"""Alpaca Broker API operations for TripVest.

All Alpaca-touching code lives here — KYC, suitability, ACH funding,
order placement, portfolio queries. Each public function maps 1:1 to
a tool name in `tools.py`.

Production posture: every mandatory field is collected from the user.
The only sandbox-specific stub is the agreement IP fallback when the
hosting layer doesn't surface a client IP.
"""

import json
import logging
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
    EmploymentStatus,
    TransferDirection,
    TransferTiming,
)
from alpaca.trading.enums import OrderSide, TimeInForce

from config import (
    PORTFOLIO_ARCHETYPES,
    RISK_THRESHOLDS,
    INCOME_BRACKETS,
    NET_WORTH_BRACKETS,
    LIQUID_NET_WORTH_BRACKETS,
)
from validation import (
    ValidationError,
    clean_optional_string,
    parse_and_validate_dob,
    parse_yes_no,
    validate_amount,
    validate_archetype,
    validate_bank_account_number,
    validate_city,
    validate_country,
    validate_email,
    validate_employment_status,
    validate_funding_source,
    validate_income_bracket,
    validate_liquid_net_worth_bracket,
    validate_name,
    validate_net_worth_bracket,
    validate_phone,
    validate_postal_code,
    validate_routing_number,
    validate_score_1to3,
    validate_state,
    validate_street,
    validate_tax_id,
)

logger = logging.getLogger(__name__)
audit_log = logging.getLogger("tripvest.audit")

# Fallback agreement IP used only when the runtime doesn't pass a
# client_ip — sandbox/local-dev only. Real prod must inject the actual
# client IP from the request layer.
_AGREEMENT_IP_FALLBACK = "127.0.0.1"


def _assert_sandbox(broker: BrokerClient) -> None:
    """Hard guard: this code path requires sandbox until prod-review approves."""
    sandbox_attr = getattr(broker, "_sandbox", None)
    if sandbox_attr is True:
        return
    base_url = str(getattr(broker, "_base_url", "") or getattr(broker, "base_url", ""))
    if "sandbox" in base_url.lower():
        return
    raise RuntimeError(
        "TripVest onboarding requires a sandbox BrokerClient until production review."
    )


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


def assess_suitability(
    knowledge: int,
    loss_reaction: int,
    loss_capacity: int,
    horizon_flexibility: int,
) -> dict:
    """Pure-logic MiFID-style suitability assessment.

    Each input is 1..3 (low/med/high). Returns risk archetype, recommended
    allocation, and an audit record. The LLM presents this to the user
    BEFORE account opening so they understand the recommendation.
    """
    knowledge = validate_score_1to3(knowledge, "investment knowledge")
    loss_reaction = validate_score_1to3(loss_reaction, "loss reaction")
    loss_capacity = validate_score_1to3(loss_capacity, "loss capacity")
    horizon_flexibility = validate_score_1to3(horizon_flexibility, "horizon flexibility")

    score = knowledge + loss_reaction + loss_capacity + horizon_flexibility
    if score <= RISK_THRESHOLDS["conservative_max"]:
        archetype = "conservative"
    elif score <= RISK_THRESHOLDS["balanced_max"]:
        archetype = "balanced"
    else:
        archetype = "growth"

    allocation = [
        {"symbol": s, "weight": w, "label": label}
        for s, w, label in PORTFOLIO_ARCHETYPES[archetype]
    ]

    record = {
        "type": "suitability_assessment",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "knowledge": knowledge,
            "loss_reaction": loss_reaction,
            "loss_capacity": loss_capacity,
            "horizon_flexibility": horizon_flexibility,
        },
        "score": score,
        "archetype": archetype,
        "allocation": allocation,
    }
    audit_log.info(json.dumps(record))

    return {
        "archetype": archetype,
        "score": score,
        "allocation": allocation,
        "rationale": (
            f"Score {score}/12 → {archetype}. Higher equity weight comes with "
            "higher expected return AND higher short-term swings."
        ),
    }


def _funding_sources(values) -> list[FundingSource]:
    """Map list of validated funding-source strings → Alpaca enum list."""
    if isinstance(values, str):
        values = [values]
    mapping = {
        "employment_income": FundingSource.EMPLOYMENT_INCOME,
        "investments": FundingSource.INVESTMENTS,
        "inheritance": FundingSource.INHERITANCE,
        "business_income": FundingSource.BUSINESS_INCOME,
        "savings": FundingSource.SAVINGS,
        "family": FundingSource.FAMILY,
    }
    out: list[FundingSource] = []
    for v in values:
        key = validate_funding_source(v)
        out.append(mapping[key])
    return out or [FundingSource.SAVINGS]


def _bracket_bounds(label: str, brackets: dict) -> tuple[int, int]:
    return brackets[label]


def create_brokerage_account(
    broker: BrokerClient,
    *,
    first_name: str,
    last_name: str,
    email: str,
    date_of_birth: str,
    phone: str,
    street_address: str,
    city: str,
    postal_code: str,
    country_of_residence: str,
    tax_id: str,
    employment_status: str,
    agreements_accepted: bool,
    country_of_citizenship: str | None = None,
    country_of_tax_residence: str | None = None,
    state: str | None = None,
    country_of_birth: str | None = None,
    funding_source: list | str | None = None,
    employer_name: str | None = None,
    employer_position: str | None = None,
    annual_income_bracket: str | None = None,
    total_net_worth_bracket: str | None = None,
    liquid_net_worth_bracket: str | None = None,
    is_control_person: bool | None = None,
    is_affiliated_exchange_or_finra: bool | None = None,
    is_politically_exposed: bool | None = None,
    immediate_family_exposed: bool | None = None,
    client_ip: str | None = None,
) -> dict:
    """Open an Alpaca sandbox account using the customer's real KYC data."""
    _assert_sandbox(broker)

    if not parse_yes_no(agreements_accepted, "agreements"):
        raise ValueError(
            "Cannot open the account without agreement acceptance. Confirm and try again."
        )

    first_name = validate_name(first_name, "first name")
    last_name = validate_name(last_name, "last name")
    email = validate_email(email)
    date_of_birth = parse_and_validate_dob(date_of_birth)
    phone = validate_phone(phone)
    street_address = validate_street(street_address)
    city = validate_city(city)
    postal_code = validate_postal_code(postal_code)
    country_of_residence = validate_country(country_of_residence)
    # Default citizenship + tax residence to country of residence — covers
    # the common case (someone living and paying tax where they're from).
    # The LLM only needs to override these if the user volunteered something
    # different.
    if country_of_citizenship:
        country_of_citizenship = validate_country(country_of_citizenship)
    else:
        country_of_citizenship = country_of_residence
    if country_of_tax_residence:
        country_of_tax_residence = validate_country(country_of_tax_residence)
    else:
        country_of_tax_residence = country_of_residence
    employer_name = clean_optional_string(employer_name)
    employer_position = clean_optional_string(employer_position)
    country_of_birth_clean = clean_optional_string(country_of_birth)
    country_of_birth_iso = (
        validate_country(country_of_birth_clean)
        if country_of_birth_clean else country_of_citizenship
    )
    tax_id_value, tax_id_type_str = validate_tax_id(tax_id, country_of_tax_residence)
    employment_status = validate_employment_status(employment_status)

    # Server-side autodefaults — keep the LLM out of fields it shouldn't
    # be guessing about. Track what we changed so the LLM can be honest
    # with the user about what was filled in vs. left blank.
    defaulted: list[str] = []

    # Smart defaults for the student profile (target user). These get
    # applied ONLY when the LLM left a field unset — any user-provided
    # value wins. Goal: zero stupid questions for the common case.
    is_no_employer = employment_status in {"student", "unemployed", "retired"}
    if annual_income_bracket is None:
        annual_income_bracket = "0-25k" if is_no_employer else "25k-50k"
        defaulted.append(f"annual_income defaulted to {annual_income_bracket}")
    if total_net_worth_bracket is None:
        total_net_worth_bracket = "0-25k" if is_no_employer else "25k-50k"
        defaulted.append(f"total_net_worth defaulted to {total_net_worth_bracket}")
    if liquid_net_worth_bracket is None:
        liquid_net_worth_bracket = "0-25k" if is_no_employer else "25k-50k"
        defaulted.append(f"liquid_net_worth defaulted to {liquid_net_worth_bracket}")
    if funding_source is None or funding_source == "" or funding_source == []:
        funding_source = (
            ["family"] if employment_status == "student"
            else ["employment_income"] if employment_status == "employed"
            else ["savings"]
        )
        defaulted.append(f"funding_source defaulted to {funding_source}")
    if is_control_person is None:
        is_control_person = False
        defaulted.append("is_control_person defaulted to false")
    if is_affiliated_exchange_or_finra is None:
        is_affiliated_exchange_or_finra = False
        defaulted.append("is_affiliated_exchange_or_finra defaulted to false")
    if is_politically_exposed is None:
        is_politically_exposed = False
        defaulted.append("is_politically_exposed defaulted to false")
    if immediate_family_exposed is None:
        immediate_family_exposed = False
        defaulted.append("immediate_family_exposed defaulted to false")

    # State is only meaningful for US/CA addresses. Anywhere else, force None.
    if country_of_residence in {"USA", "CAN"}:
        state = validate_state(state)
    elif state is not None:
        state = None
        defaulted.append(f"state cleared (not used for {country_of_residence})")
    else:
        state = None

    # Employer fields don't apply when the customer isn't employed.
    # Strip them even if the LLM tried to fill them with "student" /
    # the user's role / N/A / etc.
    if employment_status in {"student", "unemployed", "retired"}:
        if employer_name or employer_position:
            defaulted.append(
                f"employer fields cleared (employment_status={employment_status})"
            )
        employer_name = None
        employer_position = None
    else:
        # Employed: a single bare 'student' or job-status word isn't an employer.
        if employer_name and employer_name.strip().lower() in {
            "student", "unemployed", "retired", "self", "myself", "me",
        }:
            employer_name = None
            defaulted.append("employer_name cleared (looked like a status word)")
    annual_income_bracket = validate_income_bracket(annual_income_bracket)
    total_net_worth_bracket = validate_net_worth_bracket(total_net_worth_bracket)
    liquid_net_worth_bracket = validate_liquid_net_worth_bracket(liquid_net_worth_bracket)

    is_control_person = parse_yes_no(is_control_person, "control person")
    is_affiliated_exchange_or_finra = parse_yes_no(
        is_affiliated_exchange_or_finra, "affiliated with FINRA / exchange"
    )
    is_politically_exposed = parse_yes_no(is_politically_exposed, "politically exposed")
    immediate_family_exposed = parse_yes_no(immediate_family_exposed, "family politically exposed")

    income_min, income_max = _bracket_bounds(annual_income_bracket, INCOME_BRACKETS)
    nw_min, nw_max = _bracket_bounds(total_net_worth_bracket, NET_WORTH_BRACKETS)
    lnw_min, lnw_max = _bracket_bounds(liquid_net_worth_bracket, LIQUID_NET_WORTH_BRACKETS)

    signed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ip = client_ip or _AGREEMENT_IP_FALLBACK

    identity_kwargs = dict(
        given_name=first_name,
        family_name=last_name,
        date_of_birth=date_of_birth,
        tax_id=tax_id_value,
        tax_id_type=getattr(TaxIdType, tax_id_type_str),
        country_of_citizenship=country_of_citizenship,
        country_of_birth=country_of_birth_iso,
        country_of_tax_residence=country_of_tax_residence,
        funding_source=_funding_sources(funding_source),
        annual_income_min=str(income_min),
        annual_income_max=str(income_max),
        total_net_worth_min=str(nw_min),
        total_net_worth_max=str(nw_max),
        liquid_net_worth_min=str(lnw_min),
        liquid_net_worth_max=str(lnw_max),
    )

    request = CreateAccountRequest(
        contact=Contact(
            email_address=email,
            phone_number=phone,
            street_address=[street_address],
            city=city,
            state=state,
            postal_code=postal_code,
            country=country_of_residence,
        ),
        identity=Identity(**identity_kwargs),
        disclosures=Disclosures(
            is_control_person=is_control_person,
            is_affiliated_exchange_or_finra=is_affiliated_exchange_or_finra,
            is_politically_exposed=is_politically_exposed,
            immediate_family_exposed=immediate_family_exposed,
            employment_status=EmploymentStatus[employment_status.upper()],
            employer_name=employer_name or None,
            employer_address=None,
            employment_position=employer_position or None,
        ),
        agreements=[
            Agreement(
                agreement=AgreementType.MARGIN,
                signed_at=signed_at,
                ip_address=ip,
            ),
            Agreement(
                agreement=AgreementType.ACCOUNT,
                signed_at=signed_at,
                ip_address=ip,
            ),
            Agreement(
                agreement=AgreementType.CUSTOMER,
                signed_at=signed_at,
                ip_address=ip,
            ),
        ],
    )
    account = broker.create_account(request)

    audit_log.info(json.dumps({
        "type": "account_opened",
        "timestamp": signed_at,
        "account_id": str(account.id),
        "country_of_residence": country_of_residence,
        "country_of_tax_residence": country_of_tax_residence,
        "tax_id_type": tax_id_type_str,
        "income_bracket": annual_income_bracket,
        "net_worth_bracket": total_net_worth_bracket,
        "agreements": ["MARGIN", "ACCOUNT", "CUSTOMER"],
    }))

    return {
        "account_id": str(account.id),
        "account_number": str(account.account_number),
        "status": str(account.status),
        "country_of_residence": country_of_residence,
        "defaulted_fields": defaulted,
    }


# Alpaca's documented sandbox-friendly demo bank — accepts INSTANT
# transfers without external verification. Used when the user opts
# into the one-tap demo bank.
_DEMO_BANK_ROUTING = "121000358"
_DEMO_BANK_ACCOUNT = "32131231abc"


def setup_bank_funding(
    broker: BrokerClient,
    *,
    account_id: str,
    account_holder_name: str,
    use_demo_bank: bool = False,
    bank_routing_number: str | None = None,
    bank_account_number: str | None = None,
    bank_account_type: str = "CHECKING",
) -> dict:
    """Link a bank to the account via ACH relationship. No transfer yet.

    When `use_demo_bank=True`, fills in Alpaca's documented sandbox
    test bank — perfect for demos. Otherwise the user must supply
    routing + account number.
    """
    _assert_sandbox(broker)
    holder = validate_name(account_holder_name, "account holder name")

    defaulted: list[str] = []
    if use_demo_bank:
        bank_routing_number = _DEMO_BANK_ROUTING
        bank_account_number = _DEMO_BANK_ACCOUNT
        defaulted.append("demo bank used (Alpaca sandbox test routing)")
    elif not bank_routing_number or not bank_account_number:
        raise ValidationError(
            "Need either use_demo_bank=true OR a real routing + account number."
        )

    routing = validate_routing_number(bank_routing_number)
    bank_acct = validate_bank_account_number(bank_account_number)
    btype = (bank_account_type or "CHECKING").strip().upper()
    if btype not in {"CHECKING", "SAVINGS"}:
        btype = "CHECKING"

    ach = broker.create_ach_relationship_for_account(
        account_id=account_id,
        ach_data=CreateACHRelationshipRequest(
            account_owner_name=holder,
            bank_account_type=BankAccountType[btype],
            bank_account_number=bank_acct,
            bank_routing_number=routing,
            nickname="Primary",
        ),
    )
    return {
        "ach_relationship_id": str(ach.id),
        "status": str(ach.status),
        "bank_account_type": btype,
        "defaulted_fields": defaulted,
    }


def transfer_funds(
    broker: BrokerClient,
    *,
    account_id: str,
    ach_relationship_id: str,
    amount_eur: float,
) -> dict:
    """Initiate an INSTANT incoming ACH transfer in sandbox."""
    _assert_sandbox(broker)
    amount_eur = validate_amount(amount_eur)
    transfer = broker.create_transfer_for_account(
        account_id=account_id,
        transfer_data=CreateACHTransferRequest(
            amount=str(amount_eur),
            direction=TransferDirection.INCOMING,
            timing=TransferTiming.IMMEDIATE,
            relationship_id=ach_relationship_id,
        ),
    )
    return {
        "transfer_id": str(transfer.id),
        "status": str(transfer.status),
        "amount_eur": amount_eur,
    }


def invest_portfolio(
    broker: BrokerClient,
    *,
    account_id: str,
    amount_eur: float,
    archetype: str,
) -> dict:
    """Place 3 notional market orders following the chosen archetype."""
    amount_eur = validate_amount(amount_eur)
    archetype = validate_archetype(archetype)
    allocation = PORTFOLIO_ARCHETYPES[archetype]

    orders = []
    for symbol, weight, label in allocation:
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

    audit_log.info(json.dumps({
        "type": "orders_placed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "archetype": archetype,
        "total_eur": amount_eur,
        "orders": [{"symbol": o["symbol"], "amount_eur": o["amount_eur"]} for o in orders],
    }))

    return {
        "orders": orders,
        "total_invested_eur": amount_eur,
        "archetype": archetype,
    }


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
    if name == "assess_suitability":
        return assess_suitability(**args)
    if name == "create_brokerage_account":
        return create_brokerage_account(broker, **args)
    if name == "setup_bank_funding":
        return setup_bank_funding(broker, **args)
    if name == "transfer_funds":
        return transfer_funds(broker, **args)
    if name == "invest_portfolio":
        return invest_portfolio(broker, **args)
    if name == "get_portfolio":
        return get_portfolio(broker, **args)
    raise ValueError(f"unknown tool: {name}")
