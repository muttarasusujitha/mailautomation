"""Validate supplied trainer identity links without constructing missing URLs."""
import re
from urllib.parse import urlsplit


def linkedin_profile_url(value):
    """Extract a personal LinkedIn URL; company/search links are not profiles."""
    for candidate in re.findall(r"https?://[^\s<>\"')]+", str(value or ""), re.I):
        candidate = candidate.rstrip(".,;:")
        try:
            parsed = urlsplit(candidate)
            host = (parsed.hostname or "").lower()
            if host != "linkedin.com" and not re.fullmatch(r"(?:www|[a-z]{2,3})\.linkedin\.com", host):
                continue
            if parsed.username or parsed.password or parsed.port:
                continue
            if re.fullmatch(r"/(?:in|pub)/[^/?#]+(?:/[^?#]*)?", parsed.path):
                return candidate
        except ValueError:
            continue
    return ""
