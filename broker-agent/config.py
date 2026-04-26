"""Static configuration for the TripVest broker agent.

Edit constants here when tuning model choice, retry budget, or the
fixed starter portfolio. No business logic — pure values.
"""

MODEL = "gpt-4o"
MAX_TOOL_TURNS = 10

# Starter portfolio: stocks / bonds / gold (US ETFs, fractional-eligible)
# Tuple format: (symbol, weight, human_label)
PORTFOLIO_ALLOCATION = [
    ("VOO", 0.60, "global stocks (S&P 500)"),
    ("BND", 0.30, "bonds"),
    ("GLD", 0.10, "gold"),
]
