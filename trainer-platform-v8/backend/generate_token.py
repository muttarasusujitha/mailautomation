import json
import logging
import os
import shutil
import time
import urllib.parse
import webbrowser
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BACKEND_DIR / "config"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.file",
]


def backup_invalid_token():
    if not TOKEN_FILE.exists():
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = CONFIG_DIR / f"token.invalid-{stamp}.bak"
    shutil.move(str(TOKEN_FILE), str(backup))
    logger.info("Invalid token.json moved to %s", backup)


def load_existing_token():
    if not TOKEN_FILE.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if hasattr(creds, "has_scopes") and not creds.has_scopes(SCOPES):
            logger.info("Existing token is missing required Google OAuth scopes.")
            backup_invalid_token()
            return None
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        return creds if creds.valid else None
    except Exception:
        backup_invalid_token()
        return None


def save_token(creds):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    logger.info("token.json saved to %s", TOKEN_FILE)


def credentials_kind():
    if not CREDENTIALS_FILE.exists():
        raise SystemExit(f"Missing OAuth credentials: {CREDENTIALS_FILE}")
    data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    if "installed" in data:
        return "installed", data["installed"]
    if "web" in data:
        return "web", data["web"]
    raise SystemExit("credentials.json must contain a 'web' or 'installed' OAuth client.")


def generate_with_installed_client():
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    save_token(creds)


def generate_with_web_client(client):
    redirect_uri = (client.get("redirect_uris") or ["http://localhost:5173/auth/callback"])[0]
    if redirect_uri.startswith("http://localhost") or redirect_uri.startswith("http://127.0.0.1"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # NOSONAR: local OAuth callback only
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
    )

    logger.info("\nOpen this Google authorization URL:")
    logger.info(auth_url)
    logger.info("\nAfter Google redirects you back, copy the full callback URL from the browser address bar.")
    webbrowser.open(auth_url)
    callback_url = input("\nPaste callback URL here: ").strip()
    parsed = urllib.parse.urlparse(callback_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = (params.get("code") or [""])[0]
    if not code:
        raise SystemExit("No authorization code found in the pasted callback URL.")

    flow.fetch_token(code=code)
    save_token(flow.credentials)


def main():
    creds = load_existing_token()
    if creds and creds.valid:
        logger.info("Existing token is valid: %s", TOKEN_FILE)
        return

    kind, client = credentials_kind()
    if kind == "installed":
        generate_with_installed_client()
    else:
        generate_with_web_client(client)

    logger.info("Gmail OAuth flow complete.")


if __name__ == "__main__":
    main()
