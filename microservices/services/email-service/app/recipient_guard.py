"""Validate workflow recipients independently of inbound classification."""
import re
from email.utils import parseaddr


async def recipient_error(db, recipient, requirement_id, trainer_id, mail_type):
    kind = re.sub(r"[^a-z0-9]", "", str(mail_type or "").lower())
    trainer_mail = kind.startswith(("mail1", "mail2", "mail3", "mail4", "mail5")) or (
        kind.startswith("trainer") and "toclient" not in kind
    ) or kind == "commercialnegotiation"
    client_mail = kind.startswith("client") or "toclient" in kind
    if not (trainer_mail or client_mail) or not requirement_id:
        return ""
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}) or {}
    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}) or {}
    address = lambda value: parseaddr(str(value or ""))[1].strip().lower()
    actual = address(recipient)
    client = address(requirement.get("client_email") or shortlist.get("client_email"))
    trainers = shortlist.get("top_trainers") or []
    trainer = next((item for item in trainers if item.get("trainer_id") == trainer_id), {})
    expected = address(trainer.get("email") or trainer.get("trainer_email")) if trainer_mail else client
    if trainer_mail and client and actual == client:
        return "trainer_mail_recipient_is_client"
    if client_mail and any(actual == address(item.get("email") or item.get("trainer_email")) for item in trainers):
        return "client_mail_recipient_is_trainer"
    # Older requirement records can lack client_email even though the inbound
    # sender is the client. The sender/thread is the valid delivery target in
    # that case; still reject any address known to be a trainer.
    if client_mail and not client:
        return ""
    if not expected or actual != expected:
        return "workflow_recipient_unverified"
    return ""
