"""Midora broker agent — Orca entry point and Anthropic tool-use loop.

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
import re
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


# ─────────────────────────────────────────────────────────────────────────
# Session state — keeps account_id / ach_relationship_id / archetype across
# turns so the LLM can't drop them on the floor between Stage 8 (bank link)
# and Stage 9 (fund + invest). Source of truth is the dict, not chat text.
# ─────────────────────────────────────────────────────────────────────────

_STATE_KEYS = ("account_id", "ach_relationship_id", "archetype")

# Tool name → arg names that may be filled from session state when the
# model omits them.
_STATE_FILLS: dict[str, tuple[str, ...]] = {
    "setup_bank_funding": ("account_id",),
    "transfer_funds": ("account_id", "ach_relationship_id"),
    "invest_portfolio": ("account_id", "archetype"),
    "get_portfolio": ("account_id",),
}

_session_state: dict[str, dict[str, Any]] = {}
_session_state_lock = threading.Lock()

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_ARCHETYPE_RE = re.compile(r"\b(conservative|balanced|growth)\b", re.IGNORECASE)


def _get_state(thread_id: str) -> dict[str, Any]:
    if not thread_id:
        return {}
    with _session_state_lock:
        return dict(_session_state.get(thread_id, {}))


def _update_state(thread_id: str, updates: dict[str, Any]) -> None:
    if not thread_id or not updates:
        return
    with _session_state_lock:
        existing = _session_state.setdefault(thread_id, {})
        for k, v in updates.items():
            if v:
                existing[k] = v


def _extract_state_from_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    return {k: result[k] for k in _STATE_KEYS if result.get(k)}


def _fill_args_from_state(name: str, args: dict, state: dict) -> dict:
    keys = _STATE_FILLS.get(name)
    if not keys:
        return args
    out = dict(args)
    for key in keys:
        if not out.get(key) and state.get(key):
            out[key] = state[key]
    return out


def _state_addendum(state: dict) -> str:
    if not any(state.get(k) for k in _STATE_KEYS):
        return ""
    lines = [
        "",
        "═══════════════════════════════════════════════════════",
        "SESSION STATE — already established this conversation.",
        "Pass these to tools verbatim; do NOT ask the user again.",
        "═══════════════════════════════════════════════════════",
    ]
    if state.get("account_id"):
        lines.append(f"- account_id = {state['account_id']}")
    if state.get("ach_relationship_id"):
        lines.append(f"- ach_relationship_id = {state['ach_relationship_id']}")
    if state.get("archetype"):
        lines.append(f"- archetype = {state['archetype']}")
    return "\n".join(lines)


def _seed_state_from_history(thread_id: str, messages: list) -> None:
    """Best-effort recovery if the in-memory store was lost (server restart).
    Scans prior assistant text for UUIDs and archetype mentions. Heuristic:
    first distinct UUID = account_id (announced first in Stage 7), second =
    ach_relationship_id (Stage 8). Only fills slots that aren't already set."""
    if not thread_id:
        return
    state = _get_state(thread_id)
    if all(state.get(k) for k in _STATE_KEYS):
        return

    text_parts = []
    for m in messages:
        c = m.get("content")
        if m.get("role") == "assistant" and isinstance(c, str):
            text_parts.append(c)
    text = "\n".join(text_parts)
    if not text:
        return

    updates: dict[str, Any] = {}

    if not state.get("archetype"):
        archetype_hits = _ARCHETYPE_RE.findall(text)
        if archetype_hits:
            # Last mention wins — covers the case where the user switched.
            updates["archetype"] = archetype_hits[-1].lower()

    if not state.get("account_id") or not state.get("ach_relationship_id"):
        seen: list[str] = []
        for u in _UUID_RE.findall(text):
            if u not in seen:
                seen.append(u)
        if seen and not state.get("account_id"):
            updates["account_id"] = seen[0]
        if len(seen) > 1 and not state.get("ach_relationship_id"):
            updates["ach_relationship_id"] = seen[1]

    _update_state(thread_id, updates)


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

        thread_id = str(getattr(data, "thread_id", "") or "")
        _seed_state_from_history(thread_id, messages)

        total_input_tokens = 0
        total_output_tokens = 0
        final_text = ""

        for _ in range(MAX_TOOL_TURNS):
            state = _get_state(thread_id)
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT + _state_addendum(state),
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
                # Refresh state inside the loop — a prior block in this
                # same response may have produced new IDs (e.g. setup_bank
                # → transfer_funds in one turn).
                current_state = _get_state(thread_id)
                filled_args = _fill_args_from_state(
                    block.name, dict(block.input), current_state
                )
                try:
                    result = run_tool(broker, block.name, filled_args)
                except ValidationError as exc:
                    result = {"error": str(exc)}
                except Exception as exc:
                    logger.exception("tool %s failed", block.name)
                    result = {"error": str(exc)}
                _update_state(thread_id, _extract_state_from_result(result))
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
    title="Midora Advisor",
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
    # DevStreamClient captures everything emitted to the channel, including
    # Orca's loading-state pseudo-events ([orca.loading.<kind>.start/end])
    # that are meant for the hosted UI. Strip them so the browser sees a
    # clean reply.
    reply = re.sub(r"\[orca\.[^\]]*\]", "", reply).strip()
    if not reply:
        reply = "(no reply)"
    return {"reply": reply, "thread_id": msg.thread_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
