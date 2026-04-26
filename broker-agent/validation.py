"""User-input validators for TripVest tool calls.

`ValidationError` carries a user-facing message in `str(exc)` — main.py
catches it and feeds the message back as the tool result so the LLM
re-prompts the user instead of crashing the session.
"""

import re
from datetime import date

from dateutil import parser as dateparser

from config import (
    INCOME_BRACKETS,
    NET_WORTH_BRACKETS,
    LIQUID_NET_WORTH_BRACKETS,
)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_POSTAL_RE = re.compile(r"^[A-Za-z0-9\s\-]{2,12}$")
_ISO3_RE = re.compile(r"^[A-Z]{3}$")

# Values that LLMs love to invent but mean "no data". Never send to Alpaca.
_NA_TOKENS = {
    "", "n/a", "na", "n.a.", "n a", "none", "null", "nil",
    "nothing", "not applicable", "not_applicable", "-", "--",
    "x", "?", ".", "tbd", "to be decided",
}

# Country aliases users typically type → ISO 3166-1 alpha-3.
_COUNTRY_ALIASES = {
    "spain": "ESP", "españa": "ESP", "es": "ESP", "esp": "ESP",
    "usa": "USA", "us": "USA", "united states": "USA", "america": "USA",
    "uk": "GBR", "united kingdom": "GBR", "britain": "GBR", "england": "GBR",
    "belgium": "BEL", "belgië": "BEL", "belgique": "BEL", "be": "BEL",
    "germany": "DEU", "deutschland": "DEU", "de": "DEU",
    "france": "FRA", "fr": "FRA",
    "netherlands": "NLD", "nederland": "NLD", "holland": "NLD", "nl": "NLD",
    "italy": "ITA", "italia": "ITA", "it": "ITA",
    "portugal": "PRT", "pt": "PRT",
    "ireland": "IRL", "ie": "IRL",
    "switzerland": "CHE", "ch": "CHE",
    "austria": "AUT", "at": "AUT",
    "canada": "CAN", "ca": "CAN",
    "mexico": "MEX", "méxico": "MEX", "mx": "MEX",
}

_FUNDING_SOURCES = {
    "employment_income", "investments", "inheritance",
    "business_income", "savings", "family",
}

_EMPLOYMENT_STATUSES = {"employed", "unemployed", "retired", "student"}


class ValidationError(Exception):
    """User-facing message in str(exc). LLM should re-prompt the user."""


def clean_optional_string(value) -> str | None:
    """Return cleaned string, or None for empty/whitespace/N-A-style placeholders.

    LLMs love to fill optional fields with 'N/A', 'none', '-', etc. when the
    user didn't provide a value. Sending those downstream causes Alpaca to
    reject the request. This function is the single chokepoint that turns
    every placeholder pattern into a real None.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if cleaned.lower() in _NA_TOKENS:
        return None
    return cleaned or None


def reject_placeholder(value: str, field: str) -> str:
    """For required string fields — refuse 'N/A' style placeholders loudly."""
    cleaned = (value or "").strip() if isinstance(value, str) else ""
    if cleaned.lower() in _NA_TOKENS:
        raise ValidationError(
            f"I need a real {field} from the user — '{value}' isn't a valid value."
        )
    return cleaned


def validate_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValidationError("That email doesn't look right — could you double-check?")
    normalized = email.strip().lower()
    if not _EMAIL_RE.match(normalized):
        raise ValidationError("That email doesn't look right — could you double-check?")
    return normalized


def parse_and_validate_dob(s: str) -> str:
    if not isinstance(s, str) or not s.strip():
        raise ValidationError("I couldn't read that date — try a format like 15 March 2002.")
    try:
        dt = dateparser.parse(s.strip(), dayfirst=True)
    except (ValueError, OverflowError, TypeError):
        raise ValidationError("I couldn't read that date — try a format like 15 March 2002.")
    if dt is None:
        raise ValidationError("I couldn't read that date — try a format like 15 March 2002.")
    dob = dt.date()
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < 18:
        raise ValidationError("You need to be at least 18 to open an account.")
    if age > 100:
        raise ValidationError("That birthdate doesn't look right — could you double-check?")
    return dob.strftime("%Y-%m-%d")


def validate_name(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"Your {field} doesn't look right — could you send it again?")
    stripped = value.strip()
    if not stripped or len(stripped) > 50:
        raise ValidationError(f"Your {field} doesn't look right — could you send it again?")
    return stripped


def validate_amount(
    amount_eur: float,
    *,
    min_eur: float = 1.0,
    max_eur: float = 100_000.0,
) -> float:
    try:
        value = float(amount_eur)
    except (TypeError, ValueError):
        raise ValidationError(f"Amount needs to be between €{min_eur:g} and €{max_eur:g}.")
    if value < min_eur or value > max_eur:
        raise ValidationError(f"Amount needs to be between €{min_eur:g} and €{max_eur:g}.")
    return value


def validate_phone(phone: str) -> str:
    """Validate an international phone number — must include country code."""
    if not isinstance(phone, str):
        raise ValidationError(
            "Phone number doesn't look right — include the country code, e.g. +34 600 123 456."
        )
    raw = phone.strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 9 or len(digits) > 15:
        raise ValidationError(
            f"The phone you sent ('{phone}') has only {len(digits)} digits — "
            "I need a full international number with country code, e.g. "
            "+32 470 12 34 56. Re-check the user's MOST RECENT message for the "
            "correct phone — don't reuse an older value from earlier in the chat."
        )
    return "+" + digits


def validate_country(value: str) -> str:
    """Return ISO 3166-1 alpha-3 country code."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("I couldn't read that country — try a name like 'Spain' or code 'ESP'.")
    key = value.strip().lower()
    if key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[key]
    upper = value.strip().upper()
    if _ISO3_RE.match(upper):
        return upper
    raise ValidationError(
        f"I don't recognize '{value}' as a country — try the full name like 'Spain'."
    )


def validate_street(value: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < 3 or len(value) > 100:
        raise ValidationError("That street address doesn't look right — could you send it again?")
    return value.strip()


def validate_city(value: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < 2 or len(value) > 50:
        raise ValidationError("That city doesn't look right — could you send it again?")
    return value.strip()


def validate_postal_code(value: str) -> str:
    if not isinstance(value, str) or not _POSTAL_RE.match((value or "").strip()):
        raise ValidationError(
            f"The postal code you sent ('{value}') doesn't look right. Re-check the "
            "user's MOST RECENT message for the correct postal code."
        )
    return value.strip().upper()


def validate_state(value: str | None) -> str | None:
    """State/region is optional — N/A and friends become None silently."""
    return clean_optional_string(value)


# Country-specific Alpaca TaxIdType where one exists; otherwise NATIONAL_ID
# is the right call for EU residents (covers NIE/DNI/CF/etc).
_TAX_ID_TYPE_BY_COUNTRY = {
    "USA": "USA_SSN",
    "GBR": "GBR_NINO",
    "DEU": "DEU_TAX_ID",
    "FRA": "FRA_SPI",
    "ITA": "ITA_TAX_ID",
    "NLD": "NLD_TIN",
    "HUN": "HUN_TIN",
    "SWE": "SWE_TAX_ID",
    "JPN": "JPN_TAX_ID",
    "ISR": "ISR_TAX_ID",
    "IND": "IND_PAN",
    "MEX": "MEX_RFC",
    "BRA": "BRA_CPF",
    "ARG": "ARG_AR_CUIT",
    "CHL": "CHL_RUT",
    "COL": "COL_NIT",
    "PER": "PER_RUC",
    "URY": "URY_RUT",
    "VEN": "VEN_RIF",
    "BOL": "BOL_NIT",
    "CRI": "CRI_NITE",
    "DOM": "DOM_RNC",
    "ECU": "ECU_RUC",
    "GTM": "GTM_NIT",
    "HND": "HND_RTN",
    "NIC": "NIC_RUC",
    "PAN": "PAN_RUC",
    "PRY": "PRY_RUC",
    "SLV": "SLV_NIT",
    "AUS": "AUS_TFN",
    "IDN": "IDN_KTP",
    "SGP": "SGP_NRIC",
}


def validate_tax_id(tax_id: str, country_iso3: str) -> tuple[str, str]:
    """Return (normalized_tax_id, alpaca_tax_id_type_string)."""
    if not isinstance(tax_id, str) or not tax_id.strip():
        raise ValidationError("I need your tax ID number to open the account.")
    cleaned = tax_id.strip().upper().replace(" ", "")
    if cleaned.lower() in _NA_TOKENS:
        raise ValidationError(
            "That doesn't look like a real tax ID — I need your actual number "
            "(NIE/DNI/national ID/passport)."
        )
    if country_iso3 == "USA":
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) != 9:
            raise ValidationError(
                f"The tax ID you sent ('{tax_id}') has {len(digits)} digits — "
                "US SSN must be exactly 9 digits (e.g. 123-45-6789). "
                "Re-check the user's MOST RECENT message."
            )
        return f"{digits[0:3]}-{digits[3:5]}-{digits[5:9]}", "USA_SSN"
    if len(cleaned) < 7 or len(cleaned) > 25:
        raise ValidationError(
            f"The tax ID you sent ('{tax_id}') is {len(cleaned)} chars — too short "
            "to be a real national ID. Re-check the user's MOST RECENT message; "
            "don't reuse an older value from earlier in the chat."
        )
    tax_type = _TAX_ID_TYPE_BY_COUNTRY.get(country_iso3, "NATIONAL_ID")
    return cleaned, tax_type


def validate_funding_source(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Pick one funding source: savings, employment_income, family, investments, inheritance, business_income.")
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "salary": "employment_income", "job": "employment_income", "work": "employment_income",
        "employment": "employment_income", "wages": "employment_income",
        "gift": "family", "parents": "family", "family_support": "family",
        "savings_account": "savings", "saved": "savings",
    }
    key = aliases.get(key, key)
    if key not in _FUNDING_SOURCES:
        raise ValidationError(
            "Pick one: savings, employment_income, family, investments, inheritance, business_income."
        )
    return key


def validate_employment_status(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Pick one: student, employed, unemployed, retired.")
    key = value.strip().lower()
    if key in {"working", "job"}:
        key = "employed"
    if key in {"studying", "uni", "university"}:
        key = "student"
    if key not in _EMPLOYMENT_STATUSES:
        raise ValidationError("Pick one: student, employed, unemployed, retired.")
    return key


def validate_bracket(value: str, brackets: dict, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"Pick one {label} bracket: {', '.join(brackets)}.")
    key = value.strip().lower().replace(" ", "")
    aliases = {
        "0-25000": "0-25k", "<25k": "0-25k",
        "25000-50000": "25k-50k",
        "50000-100000": "50k-100k",
        "100000-250000": "100k-250k",
        ">250k": "250k+", "250000+": "250k+",
    }
    key = aliases.get(key, key)
    if key not in brackets:
        raise ValidationError(f"Pick one {label} bracket: {', '.join(brackets)}.")
    return key


def validate_income_bracket(value: str) -> str:
    return validate_bracket(value, INCOME_BRACKETS, "annual income")


def validate_net_worth_bracket(value: str) -> str:
    return validate_bracket(value, NET_WORTH_BRACKETS, "total net worth")


def validate_liquid_net_worth_bracket(value: str) -> str:
    return validate_bracket(value, LIQUID_NET_WORTH_BRACKETS, "liquid net worth")


def parse_yes_no(value, field: str) -> bool:
    """Accept bool or string ('yes'/'no'/'y'/'n'/'true'/'false')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"yes", "y", "true", "1"}:
            return True
        if v in {"no", "n", "false", "0"}:
            return False
    raise ValidationError(f"For '{field}', please answer yes or no.")


def validate_archetype(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Risk profile must be conservative, balanced, or growth.")
    key = value.strip().lower()
    if key not in {"conservative", "balanced", "growth"}:
        raise ValidationError("Risk profile must be conservative, balanced, or growth.")
    return key


def validate_routing_number(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Routing number must be 9 digits.")
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9:
        raise ValidationError("Routing number must be 9 digits (e.g. 121000358).")
    return digits


def validate_bank_account_number(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("That bank account number doesn't look right.")
    cleaned = value.strip()
    if len(cleaned) < 4 or len(cleaned) > 32:
        raise ValidationError("That bank account number doesn't look right.")
    return cleaned


def validate_score_1to3(value, field: str) -> int:
    """For suitability — 1=low, 2=medium, 3=high."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"For '{field}', send a number 1, 2, or 3.")
    if n not in (1, 2, 3):
        raise ValidationError(f"For '{field}', send a number 1, 2, or 3.")
    return n
