"""TripVest broker agent — Orca entry point and Anthropic tool-use loop.

Owns:
  - request handling (Orca session lifecycle)
  - chat history → Anthropic messages conversion
  - tool-use loop (call Anthropic, dispatch tools, feed results back)
  - a thin custom-UI endpoint so the local web/chat.html can talk to the
    same agent without going through Orca's hosted UI

Everything else is split out so multiple teammates can work in parallel:
  - prompts.py     → SYSTEM_PROMPT (copy / UX)
  - tools.py       → tool schemas (kept in OpenAI shape, converted at runtime)
  - alpaca_ops.py  → Alpaca Broker API calls + run_tool dispatch
  - config.py      → MODEL, MAX_TOOL_TURNS
"""

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

os.environ.setdefault("ORCA_DEV_MODE", "true")

from anthropic import Anthropic
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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
from validation import ValidationError


logger = logging.getLogger(__name__)


def _to_anthropic_tools(tools: list) -> list:
    """tools.py keeps the OpenAI shape so non-engineers can edit it freely.
    Convert at startup to Anthropic's input_schema shape."""
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in tools
    ]


_ANTHROPIC_TOOLS = _to_anthropic_tools(TOOLS)


# Orca fires process_message twice with the same message_id. Track which
# IDs we've already started processing and skip duplicates.
_processed_message_ids: set[str] = set()
_processed_lock = threading.Lock()


def _get_message_id(data) -> str | None:
    for attr in ("message_id", "uuid", "id", "message_uuid"):
        v = getattr(data, attr, None)
        if v:
            return str(v)
    return None


async def process_message(data: ChatMessage):
    handler = OrcaHandler()
    session = handler.begin(data)

    msg_id = _get_message_id(data)
    if msg_id:
        with _processed_lock:
            if msg_id in _processed_message_ids:
                logger.warning("Skipping duplicate fire of message_id=%s", msg_id)
                try:
                    session.close()
                except Exception:
                    logger.exception("Failed to close dup session")
                return
            _processed_message_ids.add(msg_id)
            if len(_processed_message_ids) > 1000:
                _processed_message_ids.clear()

    try:
        variables = Variables(data.variables)
        anthropic_key = (
            variables.get("MADHACK-ANTHROPIC-KEY")
            or variables.get("ANTHROPIC_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
        )
        broker_key = (
            variables.get("ALPACA_BROKER_API_KEY")
            or os.getenv("ALPACA_BROKER_API_KEY")
        )
        broker_secret = (
            variables.get("ALPACA_BROKER_SECRET_KEY")
            or os.getenv("ALPACA_BROKER_SECRET_KEY")
        )
        sandbox_raw = (
            variables.get("ALPACA_BROKER_SANDBOX")
            or os.getenv("ALPACA_BROKER_SANDBOX")
            or ""
        )
        sandbox = sandbox_raw.lower() != "false"

        missing = [
            name
            for name, value in (
                ("ANTHROPIC_API_KEY", anthropic_key),
                ("ALPACA_BROKER_API_KEY", broker_key),
                ("ALPACA_BROKER_SECRET_KEY", broker_secret),
            )
            if not value
        ]
        if missing:
            session.stream(
                "⚠️ Missing variables: " + ", ".join(f"`{m}`" for m in missing)
            )
            session.close()
            return

        client = Anthropic(api_key=anthropic_key)
        broker = BrokerClient(broker_key, broker_secret, sandbox=sandbox)

        history = ChatHistoryHelper(data.chat_history)
        messages: list[dict[str, Any]] = []
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
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=_ANTHROPIC_TOOLS,
                messages=messages,
            )
            if response.usage:
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

            # Persist the entire assistant turn (text + tool_use blocks)
            # so the next request includes tool_use IDs that match the
            # tool_result we send back.
            messages.append({
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            })

            if response.stop_reason != "tool_use":
                final_text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                break

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                kind = f"running {block.name}"
                session.loading.start(kind)
                try:
                    result = run_tool(broker, block.name, block.input)
                except ValidationError as exc:
                    result = {"error": str(exc)}
                except Exception as exc:
                    logger.exception("tool %s failed", block.name)
                    result = {"error": str(exc)}
                session.loading.end(kind)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
            messages.append({"role": "user", "content": tool_results})
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

# Allow the Vercel-hosted chat UI to call this backend cross-origin.
# Sandbox demo — allow_origins="*" is fine; tighten for prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Custom UI — local chat at "/" and a wrapper endpoint that builds an
# Orca-shaped ChatMessage from env-supplied secrets so the browser never
# sees a key.

_WEB_DIR = Path(__file__).parent / "web"
_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "MADHACK-ANTHROPIC-KEY",
    "ALPACA_BROKER_API_KEY",
    "ALPACA_BROKER_SECRET_KEY",
    "ALPACA_BROKER_SANDBOX",
)


@app.get("/")
async def _root():
    return FileResponse(_WEB_DIR / "chat.html")


@app.post("/api/chat/send")
async def _custom_chat_send(req: Request):
    from orca.domain import Variable
    from orca.infrastructure.dev_stream_client import DevStreamClient

    body = await req.json()
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    history = body.get("history") or []
    channel = f"web-{uuid.uuid4().hex}"

    msg = ChatMessage(
        thread_id=body.get("thread_id") or channel,
        model=MODEL,
        message=message,
        conversation_id=0,
        response_uuid=str(uuid.uuid4()),
        message_uuid=str(uuid.uuid4()),
        channel=channel,
        variables=[
            Variable(name=k, value=os.getenv(k, ""))
            for k in _ENV_KEYS
            if os.getenv(k)
        ],
        url="",
        chat_history=history,
    )
    await process_message(msg)
    stream = DevStreamClient.get_stream(channel)
    reply = stream.get("full_response") or "(no reply)"
    return {"reply": reply, "thread_id": msg.thread_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
