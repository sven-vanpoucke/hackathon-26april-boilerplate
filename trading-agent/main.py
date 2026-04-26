"""
TripVest Advisor — chat agent for university students 18–25.

Pitch: invest a little today, money roughly doubles in ~10 years
(Rule of 72, ~7% annual return), so a future trip is effectively
50% off in 2036.

Single-agent design backed by Anthropic tool use. Three stages:
1. Discovery   — collect trip cost, run the math
2. Sign-up     — collect name / email / DOB (conversational)
3. Investing   — place 60/30/10 paper orders (VOO / BND / GLD)

Note: Backed by a single shared Alpaca paper account (the
hackathon's Trading API key). For a real product each student
would get their own account via the Broker API — see the
sibling broker-agent/ for that shape.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from openai import OpenAI
from orca import (
    create_agent_app,
    ChatMessage,
    OrcaHandler,
    Variables,
    ChatHistoryHelper,
)

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


logger = logging.getLogger(__name__)

MODEL = "gpt-4o"
MAX_TOOL_TURNS = 8

# Starter portfolio: stocks / bonds / gold (US ETFs, fractional-eligible)
PORTFOLIO_ALLOCATION = [
    ("VOO", 0.60, "global stocks (S&P 500)"),
    ("BND", 0.30, "bonds"),
    ("GLD", 0.10, "gold"),
]

SYSTEM_PROMPT = """You are TripVest, a friendly investment buddy for university students aged 18–25.

THE BIG IDEA: invest a little today and in ~10 years your money roughly
doubles (Rule of 72, ~7% annual return). That means a future trip costs
HALF as much in real terms — the 2036 trip is effectively 50% off when
you start today.

Be warm, motivational, conversational. Plain language — no finance jargon.
Use emoji sparingly (✈️ 💰 📈 🌍 🎒). One question at a time.

═══════════════════════════════════════════════════════
STAGE 1 — DISCOVERY (the dream)
═══════════════════════════════════════════════════════

Ask in this order, ONE AT A TIME:

1. Dream destination — "Where do you want to wake up in 2036?"
2. Estimated trip cost in EUR — if they're unsure, suggest typical anchors:
   €2,000 (short trip) / €5,000 (mid) / €10,000 (big adventure).
3. How they'd rather invest, framed plainly (NEVER say "lump sum" — it
   sounds scary):
      • "Pay it all in one go"
      • "Save a little each month"
      • "Both — kickstart now + monthly after"

Then call `compute_trip_plan` and reply with ONE warm sentence translating
the math into plain language. Don't dump raw numbers — say things like
"€100/month gets you the full Hong Kong trip" or "€2,500 today doubles
into your full €5,000 trip in 2036." End by inviting them to open their
TripVest account.

═══════════════════════════════════════════════════════
STAGE 2 — SIGN-UP (the account)
═══════════════════════════════════════════════════════

Ask all 4 details in ONE batched question:

   "Just need 4 quick things to open your account — drop them all in
   one message: first name, last name, email, and your birthday."

Birthday parsing: accept ANY format the user types ("15 March 2002",
"15/03/2002", "March 15, 2002", "2002-03-15", "15-3-02", etc.). Parse
it yourself and silently normalize to YYYY-MM-DD before calling
`register_student`. NEVER ask the user to reformat their date.

Read back the 4 fields in one line, ask "shall I open your account?",
wait for an explicit yes, then call `register_student`.

═══════════════════════════════════════════════════════
STAGE 3 — INVEST (the small first step)
═══════════════════════════════════════════════════════

CRITICAL: do NOT push the student into investing the full lump-sum
number from Stage 1 — that scares people off. Most students don't have
€2,500 lying around.

Instead ask: "How much would you like to start with TODAY? Pick what
feels comfortable — most students start small:"

   • €25 — a coffee a week
   • €50 — pizza night
   • €100 — a nice dinner out
   • €500 — a serious starter
   • or any custom amount

Once they pick (call this AMOUNT), give them the projection in one line:
"€[AMOUNT] today → about €[AMOUNT × 2] in 2036 (at ~7% growth). That's
[X]% of your [destination] trip. Every bit gets you closer 🎯"

Then a single confirmation: "Ready to put €[AMOUNT] into the starter
portfolio (60% global stocks, 30% bonds, 10% gold)?" Wait for an
explicit yes, then call `invest_starter_portfolio` with
`amount_eur=AMOUNT`.

After the orders return, present a clean closing card like this
(adapt the destination & numbers):

   🎒 **Trip Fund opened!**

   - Global stocks (VOO): €X
   - Bonds (BND):         €X
   - Gold (GLD):          €X

   Projected value in 2036: ~€[AMOUNT × 2]

   See you in [destination] in 2036 ✈️

   _Demo only — your €[AMOUNT] was invested from a TripVest preview
   wallet. In production, you'd link your own bank to fund deposits.
   US market closed on weekends so orders show as "accepted" until
   Monday open. Illustrative ~7% returns, not financial advice._

═══════════════════════════════════════════════════════
ANYTIME
═══════════════════════════════════════════════════════

After investing, the student can ask "how's my portfolio?" / "what's it
worth now?" any time → call `get_account_summary` and present cleanly.

═══════════════════════════════════════════════════════
GLOBAL RULES
═══════════════════════════════════════════════════════

- Always show money in EUR with the € symbol.
- ALWAYS confirm before opening account or placing trades. Wait for an
  explicit yes.
- NEVER ask for the same info twice — read chat history first.
- NEVER invent IDs, account numbers, or order IDs. Use ONLY values
  returned by tool calls. Once you have an account_id, include it in
  your replies so it stays in conversation history.
- US market closed on weekends → orders may come back as "accepted" or
  "pending_new" instead of "filled". That is normal — mention briefly.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compute_trip_plan",
            "description": (
                "Compute lump-sum and monthly investment needed to fund a "
                "future trip, assuming ~7% annual return (money roughly "
                "doubles in 10 years per the Rule of 72)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_cost_eur": {
                        "type": "number",
                        "description": "Estimated trip cost in EUR.",
                    },
                    "years": {
                        "type": "integer",
                        "description": "Years until the trip. Default 10.",
                    },
                },
                "required": ["trip_cost_eur"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_student",
            "description": (
                "Open a TripVest account for the student. Only call after "
                "the student explicitly confirms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "email": {"type": "string"},
                    "date_of_birth": {
                        "type": "string",
                        "description": "YYYY-MM-DD",
                    },
                },
                "required": [
                    "first_name",
                    "last_name",
                    "email",
                    "date_of_birth",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "invest_starter_portfolio",
            "description": (
                "Invest the EUR amount across the starter portfolio: 60% VOO "
                "(stocks), 30% BND (bonds), 10% GLD (gold). Only call after "
                "the student explicitly confirms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "TripVest account id from register_student.",
                    },
                    "amount_eur": {"type": "number"},
                },
                "required": ["account_id", "amount_eur"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_summary",
            "description": "Return current cash and total portfolio value for the underlying Alpaca paper account.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


# ── Tool implementations ──────────────────────────────────────────────────


def _tool_compute_trip_plan(trip_cost_eur: float, years: int = 10) -> dict:
    annual_rate = 0.07
    monthly_rate = annual_rate / 12
    months = years * 12
    fv_factor = ((1 + monthly_rate) ** months - 1) / monthly_rate
    monthly_to_full_trip = trip_cost_eur / fv_factor
    lump_sum_today = trip_cost_eur / ((1 + annual_rate) ** years)
    out_of_pocket_monthly = monthly_to_full_trip * months
    growth_share_pct = round(
        (1 - out_of_pocket_monthly / trip_cost_eur) * 100
    )
    return {
        "trip_cost_eur": round(trip_cost_eur, 2),
        "years": years,
        "lump_sum_today_eur": round(lump_sum_today, 2),
        "monthly_eur": round(monthly_to_full_trip, 2),
        "out_of_pocket_monthly_total_eur": round(out_of_pocket_monthly, 2),
        "growth_share_pct": growth_share_pct,
    }


def _tool_register_student(
    first_name: str,
    last_name: str,
    email: str,
    date_of_birth: str,
) -> dict:
    return {
        "account_id": f"TV-{uuid.uuid4().hex[:8].upper()}",
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "date_of_birth": date_of_birth,
        "opened_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "ACTIVE",
    }


def _tool_invest_starter_portfolio(
    trading: TradingClient,
    account_id: str,
    amount_eur: float,
) -> dict:
    orders = []
    for symbol, weight, label in PORTFOLIO_ALLOCATION:
        slice_amount = round(amount_eur * weight, 2)
        order = trading.submit_order(
            order_data=MarketOrderRequest(
                symbol=symbol,
                notional=slice_amount,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
        )
        orders.append({
            "symbol": symbol,
            "label": label,
            "amount_eur": slice_amount,
            "order_id": str(order.id),
            "status": str(order.status),
        })
    return {
        "account_id": account_id,
        "orders": orders,
        "total_invested_eur": amount_eur,
    }


def _tool_get_account_summary(trading: TradingClient) -> dict:
    account = trading.get_account()
    return {
        "cash_eur": float(account.cash or 0),
        "portfolio_value_eur": float(account.portfolio_value or 0),
        "buying_power_eur": float(account.buying_power or 0),
    }


def _run_tool(trading: TradingClient, name: str, args: dict) -> dict:
    if name == "compute_trip_plan":
        return _tool_compute_trip_plan(**args)
    if name == "register_student":
        return _tool_register_student(**args)
    if name == "invest_starter_portfolio":
        return _tool_invest_starter_portfolio(trading, **args)
    if name == "get_account_summary":
        return _tool_get_account_summary(trading)
    raise ValueError(f"unknown tool: {name}")


# ── Orca entry point ──────────────────────────────────────────────────────


async def process_message(data: ChatMessage):
    handler = OrcaHandler()
    session = handler.begin(data)

    try:
        variables = Variables(data.variables)
        openai_key = variables.get("MADHACK-OPENAI-KEY")
        alpaca_key = variables.get("ALPACA_API_KEY")
        alpaca_secret = variables.get("ALPACA_API_SECRET")

        missing = [
            name
            for name, value in (
                ("MADHACK-OPENAI-KEY", openai_key),
                ("ALPACA_API_KEY", alpaca_key),
                ("ALPACA_API_SECRET", alpaca_secret),
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
        trading = TradingClient(alpaca_key, alpaca_secret, paper=True)

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

            choice = response.choices[0]
            assistant_msg = choice.message

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
                    result = _run_tool(trading, tc.function.name, args)
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
        "Friendly investment advisor for students 18–25 — invest today, "
        "make a future trip 50% cheaper in 10 years."
    ),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
