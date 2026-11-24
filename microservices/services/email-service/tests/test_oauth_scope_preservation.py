"""Exercise credential loading without network calls or real credentials."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from google.oauth2.credentials import Credentials


class OAuthScopePreservationTests(unittest.TestCase):
    def test_shared_token_loaders_preserve_calendar_scope(self):
        app = Path(__file__).resolve().parents[1] / "app"
        scopes = [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/calendar",
        ]
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token.json"
            token.write_text(json.dumps({
                "client_id": "test", "client_secret": "test",
                "refresh_token": "test", "scopes": scopes,
            }), encoding="utf-8")
            for relative in ("gmail_client.py", "calendar_client.py", "routes/gmail.py"):
                with self.subTest(loader=relative):
                    tree = ast.parse((app / relative).read_text(encoding="utf-8"))
                    calls = [node for node in ast.walk(tree)
                             if isinstance(node, ast.Call)
                             and isinstance(node.func, ast.Attribute)
                             and node.func.attr == "from_authorized_user_file"]
                    self.assertEqual(len(calls), 1)
                    namespace = {"Credentials": Credentials, "token_file": str(token), "tp": str(token),
                                 "GMAIL_SCOPES": scopes[:2], "CALENDAR_SCOPES": scopes}
                    creds = eval(compile(ast.Expression(calls[0]), relative, "eval"), namespace)
                    self.assertEqual(json.loads(creds.to_json())["scopes"], scopes)


if __name__ == "__main__":
    unittest.main()
