# Hackathon x Orca — Alpaca Trading Agent

Build an **AI trading assistant** that connects to [Alpaca Markets](https://alpaca.markets) through [Orca](https://orcaplatform.ai) — the orchestration layer for AI agents.

---

## The Challenge

You have one agent. It receives natural language messages from users via Orca and responds by calling the **Alpaca Trading API** — fetching quotes, checking portfolios, placing and cancelling orders.

| Agent | What it does | Port |
|-------|-------------|------|
| **Trading Agent** | Understands user intent, calls Alpaca API, returns a helpful reply | 8000 |

---

## Quick Start

```bash
# 1. Clone this repo
git clone <repo-url> && cd boilerplate-alpaca

# 2. Install and run the agent
cd agent
pip install -r requirements.txt
python main.py
# → runs on http://localhost:8000
```

Or with Docker:

```bash
cd agent && docker compose up --build
```

> **API keys** (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `OPENAI_API_KEY`, etc.) are configured in the Orca admin panel and delivered to your agent in every request via `data.variables`. Use `Variables(data.variables).get("VARIABLE_NAME")` to read them — no local environment variables needed.

---

## Project Structure

```
├── agent/
│   ├── main.py              ← Your trading agent (START HERE)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── docker-compose.yml
├── .gitignore
└── README.md
```

---

## What You Need to Build

Your agent receives a message from a user (e.g. *"What's Apple's current price?"* or *"Buy 5 shares of TSLA"*) and must:

1. **Understand the request** — use an LLM (OpenAI, Anthropic, etc.)
2. **Call Alpaca** — use `alpaca-py` to interact with the trading API
3. **Reply to the user** — stream a clear, concise response via `session.stream()`

Think about: How do you parse intent? How do you handle ambiguous requests? How do you keep responses short and useful?

---

## Alpaca Variables (set in Orca admin panel)

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Your Alpaca API key ID |
| `ALPACA_SECRET_KEY` | Your Alpaca secret key |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` (paper) or `https://api.alpaca.markets` (live) |
| `OPENAI_API_KEY` | Optional — for LLM-based intent parsing |

> Start with **paper trading** — it's free, requires no real money, and behaves identically to live trading.

---

## Alpaca API Quick Reference

Install: `pip install alpaca-py`

```python
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.requests import StockLatestQuoteRequest

trading     = TradingClient(api_key, secret_key, paper=True)
market_data = StockHistoricalDataClient(api_key, secret_key)

# Account info
account = trading.get_account()
print(account.buying_power, account.portfolio_value)

# Positions
positions = trading.get_all_positions()

# Latest quote
req   = StockLatestQuoteRequest(symbol_or_symbols="AAPL")
quote = market_data.get_stock_latest_quote(req)
ask   = quote["AAPL"].ask_price

# Place a market buy order
order = trading.submit_order(MarketOrderRequest(
    symbol="AAPL",
    qty=1,
    side=OrderSide.BUY,
    time_in_force=TimeInForce.DAY,
))

# Cancel all open orders
trading.cancel_orders()

# Close all positions
trading.close_all_positions(cancel_orders=True)
```

---

## Orca SDK Cheat Sheet

Install: `pip install orca-platform-sdk-ui`

### Agent Lifecycle

```python
from orca import create_agent_app, ChatMessage, OrcaHandler

async def process_message(data: ChatMessage):
    handler = OrcaHandler()
    session = handler.begin(data)

    # ... your logic ...

    session.stream("Your response text")
    session.close()

app, orca = create_agent_app(process_message_func=process_message)
```

### Reading Variables

```python
from orca import Variables

variables  = Variables(data.variables)
api_key    = variables.get("ALPACA_API_KEY")
secret_key = variables.get("ALPACA_SECRET_KEY")
```

### Loading Indicators

```python
session.loading.start("fetching quote")
# ... call Alpaca ...
session.loading.end("fetching quote")
```

### Error Handling

```python
try:
    # your logic
except Exception as e:
    session.error("Something went wrong", exception=e)
```

### Chat History

```python
from orca import ChatHistoryHelper

history = ChatHistoryHelper(data.chat_history)
recent  = history.get_last_n_messages(10)
```

### Usage Tracking

```python
session.usage.track(tokens=1500, token_type="total")
```

---

## How It Connects

```
  User ──────► Orca Cloud ──────► Your Agent (port 8000)
                                       │
                                  alpaca-py
                                       │
                                  Alpaca API
                              (paper or live trading)
```

---

## Judging Criteria

| Criteria | Description |
|----------|-------------|
| **Functionality** | Does it work? How many trading operations does it support? |
| **API Coverage** | Breadth of Alpaca features used (quotes, orders, positions, history, etc.) |
| **Efficiency** | Prompt and token optimization per request |

---

## Tips

- Use **paper trading** during development — it's safe and free
- Use **function calling** (OpenAI) or **tool use** (Anthropic) to map user intent to Alpaca actions
- Return **concise, structured responses** — the user doesn't need raw JSON
- Add dependencies to `requirements.txt` as you go (`openai`, `anthropic`, `httpx`, etc.)
- Test your agent locally before connecting through Orca

---

## Resources

- [Alpaca Trading API Docs](https://docs.alpaca.markets/reference/getallaccounts-1)
- [alpaca-py SDK on PyPI](https://pypi.org/project/alpaca-py/)
- [alpaca-py GitHub](https://github.com/alpacahq/alpaca-py)
- [Orca SDK on PyPI](https://pypi.org/project/orca-platform-sdk-ui/)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic Tool Use](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)

---

Good luck. Build fast, build smart.
