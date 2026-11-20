"""Match requested trainer evidence to readable documents and named holders."""
import re
import unicodedata


DOCUMENTS = {
    "Experience letter": r"(?:experience|employment|service)\s+(?:letter|certificate)",
    "Graduation certificate": r"(?:graduation|degree|university|educational qualification)\s+(?:certificate|proof)|proof of (?:degree|graduation)",
}


def requested_documents(requirement):
    fields = ("requested_details", "client_requirement_text", "requirement_text", "description")
    source = "\n".join(str(record.get(field) or "") for record in
                       (requirement, requirement.get("extracted") or {}) for field in fields)
    return [label for label, pattern in DOCUMENTS.items() if re.search(pattern, source, re.I)]


def _name(value):
    return " ".join(re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", value).casefold()))


def matching_document(attachment, label, trainer_name):
    """Require a document type and an explicit holder line. Ambiguity needs review."""
    analysis = attachment.get("analysis") or {}
    text = str(
        analysis.get("extracted_text")
        or attachment.get("extracted_text")
        or attachment.get("parsed_text")
        or attachment.get("text")
        or ""
    )
    if not re.search(DOCUMENTS[label], text, re.I):
        return False
    holder = re.search(r"(?im)^\s*(?:(?:employee|candidate|student|holder|recipient)(?:'s)?\s+name|name)\s*[:\-]\s*([^\r\n]+)", text)
    return bool(holder and len(_name(trainer_name).split()) >= 2
                and _name(holder[1]) == _name(trainer_name))
