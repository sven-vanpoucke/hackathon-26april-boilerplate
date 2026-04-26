"""OpenAI function-calling schema for TripVest tools.

This file lists the LLM-facing tool definitions only — names,
descriptions, and parameter schemas. The actual implementations
live in `alpaca_ops.py`. A teammate working on prompt/tool design
can edit this file freely.
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
            "name": "create_brokerage_account",
            "description": (
                "Open a REAL Alpaca sandbox brokerage account for the "
                "student. Only call after explicit confirmation."
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
            "name": "fund_account",
            "description": (
                "Link a sandbox bank and initiate an INSTANT ACH deposit "
                "in EUR to a real Alpaca account. Only after confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "amount_eur": {"type": "number"},
                },
                "required": ["account_id", "amount_eur"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "invest_starter_portfolio",
            "description": (
                "Place 3 real notional market orders on the account: "
                "60% VOO / 30% BND / 10% GLD. Only after confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "amount_eur": {"type": "number"},
                },
                "required": ["account_id", "amount_eur"],
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
