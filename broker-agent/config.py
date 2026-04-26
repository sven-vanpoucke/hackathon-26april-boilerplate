"""Static configuration for the TripVest broker agent.

Edit constants here when tuning model choice, retry budget, or the
portfolio archetypes. No business logic — pure values.
"""

MODEL = "claude-sonnet-4-6"
MAX_TOOL_TURNS = 12

# Three suitability-driven archetypes. Each is a list of
# (symbol, weight, human_label). Weights must sum to 1.0.
PORTFOLIO_ARCHETYPES = {
    "conservative": [
        ("VOO", 0.30, "global stocks (S&P 500)"),
        ("BND", 0.60, "bonds"),
        ("GLD", 0.10, "gold"),
    ],
    "balanced": [
        ("VOO", 0.50, "global stocks (S&P 500)"),
        ("BND", 0.40, "bonds"),
        ("GLD", 0.10, "gold"),
    ],
    "growth": [
        ("VOO", 0.70, "global stocks (S&P 500)"),
        ("BND", 0.20, "bonds"),
        ("GLD", 0.10, "gold"),
    ],
}

# Risk-score thresholds — sum of 4 suitability answers in [4..12].
# score <= 6  → conservative
# score 7..9  → balanced
# score >= 10 → growth
RISK_THRESHOLDS = {"conservative_max": 6, "balanced_max": 9}

# Income / net-worth bracket labels mapped to Alpaca min/max.
# Alpaca expects integers in USD; sandbox accepts EUR-as-USD.
INCOME_BRACKETS = {
    "0-25k":     (0, 25_000),
    "25k-50k":   (25_000, 50_000),
    "50k-100k":  (50_000, 100_000),
    "100k-250k": (100_000, 250_000),
    "250k+":     (250_000, 9_999_999),
}
NET_WORTH_BRACKETS = INCOME_BRACKETS
LIQUID_NET_WORTH_BRACKETS = INCOME_BRACKETS
