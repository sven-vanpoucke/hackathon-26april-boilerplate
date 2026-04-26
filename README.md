# Hackathon x Orca — Alpaca Agents

Build AI agents on top of [Alpaca Markets](https://alpaca.markets) through [Orca](https://orcaplatform.ai) — the orchestration layer for AI agents.

This boilerplate ships the **Broker Agent** — a brokerage operations assistant that onboards customers (KYC), funds accounts (ACH), moves cash (journals), and trades on behalf of end-users via the [Alpaca Broker API](https://docs.alpaca.markets/docs/broker-api).

> The Broker API is for **your customers'** accounts — it's what fintechs, neobanks, and robo-advisors build on top of.

---

## The Challenge

The agent receives natural-language messages from users via Orca and responds by calling the appropriate Alpaca API.

Some ideas:

**Broker Agent**
- *"Onboard a new customer named Jane Doe, email jane@example.com"*
- *"Show me all accounts that joined this week"*
- *"Fund account ABC123 with $1,000 from their linked bank"*
- *"Move $500 from house account to customer ABC123"*
- *"Place a market buy of 10 SPY for customer ABC123"*
- *"Why did the last ACH transfer for ABC123 fail?"*

---

## Quick Start

### Run the agent

```bash
git clone <repo-url> && cd boilerplate-alpaca

cd broker-agent
pip install -r requirements.txt
python main.py
# → http://localhost:8001
```

### Run with Docker

```bash
docker compose up --build
# broker-agent → http://localhost:8001
```

> **API keys** (`ALPACA_API_KEY`, `ALPACA_BROKER_API_KEY`, `OPENAI_API_KEY`, etc.) are configured in the Orca admin panel and delivered to your agent in every request via `data.variables`. Use `Variables(data.variables).get("VARIABLE_NAME")` — no local environment variables needed.

---

## Project Structure

```
├── broker-agent/
│   ├── main.py              ← Broker API agent (START HERE)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── docker-compose.yml
├── docker-compose.yml       ← Runs the agent
├── .gitignore
└── README.md
```

---

## Variables (set in Orca admin panel)

### Broker Agent

| Variable | Description |
|----------|-------------|
| `ALPACA_BROKER_API_KEY` | Your Alpaca **Broker** API key |
| `ALPACA_BROKER_SECRET_KEY` | Your Alpaca **Broker** secret key |
| `ALPACA_BROKER_SANDBOX` | `"true"` (default, `https://broker-api.sandbox.alpaca.markets`) or `"false"` (live) |
| `OPENAI_API_KEY` | Optional — for LLM-based intent parsing |

> Always start in **sandbox** mode. Sign up for the Broker sandbox at [broker-app.alpaca.markets/sign-up](https://broker-app.alpaca.markets/sign-up).

---

## Trading API Quick Reference

Install: `pip install alpaca-py`

```python
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.requests import MarketOrderRequest
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
quote = market_data.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols="AAPL"))
ask   = quote["AAPL"].ask_price

# Place a market buy order
order = trading.submit_order(MarketOrderRequest(
    symbol="AAPL", qty=1, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
))

# Cancel all open orders / close all positions
trading.cancel_orders()
trading.close_all_positions(cancel_orders=True)
```

---

## Broker API Quick Reference

Install: `pip install alpaca-py`

```python
from alpaca.broker.client import BrokerClient
from alpaca.broker.requests import (
    CreateAccountRequest, CreateACHRelationshipRequest,
    CreateACHTransferRequest, CreateJournalRequest, MarketOrderRequest,
)
from alpaca.broker.models import Contact, Identity, Disclosures, Agreement
from alpaca.broker.enums import (
    TaxIdType, FundingSource, AgreementType,
    TransferDirection, TransferTiming, JournalEntryType,
)
from alpaca.trading.enums import OrderSide, TimeInForce

broker = BrokerClient(broker_api_key, broker_secret_key, sandbox=True)

# 1. Onboard a new customer (KYC)
account = broker.create_account(CreateAccountRequest(
    contact=Contact(...),
    identity=Identity(..., tax_id_type=TaxIdType.USA_SSN,
                      funding_source=[FundingSource.EMPLOYMENT_INCOME]),
    disclosures=Disclosures(...),
    agreements=[Agreement(agreement=AgreementType.CUSTOMER, ...)],
))

# 2. Link a bank account & fund it
ach = broker.create_ach_relationship_for_account(
    account_id=account.id,
    ach_data=CreateACHRelationshipRequest(...),
)
broker.create_transfer_for_account(
    account_id=account.id,
    transfer_data=CreateACHTransferRequest(
        amount="1000", direction=TransferDirection.INCOMING,
        timing=TransferTiming.IMMEDIATE, relationship_id=ach.id,
    ),
)

# 3. Move cash between accounts (journals)
broker.create_journal(CreateJournalRequest(
    from_account="<from_id>", to_account="<to_id>",
    entry_type=JournalEntryType.CASH, amount="50",
))

# 4. Trade on behalf of a customer
broker.submit_order_for_account(
    account_id=account.id,
    order_data=MarketOrderRequest(
        symbol="AAPL", qty=1, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
    ),
)

# 5. Per-customer portfolio & activity
positions  = broker.get_all_positions_for_account(account_id=account.id)
activities = broker.get_account_activities(account_id=account.id)
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

variables = Variables(data.variables)
api_key   = variables.get("ALPACA_BROKER_API_KEY")
```

### Loading Indicators, Errors, History, Usage

```python
session.loading.start("creating account")
# ... call Alpaca ...
session.loading.end("creating account")

try:
    ...
except Exception as e:
    session.error("Something went wrong", exception=e)

from orca import ChatHistoryHelper
history = ChatHistoryHelper(data.chat_history)
recent  = history.get_last_n_messages(10)

session.usage.track(tokens=1500, token_type="total")
```

---

## How It Connects

```
                  ┌──────────────────────────────► Trading Agent (8000) ──► Alpaca Trading API
  User ──► Orca Cloud
                  └──────────────────────────────► Broker  Agent (8001) ──► Alpaca Broker  API
```

---

## Judging Criteria

| Criteria | Description |
|----------|-------------|
| **Functionality** | Does it work? How many operations does it support? |
| **API Coverage** | Breadth of Alpaca features used (quotes, orders, positions, KYC, transfers, journals, …) |
| **Efficiency** | Prompt and token optimization per request |
| **Creativity** | Bonus for non-obvious use cases — e.g. an ops copilot for a brokerage, an automated onboarding agent, a customer-success bot that explains failed transfers |

---

## Tips

- Use **paper trading** (Trading API) and **sandbox** (Broker API) during development — both are free and safe
- Use **function calling** (OpenAI) or **tool use** (Anthropic) to map user intent to Alpaca actions
- Return **concise, structured responses** — the user doesn't need raw JSON
- Add dependencies to `requirements.txt` as you go (`openai`, `anthropic`, `httpx`, etc.)
- For the Broker Agent, think of the user as an **operator** at a fintech, not necessarily an end-investor
- Test your agent locally before connecting through Orca

---

## Resources

- [Alpaca Trading API Docs](https://docs.alpaca.markets/docs/trading-api)
- [Alpaca Broker API Docs](https://docs.alpaca.markets/docs/broker-api)
- [alpaca-py SDK on PyPI](https://pypi.org/project/alpaca-py/) · [GitHub](https://github.com/alpacahq/alpaca-py)
- [alpaca-py Trading reference](https://alpaca.markets/sdks/python/trading.html)
- [alpaca-py Broker reference](https://alpaca.markets/sdks/python/broker.html)
- [Orca SDK on PyPI](https://pypi.org/project/orca-platform-sdk-ui/)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic Tool Use](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)

---

Good luck. Build fast, build smart.
