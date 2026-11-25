"""Transparent, rule-based scoring. Every point has a reason in the output."""

TARGET_INDUSTRIES = {"saas", "ecommerce", "retail", "d2c", "marketing", "fintech"}
DECISION_MAKER_WORDS = ("founder", "ceo", "owner", "head", "director", "vp", "chief")
HOT, WARM = 80, 40
OWNERS = {"hot": "founder", "warm": "sdr", "cold": "nurture"}


def _employee_points(n):
    if n is None:
        return 0, None
    if 11 <= n <= 200:
        return 25, "sweet-spot team size"
    if 201 <= n <= 1000:
        return 15, "mid-size team"
    if 1 <= n <= 10:
        return 10, "very small team"
    return 0, "very large company"


def score_lead(lead: dict, warnings: list):
    """Return (score 0-100, tier, owner, reasons)."""
    score, reasons = 0, []

    def add(points, reason):
        nonlocal score
        score += points
        reasons.append(f"{points:+d} {reason}")

    if lead.get("industry") in TARGET_INDUSTRIES:
        add(30, "target industry")
    pts, why = _employee_points(lead.get("employees"))
    if pts:
        add(pts, why)
    signals = set(lead.get("signals") or [])
    if "hiring" in signals:
        add(15, "hiring signal")
    if "ecommerce" in signals:
        add(10, "ecommerce signal")
    if "pricing_page" in signals:
        add(5, "pricing page")
    if lead.get("email") and not {"free_email", "email_domain_mismatch"} & set(warnings):
        add(15, "business email")
    if "free_email" in warnings:
        add(-10, "free email provider")
    title = (lead.get("contact_title") or "").lower()
    if any(w in title for w in DECISION_MAKER_WORDS):
        add(15, "decision-maker title")

    score = max(0, min(100, score))
    tier = "hot" if score >= HOT else "warm" if score >= WARM else "cold"
    return score, tier, OWNERS[tier], reasons
