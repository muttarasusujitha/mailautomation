import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parent.parent
EXTENSION = Path.home() / ".vscode/extensions/sonarsource.sonarlint-vscode-5.3.0-win32-x64"
JAVA = EXTENSION / "jre/21.0.11-win32-x86_64.tar/bin/java.exe"
SERVER = EXTENSION / "server/sonarlint-ls.jar"
ANALYZERS = [
    EXTENSION / "analyzers/sonarpython.jar",
    EXTENSION / "analyzers/sonartext.jar",
]
FILES = [
    "trainer-platform-v8/backend/routes/api.py",
    "trainer-platform-v8/backend/agents/trainer_slot_agent.py",
    "trainer-platform-v8/backend/agents/client_intelligence_agent.py",
    "trainer-platform-v8/backend/config.py",
    "trainer-platform-v8/backend/.env.example",
]


class SonarClient:
    def __init__(self):
        args = [
            str(JAVA),
            "-Dsonarlint.telemetry.disabled=true",
            "-jar",
            str(SERVER),
            "-stdio",
            "-analyzers",
            *(str(path) for path in ANALYZERS),
        ]
        self.process = subprocess.Popen(
            args,
            cwd=WORKSPACE,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.next_id = 1
        self.responses = {}
        self.response_event = threading.Event()
        self.diagnostics = {}
        self.stderr_lines = queue.Queue()
        threading.Thread(target=self._read_messages, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _send(self, message):
        payload = json.dumps(message, separators=(",", ":")).encode()
        frame = f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload
        self.process.stdin.write(frame)
        self.process.stdin.flush()

    def request(self, method, params, timeout=30):
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if request_id in self.responses:
                response = self.responses.pop(request_id)
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response.get("result")
            self.response_event.wait(0.1)
            self.response_event.clear()
        raise TimeoutError(f"Timed out waiting for {method}")

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _read_messages(self):
        while self.process.poll() is None:
            headers = {}
            while True:
                line = self.process.stdout.readline()
                if not line:
                    return
                if line in {b"\r\n", b"\n"}:
                    break
                name, _, value = line.decode(errors="replace").partition(":")
                headers[name.lower()] = value.strip()
            length = int(headers.get("content-length", 0))
            if not length:
                continue
            message = json.loads(self.process.stdout.read(length))
            self._handle_message(message)

    def _handle_message(self, message):
        if "id" in message and "method" not in message:
            self.responses[message["id"]] = message
            self.response_event.set()
            return
        method = message.get("method")
        params = message.get("params") or {}
        if method == "textDocument/publishDiagnostics":
            self.diagnostics[params["uri"]] = params.get("diagnostics") or []
            return
        if "id" not in message:
            return
        result = None
        if method == "workspace/configuration":
            result = [None for _ in params.get("items", [])]
        elif method == "workspace/workspaceFolders":
            result = [{"uri": WORKSPACE.as_uri(), "name": WORKSPACE.name}]
        elif method == "sonarlint/shouldAnalyseFile":
            result = True
        elif method == "sonarlint/filterOutExcludedFiles":
            result = params.get("fileUris", [])
        elif method == "sonarlint/listFilesInFolder":
            result = []
        elif method == "sonarlint/scmCheck":
            result = False
        elif method == "sonarlint/canShowMissingRequirementNotification":
            result = 0
        self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def _read_stderr(self):
        for line in iter(self.process.stderr.readline, b""):
            self.stderr_lines.put(line.decode(errors="replace").rstrip())


def main():
    client = SonarClient()
    client.request(
        "initialize",
        {
            "processId": None,
            "clientInfo": {"name": "Codex Sonar client", "version": "1"},
            "locale": "en",
            "rootPath": str(WORKSPACE),
            "rootUri": WORKSPACE.as_uri(),
            "workspaceFolders": [{"uri": WORKSPACE.as_uri(), "name": WORKSPACE.name}],
            "capabilities": {
                "workspace": {"configuration": True, "workspaceFolders": True},
                "textDocument": {
                    "publishDiagnostics": {"relatedInformation": True, "versionSupport": True},
                    "synchronization": {"didSave": True, "dynamicRegistration": True},
                },
            },
            "initializationOptions": {
                "productKey": "vscode",
                "telemetryStorage": str(WORKSPACE / ".sonarlint-codex"),
                "productName": "SonarLint VSCode",
                "productVersion": "5.3.0",
                "workspaceName": WORKSPACE.name,
                "firstSecretDetected": False,
                "showVerboseLogs": False,
                "platform": "win32",
                "architecture": "x64",
                "additionalAttributes": {},
                "enableNotebooks": False,
                "connections": {"sonarqube": [], "sonarcloud": []},
                "rules": {},
                "focusOnNewCode": False,
                "automaticAnalysis": True,
            },
        },
        timeout=60,
    )
    client.notify("initialized", {})
    client.notify(
        "workspace/didChangeConfiguration",
        {"settings": {"sonarlint": {"automaticAnalysis": True, "rules": {}}}},
    )
    for relative_path in FILES:
        path = WORKSPACE / relative_path
        client.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": path.as_uri(),
                    "languageId": "python" if path.suffix == ".py" else "plaintext",
                    "version": 1,
                    "text": path.read_text(encoding="utf-8"),
                }
            },
        )

    deadline = time.monotonic() + 180
    last_signature = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        signature = tuple(sorted((uri, len(items)) for uri, items in client.diagnostics.items()))
        if signature != last_signature:
            last_signature = signature
            stable_since = time.monotonic()
        if len(client.diagnostics) >= len(FILES) and time.monotonic() - stable_since > 15:
            break
        time.sleep(1)

    output = {}
    for uri, diagnostics in client.diagnostics.items():
        output[uri] = [
            {
                "line": item.get("range", {}).get("start", {}).get("line", 0) + 1,
                "column": item.get("range", {}).get("start", {}).get("character", 0) + 1,
                "severity": item.get("severity"),
                "code": item.get("code"),
                "source": item.get("source"),
                "message": item.get("message"),
            }
            for item in diagnostics
        ]
    print(json.dumps(output, indent=2))
    try:
        client.request("shutdown", None, timeout=10)
        client.notify("exit", None)
    finally:
        client.process.kill()


if __name__ == "__main__":
    main()
