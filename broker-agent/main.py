import logging
from orca import create_agent_app, ChatMessage, OrcaHandler, Variables, ChatHistoryHelper

logger = logging.getLogger(__name__)


async def process_message(data: ChatMessage):
    handler = OrcaHandler()
    session = handler.begin(data)

    try:
        variables = Variables(data.variables)

        # ── Alpaca Broker credentials (set these in the Orca admin panel) ─────
        # Broker API uses a different key pair than the Trading API.
        # Sign up for Broker API sandbox: https://broker-app.alpaca.markets/sign-up
        #
        # broker_api_key    = variables.get("ALPACA_BROKER_API_KEY")
        # broker_secret_key = variables.get("ALPACA_BROKER_SECRET_KEY")
        # sandbox           = variables.get("ALPACA_BROKER_SANDBOX") != "false"
        #   Sandbox: https://broker-api.sandbox.alpaca.markets
        #   Live:    https://broker-api.alpaca.markets
        #
        # LLM key (optional, for intent understanding):
        # openai_key = variables.get("OPENAI_API_KEY")
        # ─────────────────────────────────────────────────────────────────────

        # ── Set up the Alpaca Broker client ───────────────────────────────────
        # from alpaca.broker.client import BrokerClient
        # from alpaca.broker.requests import (
        #     CreateAccountRequest,
        #     CreateACHRelationshipRequest,
        #     CreateACHTransferRequest,
        #     CreateJournalRequest,
        #     MarketOrderRequest,
        # )
        # from alpaca.broker.models import (
        #     Contact, Identity, Disclosures, Agreement,
        # )
        # from alpaca.broker.enums import (
        #     TaxIdType, FundingSource, AgreementType,
        #     TransferDirection, TransferTiming, JournalEntryType,
        # )
        # from alpaca.trading.enums import OrderSide, TimeInForce
        #
        # broker = BrokerClient(broker_api_key, broker_secret_key, sandbox=sandbox)
        # ─────────────────────────────────────────────────────────────────────

        # ── Common Broker API operations ──────────────────────────────────────
        #
        # 1) Onboard a new end-user (KYC):
        # account_req = CreateAccountRequest(
        #     contact=Contact(
        #         email_address="jane.doe@example.com",
        #         phone_number="+15551234567",
        #         street_address=["123 Main St"],
        #         city="San Francisco",
        #         state="CA",
        #         postal_code="94103",
        #         country="USA",
        #     ),
        #     identity=Identity(
        #         given_name="Jane",
        #         family_name="Doe",
        #         date_of_birth="1990-01-15",
        #         tax_id="123-45-6789",
        #         tax_id_type=TaxIdType.USA_SSN,
        #         country_of_citizenship="USA",
        #         country_of_birth="USA",
        #         country_of_tax_residence="USA",
        #         funding_source=[FundingSource.EMPLOYMENT_INCOME],
        #     ),
        #     disclosures=Disclosures(
        #         is_control_person=False,
        #         is_affiliated_exchange_or_finra=False,
        #         is_politically_exposed=False,
        #         immediate_family_exposed=False,
        #     ),
        #     agreements=[
        #         Agreement(agreement=AgreementType.MARGIN, signed_at="2025-01-01T00:00:00Z", ip_address="127.0.0.1"),
        #         Agreement(agreement=AgreementType.ACCOUNT, signed_at="2025-01-01T00:00:00Z", ip_address="127.0.0.1"),
        #         Agreement(agreement=AgreementType.CUSTOMER, signed_at="2025-01-01T00:00:00Z", ip_address="127.0.0.1"),
        #     ],
        # )
        # account = broker.create_account(account_req)
        #
        # 2) List / fetch accounts:
        # accounts = broker.list_accounts()
        # account  = broker.get_account_by_id("<account_id>")
        #
        # 3) Link a bank (ACH relationship) and fund the account:
        # ach = broker.create_ach_relationship_for_account(
        #     account_id=account.id,
        #     ach_data=CreateACHRelationshipRequest(
        #         account_owner_name="Jane Doe",
        #         bank_account_type="CHECKING",
        #         bank_account_number="32131231abc",
        #         bank_routing_number="121000358",
        #     ),
        # )
        # transfer = broker.create_transfer_for_account(
        #     account_id=account.id,
        #     transfer_data=CreateACHTransferRequest(
        #         amount="1000",
        #         direction=TransferDirection.INCOMING,
        #         timing=TransferTiming.IMMEDIATE,
        #         relationship_id=ach.id,
        #     ),
        # )
        #
        # 4) Move cash between accounts (journals):
        # journal = broker.create_journal(CreateJournalRequest(
        #     from_account="<from_account_id>",
        #     to_account="<to_account_id>",
        #     entry_type=JournalEntryType.CASH,
        #     amount="50",
        # ))
        #
        # 5) Trade on behalf of an end-user:
        # order = broker.submit_order_for_account(
        #     account_id=account.id,
        #     order_data=MarketOrderRequest(
        #         symbol="AAPL",
        #         qty=1,
        #         side=OrderSide.BUY,
        #         time_in_force=TimeInForce.DAY,
        #     ),
        # )
        #
        # 6) Per-user portfolio / activity:
        # positions  = broker.get_all_positions_for_account(account_id=account.id)
        # activities = broker.get_account_activities(account_id=account.id)
        # ─────────────────────────────────────────────────────────────────────

        # ── Chat history ──────────────────────────────────────────────────────
        # history = ChatHistoryHelper(data.chat_history)
        # recent  = history.get_last_n_messages(10)
        # ─────────────────────────────────────────────────────────────────────

        # ── Your agent logic goes here ────────────────────────────────────────
        #
        # Suggested flow:
        # 1. Use an LLM to understand what the operator/end-user wants
        #    (onboard a new customer, fund an account, place an order on
        #    behalf of a customer, generate a portfolio summary, move cash,
        #    investigate failed transfers, etc.)
        # 2. Resolve the target account (by id, email, or context)
        # 3. Call the appropriate Broker API methods above
        # 4. Stream a friendly, concise response back to the user
        #
        # session.loading.start("creating account")
        # ... call BrokerClient ...
        # session.loading.end("creating account")
        # session.stream(f"Account {account.id} created for {account.contact.email_address}")
        # ─────────────────────────────────────────────────────────────────────

        session.stream("Alpaca broker agent is not implemented yet.")
        session.close()

    except Exception as e:
        logger.exception("Error processing message")
        session.error("Something went wrong.", exception=e)


app, orca = create_agent_app(
    process_message_func=process_message,
    title="Alpaca Broker Agent",
    description="AI brokerage operations assistant powered by the Alpaca Broker API and Orca",
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
