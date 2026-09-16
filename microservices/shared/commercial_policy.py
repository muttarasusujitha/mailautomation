"""Clahan-owned offers and margin calculations, independent of email wording."""
from shared.requirement_duration import positive_number, training_duration


def margin_percent(requirement):
    batch = str(requirement.get("batch_flow") or requirement.get("batch_type") or requirement.get("requirement_type") or "").lower()
    if "proposal" not in batch:
        return 30.0
    value = requirement.get("clahan_margin_percent", 30)
    if isinstance(value, bool):
        raise ValueError("Clahan margin must be 25 or 30 percent")
    value = float(value)
    if value not in (25, 30):
        raise ValueError("Clahan margin must be 25 or 30 percent")
    return value


def commercial_days(requirement):
    return (training_duration(requirement).get("duration_days")
            or positive_number(requirement.get("commercial_working_days")))


def package_basis(requirement, trainer_daily_rate):
    days = commercial_days(requirement)
    rate = positive_number(trainer_daily_rate)
    return bool(days and days >= 5 and rate and rate < 12000)


def proposal_offer(requirement, trainer=None):
    """An explicit Clahan rate overrides the documented expertise tier.

    Tier is selected by Clahan; years alone do not prove specialist expertise.
    """
    trainer = trainer or {}
    rate = positive_number(trainer.get("clahan_offer_per_day")) or positive_number(requirement.get("clahan_offer_per_day"))
    tier = str(trainer.get("clahan_skill_tier") or requirement.get("clahan_skill_tier") or "standard").lower()
    if rate is None:
        if tier not in {"standard", "advanced", "specialist"}:
            raise ValueError("Clahan skill tier must be standard, advanced, or specialist")
        rate = {"standard": 14000, "advanced": 15000, "specialist": 16000}[tier]
    if not 14000 <= rate <= 16000:
        raise ValueError("Proposal trainer daily offer must be between INR 14,000 and INR 16,000")
    margin = margin_percent(requirement)
    days = commercial_days(requirement)
    total = bool(days and days >= 5)
    trainer_amount = rate * days if total else rate
    return {"trainer_amount": trainer_amount,
            "client_amount": round(trainer_amount / (1 - margin / 100), 2),
            "trainer_daily_rate": rate, "days": days,
            "basis": "total engagement" if total else "per training day",
            "margin_percent": margin}


def trainer_offer(requirement, trainer=None):
    """Return both trainer daily rate and total where duration is known."""
    batch = str(requirement.get("batch_flow") or requirement.get("batch_type") or "").lower()
    days = commercial_days(requirement)
    if "proposal" in batch:
        rate = proposal_offer(requirement, trainer)["trainer_daily_rate"]
        total = rate * days if days else None
    else:
        share = 1 - margin_percent(requirement) / 100
        budget = positive_number(requirement.get("budget_total"))
        client_rate = (positive_number(requirement.get("client_budget_per_day"))
                       or positive_number(requirement.get("budget_per_day")))
        total = budget * share if budget else None
        rate = total / days if total and days else client_rate * share if client_rate else None
        if total is None and rate and days:
            total = rate * days
        # Without duration, preserve a supplied total rather than invent a rate.
        if budget and not days:
            return {"amount": total, "basis": "total commercial",
                    "daily_rate": None, "total": total, "days": None}
    if not rate:
        return None
    return {"amount": rate, "basis": "per training day",
            "daily_rate": rate, "total": total, "days": days}


def trainer_commercial_text(requirement, trainer=None):
    """Show daily plus total above INR 13,000; otherwise show known total."""
    offer = trainer_offer(requirement, trainer)
    if not offer:
        return ""

    def money(value):
        return f"{value:,.2f}".rstrip("0").rstrip(".")

    if offer["total"] is not None and (offer["daily_rate"] is None or round(offer["daily_rate"], 2) <= 13000):
        amount = f"INR {money(offer['total'])} total commercial"
    elif offer["daily_rate"] is not None and offer["days"]:
        amount = (f"INR {money(offer['daily_rate'])} per training day x "
                  f"{offer['days']:g} training days = INR {money(offer['total'])} total commercial")
    else:
        amount = f"INR {money(offer['amount'])} {offer['basis']}"
    return f"{amount}, inclusive of applicable TDS"

