from urllib.parse import urlparse


def valid_meet_link(link: str, allowed_hosts: str) -> bool:
    parsed = urlparse(link)
    host = (parsed.hostname or "").lower()
    allowed = {item.strip().lower() for item in allowed_hosts.split(",") if item.strip()}
    return parsed.scheme == "https" and host in allowed

