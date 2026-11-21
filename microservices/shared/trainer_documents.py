"""Match requested trainer evidence to readable documents and named holders."""
import re
import unicodedata


DOCUMENTS = {
    "Experience letter": r"(?:experience|employment|service)\s+(?:letter|certificate)",
    "Graduation certificate": r"(?:graduation|degree|university|educational qualification)\s+(?:certificate|proof)|proof of (?:degree|graduation)",
}


def document_request_text(requirement):
    fields = ("requested_details", "client_requirement_text", "requirement_text", "description")
    return "\n".join(str(record.get(field) or "") for record in
                     (requirement, requirement.get("extracted") or {}) for field in fields)


def requested_documents(requirement):
    source = document_request_text(requirement)
    return [label for label, pattern in DOCUMENTS.items() if re.search(pattern, source, re.I)]


def requires_issuer_check(requirement):
    text = document_request_text(requirement)
    evidence = r"(?:certificates?|degrees?|diplomas?|credentials?|experience letters?|documents?)"
    verification = r"(?:authentic(?:ity)?|genuine|fake|issuer[- ]verified|verify|verified|validate)"
    return bool(re.search(rf"\b{verification}\b[^.!?\n]{{0,80}}\b{evidence}\b|\b{evidence}\b[^.!?\n]{{0,80}}\b{verification}\b", text, re.I))


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
