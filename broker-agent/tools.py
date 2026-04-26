"""OpenAI function-calling schema for Midora tools.

This file lists the LLM-facing tool definitions only — names,
descriptions, and parameter schemas. The actual implementations
live in `alpaca_ops.py`.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compute_trip_plan",
            "description": (
                "Compute lump-sum and monthly investment needed for a "
                "future trip, assuming ~7% annual return."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_cost_eur": {"type": "number"},
                    "years": {"type": "integer"},
                },
                "required": ["trip_cost_eur"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_suitability",
            "description": (
                "Run the MiFID-style suitability assessment from 4 user "
                "answers (each 1=low, 2=medium, 3=high). Returns a risk "
                "archetype (conservative/balanced/growth) and the "
                "recommended portfolio allocation. Call this BEFORE "
                "opening the account so the user sees the recommendation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "knowledge": {
                        "type": "integer",
                        "description": "1=never invested, 2=some, 3=experienced",
                    },
                    "loss_reaction": {
                        "type": "integer",
                        "description": "If portfolio drops 30%: 1=sell to stop loss, 2=hold, 3=buy more",
                    },
                    "loss_capacity": {
                        "type": "integer",
                        "description": "Impact of total loss: 1=serious, 2=somewhat, 3=not really",
                    },
                    "horizon_flexibility": {
                        "type": "integer",
                        "description": "Trip date: 1=fixed, 2=±1y, 3=very flexible",
                    },
                },
                "required": [
                    "knowledge",
                    "loss_reaction",
                    "loss_capacity",
                    "horizon_flexibility",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_brokerage_account",
            "description": (
                "Open a REAL Alpaca sandbox brokerage account using the "
                "customer's full KYC data. Only call after explicit "
                "confirmation AND after agreements_accepted is true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "email": {"type": "string"},
                    "date_of_birth": {
                        "type": "string",
                        "description": "YYYY-MM-DD (parse any user format)",
                    },
                    "phone": {
                        "type": "string",
                        "description": "Include country code, e.g. +34 600 123 456",
                    },
                    "street_address": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {
                        "type": ["string", "null"],
                        "description": "Optional region/state for non-US",
                    },
                    "postal_code": {"type": "string"},
                    "country_of_residence": {
                        "type": "string",
                        "description": "Country name or ISO-3 code (e.g. 'Spain' or 'ESP')",
                    },
                    "country_of_citizenship": {
                        "type": ["string", "null"],
                        "description": "OPTIONAL — defaults to country_of_residence. Only set if user is a citizen of a different country.",
                    },
                    "country_of_birth": {
                        "type": ["string", "null"],
                        "description": "OPTIONAL — defaults to country_of_citizenship.",
                    },
                    "country_of_tax_residence": {
                        "type": ["string", "null"],
                        "description": "OPTIONAL — defaults to country_of_residence. Only set if user pays tax in a different country.",
                    },
                    "tax_id": {
                        "type": "string",
                        "description": "SSN for US (9 digits), national tax ID otherwise (NIE/DNI/passport)",
                    },
                    "funding_source": {
                        "type": ["string", "array", "null"],
                        "items": {"type": "string"},
                        "description": "One or more of: savings, employment_income, family, investments, inheritance, business_income. OPTIONAL — student default: ['savings'].",
                    },
                    "employment_status": {
                        "type": "string",
                        "enum": ["student", "employed", "unemployed", "retired"],
                    },
                    "employer_name": {
                        "type": ["string", "null"],
                        "description": "Only required if employment_status='employed'. NEVER set for student/unemployed/retired.",
                    },
                    "employer_position": {
                        "type": ["string", "null"],
                        "description": "Only required if employment_status='employed'. NEVER set for student/unemployed/retired.",
                    },
                    "annual_income_bracket": {
                        "type": ["string", "null"],
                        "enum": ["0-25k", "25k-50k", "50k-100k", "100k-250k", "250k+", None],
                        "description": "OPTIONAL — student default: '0-25k'.",
                    },
                    "total_net_worth_bracket": {
                        "type": ["string", "null"],
                        "enum": ["0-25k", "25k-50k", "50k-100k", "100k-250k", "250k+", None],
                        "description": "OPTIONAL — student default: '0-25k'.",
                    },
                    "liquid_net_worth_bracket": {
                        "type": ["string", "null"],
                        "enum": ["0-25k", "25k-50k", "50k-100k", "100k-250k", "250k+", None],
                        "description": "OPTIONAL — student default: '0-25k'.",
                    },
                    "is_control_person": {
                        "type": ["boolean", "null"],
                        "description": "Senior officer/director or 10%+ owner of a public company? OPTIONAL — defaults to false.",
                    },
                    "is_affiliated_exchange_or_finra": {
                        "type": ["boolean", "null"],
                        "description": "You or family at a stock exchange or FINRA member? OPTIONAL — defaults to false.",
                    },
                    "is_politically_exposed": {
                        "type": ["boolean", "null"],
                        "description": "Are you a politically exposed person (PEP)? OPTIONAL — defaults to false.",
                    },
                    "immediate_family_exposed": {
                        "type": ["boolean", "null"],
                        "description": "Is an immediate family member a PEP? OPTIONAL — defaults to false.",
                    },
                    "agreements_accepted": {
                        "type": "boolean",
                        "description": "User has explicitly acknowledged Customer / Account / Margin agreements",
                    },
                },
                "required": [
                    "first_name", "last_name", "email", "date_of_birth", "phone",
                    "street_address", "city", "postal_code",
                    "country_of_residence", "tax_id",
                    "employment_status",
                    "agreements_accepted",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_bank_funding",
            "description": (
                "Link a bank to the account via ACH. Returns an "
                "ach_relationship_id. No money moves yet. "
                "For demos pass use_demo_bank=true and skip routing/account."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "account_holder_name": {
                        "type": "string",
                        "description": "Defaults to the user's full name from Stage 3 — don't re-ask the user.",
                    },
                    "use_demo_bank": {
                        "type": "boolean",
                        "description": "If true, fills in Alpaca's sandbox test routing+account. Skip routing/account when this is true.",
                    },
                    "bank_routing_number": {
                        "type": ["string", "null"],
                        "description": "9-digit ABA routing number. Omit if use_demo_bank=true.",
                    },
                    "bank_account_number": {
                        "type": ["string", "null"],
                        "description": "Omit if use_demo_bank=true.",
                    },
                    "bank_account_type": {
                        "type": "string",
                        "enum": ["CHECKING", "SAVINGS"],
                    },
                },
                "required": [
                    "account_id",
                    "account_holder_name",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_funds",
            "description": (
                "Initiate an INSTANT ACH deposit in EUR to a real Alpaca "
                "sandbox account. Requires an existing ach_relationship_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "ach_relationship_id": {"type": "string"},
                    "amount_eur": {"type": "number"},
                },
                "required": ["account_id", "ach_relationship_id", "amount_eur"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "invest_portfolio",
            "description": (
                "Place 3 real notional market orders following the user's "
                "suitability-derived archetype. Only call after confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "amount_eur": {"type": "number"},
                    "archetype": {
                        "type": "string",
                        "enum": ["conservative", "balanced", "growth"],
                    },
                },
                "required": ["account_id", "amount_eur", "archetype"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": "Return the account's current cash, positions and total value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                },
                "required": ["account_id"],
            },
        },
    },
]
