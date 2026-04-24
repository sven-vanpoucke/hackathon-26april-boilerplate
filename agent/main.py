import logging
from orca import create_agent_app, ChatMessage, OrcaHandler, Variables, ChatHistoryHelper

logger = logging.getLogger(__name__)


async def process_message(data: ChatMessage):
    handler = OrcaHandler()
    session = handler.begin(data)

    try:
        variables = Variables(data.variables)

        # ── Alpaca credentials (set these in the Orca admin panel) ────────────
        # api_key    = variables.get("ALPACA_API_KEY")
        # secret_key = variables.get("ALPACA_SECRET_KEY")
        # base_url   = variables.get("ALPACA_BASE_URL")
        #   Paper trading: "https://paper-api.alpaca.markets"
        #   Live trading:  "https://api.alpaca.markets"
        #
        # LLM key (optional, for intent understanding):
        # openai_key = variables.get("OPENAI_API_KEY")
        # ─────────────────────────────────────────────────────────────────────

        # ── Set up the Alpaca client ──────────────────────────────────────────
        # from alpaca.trading.client import TradingClient
        # from alpaca.data.historical import StockHistoricalDataClient
        # from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
        # from alpaca.trading.enums import OrderSide, TimeInForce
        # from alpaca.data.requests import StockLatestQuoteRequest
        #
        # trading = TradingClient(api_key, secret_key, paper=True)
        # market_data = StockHistoricalDataClient(api_key, secret_key)
        # ─────────────────────────────────────────────────────────────────────

        # ── Common Alpaca operations ──────────────────────────────────────────
        #
        # Get account info:
        # account = trading.get_account()
        # buying_power = account.buying_power
        # portfolio_value = account.portfolio_value
        #
        # Get open positions:
        # positions = trading.get_all_positions()
        # for p in positions: print(p.symbol, p.qty, p.unrealized_pl)
        #
        # Get latest stock quote:
        # req = StockLatestQuoteRequest(symbol_or_symbols="AAPL")
        # quote = market_data.get_stock_latest_quote(req)
        # bid = quote["AAPL"].bid_price
        # ask = quote["AAPL"].ask_price
        #
        # Place a market order (buy):
        # order_req = MarketOrderRequest(
        #     symbol="AAPL",
        #     qty=1,
        #     side=OrderSide.BUY,
        #     time_in_force=TimeInForce.DAY,
        # )
        # order = trading.submit_order(order_req)
        #
        # Cancel all open orders:
        # trading.cancel_orders()
        #
        # Close all positions:
        # trading.close_all_positions(cancel_orders=True)
        # ─────────────────────────────────────────────────────────────────────

        # ── Chat history ──────────────────────────────────────────────────────
        # history = ChatHistoryHelper(data.chat_history)
        # recent = history.get_last_n_messages(10)
        # ─────────────────────────────────────────────────────────────────────

        # ── Your agent logic goes here ────────────────────────────────────────
        #
        # Suggested flow:
        # 1. Use an LLM to understand what the user wants
        #    (check portfolio, get a quote, place/cancel an order, etc.)
        # 2. Call the appropriate Alpaca API methods above
        # 3. Stream a friendly, concise response back to the user
        #
        # session.loading.start("fetching quote")
        # ... call Alpaca ...
        # session.loading.end("fetching quote")
        # session.stream(f"AAPL is trading at ${ask}")
        # ─────────────────────────────────────────────────────────────────────

        session.stream("Alpaca trading agent is not implemented yet.")
        session.close()

    except Exception as e:
        logger.exception("Error processing message")
        session.error("Something went wrong.", exception=e)


app, orca = create_agent_app(
    process_message_func=process_message,
    title="Alpaca Trading Agent",
    description="AI trading assistant powered by Alpaca Markets and Orca",
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
