import re
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")
DOMAIN_RE = re.compile(r"^([a-z0-9-]+\.)+[a-z]{2,}$")
FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "icloud.com",
}


class ValidationError(Exception):
    """A row that cannot continue. `code` is a stable reason for the errors sheet."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _s(value) -> str:
    """Coerce any input (None, int from a sheet, str) to a stripped string."""
    return "" if value is None else str(value).strip()


def normalize_domain(raw: str) -> str:
    """'https://www.Example.com/about' -> 'example.com'"""
    raw = _s(raw).lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "//" + raw
    host = urlparse(raw).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _parse_employees(raw, warnings):
    raw = _s(raw).replace(",", "")
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    warnings.append("employees_unparseable")
    return None


def validate_row(row: dict, require_email: bool = False):
    """Return (clean_lead, warnings) or raise ValidationError.

    Hard errors: no company, no/invalid domain, malformed email, and (only when
    require_email=True, e.g. a CRM that upserts by email) a missing email.
    Warnings (row continues, score reflects them): no email, free email
    provider, email domain differs from company domain, bad employee count.
    """
    warnings = []
    company = _s(row.get("company"))
    if not company:
        raise ValidationError("missing_company", "company is empty")

    raw_domain = _s(row.get("domain"))
    if not raw_domain:
        raise ValidationError("missing_domain", "domain is empty")
    domain = normalize_domain(raw_domain)
    if not DOMAIN_RE.match(domain):
        raise ValidationError("invalid_domain", f"'{raw_domain}' is not a valid domain")

    email = _s(row.get("email")).lower()
    if not email:
        if require_email:
            raise ValidationError("missing_email", "email is required for CRM upsert")
        warnings.append("no_email")
    elif not EMAIL_RE.match(email):
        raise ValidationError("invalid_email", f"'{email}' is not a valid email")
    else:
        email_domain = email.split("@", 1)[1]
        if email_domain in FREE_EMAIL_DOMAINS:
            warnings.append("free_email")
        elif email_domain != domain and not email_domain.endswith("." + domain):
            warnings.append("email_domain_mismatch")

    first, _, last = _s(row.get("contact_name")).partition(" ")
    lead = {
        "company": company,
        "domain": domain,
        "contact_name": _s(row.get("contact_name")),
        "first_name": first,
        "last_name": last.strip(),
        "contact_title": _s(row.get("contact_title")),
        "email": email,
        "industry": _s(row.get("industry")).lower(),
        "employees": _parse_employees(row.get("employees"), warnings),
    }
    return lead, warnings
