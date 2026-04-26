"""TripVest broker agent — Orca entry point and OpenAI tool-use loop.

This file is intentionally small. It owns:
  - request handling (Orca session lifecycle)
  - chat history → OpenAI messages conversion
  - the tool-use loop (call OpenAI, dispatch tool calls, feed results back)

Everything else is split out so multiple teammates can work in parallel
without merge conflicts:
  - prompts.py     → SYSTEM_PROMPT (copy / UX)
  - tools.py       → OpenAI tool schema (LLM contract)
  - alpaca_ops.py  → Alpaca Broker API calls + run_tool dispatch
  - config.py      → MODEL, MAX_TOOL_TURNS, PORTFOLIO_ALLOCATION
"""

import json
import logging

from openai import OpenAI
from orca import (
    create_agent_app,
    ChatMessage,
    OrcaHandler,
    Variables,
    ChatHistoryHelper,
)

from alpaca.broker.client import BrokerClient

from config import MODEL, MAX_TOOL_TURNS
from prompts import SYSTEM_PROMPT
from tools import TOOLS
from alpaca_ops import run_tool


logger = logging.getLogger(__name__)


async def process_message(data: ChatMessage):
    handler = OrcaHandler()
    session = handler.begin(data)

    try:
        variables = Variables(data.variables)
        openai_key = variables.get("MADHACK-OPENAI-KEY")
        broker_key = variables.get("ALPACA_BROKER_API_KEY")
        broker_secret = variables.get("ALPACA_BROKER_SECRET_KEY")
        sandbox = variables.get("ALPACA_BROKER_SANDBOX") != "false"

        missing = [
            name
            for name, value in (
                ("MADHACK-OPENAI-KEY", openai_key),
                ("ALPACA_BROKER_API_KEY", broker_key),
                ("ALPACA_BROKER_SECRET_KEY", broker_secret),
            )
            if not value
        ]
        if missing:
            session.stream(
                "⚠️ Missing variables in the Orca admin panel: "
                + ", ".join(f"`{m}`" for m in missing)
            )
            session.close()
            return

        openai = OpenAI(api_key=openai_key)
        broker = BrokerClient(broker_key, broker_secret, sandbox=sandbox)

        history = ChatHistoryHelper(data.chat_history)
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in history.get_messages():
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": data.message})

        total_input_tokens = 0
        total_output_tokens = 0
        final_text = ""

        for _ in range(MAX_TOOL_TURNS):
            response = openai.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
            )
            if response.usage:
                total_input_tokens += response.usage.prompt_tokens
                total_output_tokens += response.usage.completion_tokens

            assistant_msg = response.choices[0].message

            if not assistant_msg.tool_calls:
                final_text = assistant_msg.content or ""
                break

            messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ],
            })

            for tc in assistant_msg.tool_calls:
                kind = f"running {tc.function.name}"
                session.loading.start(kind)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = run_tool(broker, tc.function.name, args)
                except Exception as exc:
                    logger.exception("tool %s failed", tc.function.name)
                    result = {"error": str(exc)}
                session.loading.end(kind)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })
        else:
            final_text = (
                "I had to stop after several tool calls without finishing — "
                "could you try again or rephrase?"
            )

        if final_text.strip():
            session.stream(final_text)

        session.usage.track(
            tokens=total_input_tokens + total_output_tokens,
            token_type="total",
        )
        session.close()

    except Exception as exc:
        logger.exception("Error processing message")
        session.error("Something went wrong.", exception=exc)


app, orca = create_agent_app(
    process_message_func=process_message,
    title="TripVest Advisor",
    description=(
        "Friendly investment advisor for students 18–25 — opens a real "
        "Alpaca sandbox account, funds via ACH, and invests in a "
        "starter portfolio. Trip in 2036, half-priced if you start today."
    ),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
