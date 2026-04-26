"""Alpaca Broker API operations for TripVest.

All Alpaca-touching code lives here — KYC, ACH funding, order placement,
portfolio queries. Each public function maps 1:1 to a tool name in
`tools.py`. A teammate working on the brokerage layer can iterate here
without touching prompts or LLM wiring.
"""

from datetime import datetime, timezone

from alpaca.broker.client import BrokerClient
from alpaca.broker.requests import (
    CreateAccountRequest,
    CreateACHRelationshipRequest,
    CreateACHTransferRequest,
    MarketOrderRequest,
)
from alpaca.broker.models import Contact, Identity, Disclosures, Agreement
from alpaca.broker.enums import (
    TaxIdType,
    FundingSource,
    AgreementType,
    BankAccountType,
    TransferDirection,
    TransferTiming,
)
from alpaca.trading.enums import OrderSide, TimeInForce

from config import PORTFOLIO_ALLOCATION


def compute_trip_plan(trip_cost_eur: float, years: int = 10) -> dict:
    """Pure math — no Alpaca call. Lump-sum + monthly projections at 7%."""
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


def create_brokerage_account(
    broker: BrokerClient,
    first_name: str,
    last_name: str,
    email: str,
    date_of_birth: str,
) -> dict:
    """Open a real Alpaca sandbox account. Auto-fills US-resident stub data."""
    signed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    request = CreateAccountRequest(
        contact=Contact(
            email_address=email,
            phone_number="+15551234567",
            street_address=["20 N San Mateo Dr"],
            city="San Mateo",
            state="CA",
            postal_code="94401",
            country="USA",
        ),
        identity=Identity(
            given_name=first_name,
            family_name=last_name,
            date_of_birth=date_of_birth,
            tax_id="615-30-6411",
            tax_id_type=TaxIdType.USA_SSN,
            country_of_citizenship="USA",
            country_of_birth="USA",
            country_of_tax_residence="USA",
            funding_source=[FundingSource.EMPLOYMENT_INCOME],
        ),
        disclosures=Disclosures(
            is_control_person=False,
            is_affiliated_exchange_or_finra=False,
            is_politically_exposed=False,
            immediate_family_exposed=False,
        ),
        agreements=[
            Agreement(
                agreement=AgreementType.MARGIN,
                signed_at=signed_at,
                ip_address="127.0.0.1",
            ),
            Agreement(
                agreement=AgreementType.ACCOUNT,
                signed_at=signed_at,
                ip_address="127.0.0.1",
            ),
            Agreement(
                agreement=AgreementType.CUSTOMER,
                signed_at=signed_at,
                ip_address="127.0.0.1",
            ),
        ],
    )
    account = broker.create_account(request)
    return {
        "account_id": str(account.id),
        "account_number": str(account.account_number),
        "status": str(account.status),
    }


def fund_account(
    broker: BrokerClient,
    account_id: str,
    amount_eur: float,
) -> dict:
    """Create ACH relationship + INSTANT incoming transfer in sandbox."""
    ach = broker.create_ach_relationship_for_account(
        account_id=account_id,
        ach_data=CreateACHRelationshipRequest(
            account_owner_name="TripVest Holder",
            bank_account_type=BankAccountType.CHECKING,
            bank_account_number="32131231abc",
            bank_routing_number="121000358",
            nickname="Primary",
        ),
    )
    transfer = broker.create_transfer_for_account(
        account_id=account_id,
        transfer_data=CreateACHTransferRequest(
            amount=str(amount_eur),
            direction=TransferDirection.INCOMING,
            timing=TransferTiming.IMMEDIATE,
            relationship_id=ach.id,
        ),
    )
    return {
        "transfer_id": str(transfer.id),
        "status": str(transfer.status),
        "amount_eur": amount_eur,
    }


def invest_starter_portfolio(
    broker: BrokerClient,
    account_id: str,
    amount_eur: float,
) -> dict:
    """Place 3 notional market orders on the account per PORTFOLIO_ALLOCATION."""
    orders = []
    for symbol, weight, label in PORTFOLIO_ALLOCATION:
        slice_amount = round(amount_eur * weight, 2)
        order = broker.submit_order_for_account(
            account_id=account_id,
            order_data=MarketOrderRequest(
                symbol=symbol,
                notional=slice_amount,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            ),
        )
        orders.append({
            "symbol": symbol,
            "label": label,
            "amount_eur": slice_amount,
            "order_id": str(order.id),
            "status": str(order.status),
        })
    return {"orders": orders, "total_invested_eur": amount_eur}


def get_portfolio(broker: BrokerClient, account_id: str) -> dict:
    """Return cash, positions and total value for an account."""
    positions = broker.get_all_positions_for_account(account_id=account_id)
    trade_account = broker.get_trade_account_by_id(account_id)
    return {
        "cash_eur": float(trade_account.cash or 0),
        "portfolio_value_eur": float(trade_account.portfolio_value or 0),
        "positions": [
            {
                "symbol": p.symbol,
                "qty": float(p.qty or 0),
                "market_value_eur": float(p.market_value or 0),
            }
            for p in positions
        ],
    }


def run_tool(broker: BrokerClient, name: str, args: dict) -> dict:
    """Dispatch a tool call by name. Raises ValueError for unknown names."""
    if name == "compute_trip_plan":
        return compute_trip_plan(**args)
    if name == "create_brokerage_account":
        return create_brokerage_account(broker, **args)
    if name == "fund_account":
        return fund_account(broker, **args)
    if name == "invest_starter_portfolio":
        return invest_starter_portfolio(broker, **args)
    if name == "get_portfolio":
        return get_portfolio(broker, **args)
    raise ValueError(f"unknown tool: {name}")
