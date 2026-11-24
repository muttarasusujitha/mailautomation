"""Clahan-owned offers and margin calculations, independent of email wording."""
import re

from shared.requirement_duration import positive_number, training_duration


def commercial_breakdown(requirement):
    """Keep the client-facing training and lab commercials distinct.

    A client can quote one budget for the complete engagement.  Only when the
    requirement explicitly says that this budget covers labs do we subtract the
    client lab workbook value before calculating the trainer's 70% share.
    This avoids silently reducing a training commercial that was quoted
    separately from the lab.
    """
    requirement = requirement or {}
    lab_amount = next((positive_number(requirement.get(key)) for key in (
        "lab_client_price", "lab_quote_amount",
    ) if positive_number(requirement.get(key))), 0.0) or 0.0
    training_amount = next((positive_number(requirement.get(key)) for key in (
        "training_commercial_amount", "training_commercial", "client_training_amount",
    ) if positive_number(requirement.get(key))), None)
    total_budget = next((positive_number(requirement.get(key)) for key in (
        "client_commercial_total", "total_commercial", "commercial_amount", "client_budget", "budget_total",
    ) if positive_number(requirement.get(key))), None)
    source_text = " ".join(str(requirement.get(key) or "") for key in (
        "requirement_source_text", "client_requirement_text", "commercial_notes",
    ))
    covers_lab = bool(requirement.get("client_budget_includes_lab")) or str(
        requirement.get("commercial_scope") or ""
    ).lower() in {"combined", "training_and_lab", "training_lab"}
    # Accept an unambiguous client statement as well as a structured field.
    if not covers_lab:
        covers_lab = bool(re.search(
            r"(?:budget|commercials?|amount|quote).{0,80}(?:include|including|covers?|covering).{0,50}(?:lab|labs|labworkbook|lab workbook)"
            r"|(?:lab|labs|labworkbook|lab workbook).{0,50}(?:include|including|covered).{0,80}(?:budget|commercials?|amount|quote)",
            source_text, re.I,
        ))
    needs_lab_price = bool(covers_lab and total_budget and not lab_amount)
    if covers_lab and total_budget and lab_amount:
        training_amount = total_budget - lab_amount
    elif training_amount is None:
        training_amount = total_budget or 0.0
    invalid = bool(covers_lab and total_budget and lab_amount and training_amount < 0)
    training_amount = max(float(training_amount or 0), 0.0)
    total_client_amount = float(total_budget if covers_lab and total_budget else training_amount + lab_amount)
    return {
        "training_client_amount": round(training_amount, 2),
        "lab_client_amount": round(float(lab_amount), 2),
        "total_client_amount": round(total_client_amount, 2),
        "trainer_amount": round(training_amount * 0.70, 2),
        "clahan_training_margin_amount": round(training_amount * 0.30, 2),
        "budget_includes_lab": covers_lab,
        "needs_lab_price": needs_lab_price,
        "invalid": invalid,
    }


def margin_percent(requirement):
    """Clahan uses a fixed 30% client uplift for confirmed and proposal batches."""
    del requirement
    return 30.0


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
            "client_amount": round((trainer_amount * (1 + margin / 100)) / 1000) * 1000,
            "trainer_daily_rate": rate, "days": days,
            "basis": "total engagement" if total else "per training day",
            "margin_percent": margin}


def shortlist_proposal_offer(requirement, trainer=None):
    """Clahan-selected trainer offer for proposals entered through Shortlist.

    Proposal markup pricing is separate from confirmed-batch 70/30 shares.
    Clahan's explicit rate/tier wins; otherwise verified experience selects
    the base (0-4 years), advanced (5-9 years), or specialist (10+ years)
    rate. The client rate is exactly 30% above the trainer amount.
    """
    trainer = trainer or {}
    rate = positive_number(trainer.get("clahan_offer_per_day")) or positive_number(requirement.get("clahan_offer_per_day"))
    tier = str(trainer.get("clahan_skill_tier") or requirement.get("clahan_skill_tier") or "standard").lower()
    if rate is None:
        if not (trainer.get("clahan_skill_tier") or requirement.get("clahan_skill_tier")):
            from shared.trainer_experience import profile_experience_years
            experience = profile_experience_years(trainer) if trainer else None
            if experience is None:
                experience = profile_experience_years(requirement)
            tier = "specialist" if experience is not None and experience >= 10 else (
                "advanced" if experience is not None and experience >= 5 else "standard"
            )
        if tier not in {"standard", "advanced", "specialist"}:
            raise ValueError("Clahan skill tier must be standard, advanced, or specialist")
        rate = {"standard": 12000, "advanced": 14000, "specialist": 16000}[tier]
    if not 12000 <= rate <= 16000:
        raise ValueError("Shortlist proposal trainer offer must be between INR 12,000 and INR 16,000 per day")
    days = commercial_days(requirement)
    trainer_amount = rate * days if days else rate
    total = bool(days)
    return {"trainer_amount": trainer_amount,
            "client_amount": round(trainer_amount * 1.30, 2),
            "trainer_daily_rate": rate,
            "client_daily_rate": rate * 1.30,
            "days": days,
            "basis": "total engagement" if total else "per training day",
            "margin_percent": 30}


def trainer_offer(requirement, trainer=None):
    """Return both trainer daily rate and total where duration is known."""
    batch = str(requirement.get("batch_flow") or requirement.get("batch_type") or "").lower()
    days = commercial_days(requirement)
    if "proposal" in batch:
        rate = proposal_offer(requirement, trainer)["trainer_daily_rate"]
        total = rate * days if days else None
    else:
        share = 1 - margin_percent(requirement) / 100
        # Prefer the confirmed client commercial total when deriving the
        # trainer allocation. Some requirement parsers store that value under
        # a commercial-specific field instead of budget_total.
        budget = commercial_breakdown(requirement)["training_client_amount"] or None
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


def client_stated_commercial_text(requirement):
    """The commercial the client stated, with no trainer share applied."""
    per_day = (positive_number(requirement.get("client_budget_per_day"))
               or positive_number(requirement.get("budget_per_day")))
    total = next((positive_number(requirement.get(key)) for key in (
        "budget_total", "training_commercial_amount", "client_commercial_total",
        "total_commercial", "commercial_amount",
    ) if positive_number(requirement.get(key))), None)
    stated_range = str(requirement.get("budget_range") or "").strip()

    def money(value):
        return f"{int(round(value)):,}"

    # A figure below INR 10,000 is one course total, not a daily rate.
    if per_day:
        if per_day < 10000:
            return f"INR {money(total or per_day)} total-course commercial"
        return f"INR {money(per_day)} per day/session"
    if total:
        return f"INR {money(total)} total-course commercial"
    return stated_range


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

