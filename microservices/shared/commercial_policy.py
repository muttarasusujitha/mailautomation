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


def package_basis(requirement):
    days = commercial_days(requirement)
    return bool(days and days >= 5)


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
    total = package_basis(requirement)
    trainer_amount = rate * days if total else rate
    return {"trainer_amount": trainer_amount,
            "client_amount": round(trainer_amount / (1 - margin / 100), 2),
            "trainer_daily_rate": rate, "days": days,
            "basis": "total engagement" if total else "per training day",
            "margin_percent": margin}
