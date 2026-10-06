"""Scope normalization and fail-closed delivery checks for generated ToCs."""
import re


def normalize_topic(value):
    text = str(value or "").lower()
    aliases = (
        (r"\bk8s\b", "kubernetes"),
        (r"\bamazon web services\b", "aws"),
        (r"\bmicrosoft azure\b", "azure"),
        (r"\bgoogle cloud(?: platform)?\b", "gcp"),
        (r"\bcontinuous integration\s*(?:and|/|&)\s*continuous (?:delivery|deployment)\b", "ci cd"),
        (r"\bci\s*[/ -]\s*cd\b", "ci cd"),
        (r"\binfrastructure as code\b", "iac"),
    )
    for pattern, replacement in aliases:
        text = re.sub(pattern, replacement, text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def topic_is_covered(topic, curriculum):
    required = normalize_topic(topic)
    return bool(required) and f" {required} " in f" {normalize_topic(curriculum)} "


def toc_delivery_error(toc):
    quality = toc.get("quality") or {}
    status = quality.get("status")
    if status in {"requires_review", "requires_regeneration"}:
        return "TOC requires review before export or delivery; resolve its quality warnings first"
    evaluation = quality.get("content_evaluation") or {}
    if (evaluation.get("status") == "fail"
            or (evaluation.get("status") == "review" and evaluation.get("score", 0) < 85)):
        return "TOC content evidence requires trainer review before export or delivery"
    if not toc.get("days"):
        return "TOC has no day-wise curriculum"
    return ""
