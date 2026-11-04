"""End-to-end test harness: a fresh database and a real uvicorn server.

Set TEST_DATABASE_ADMIN_URL to a PostgreSQL URL with rights to create databases,
for example postgresql://postgres@127.0.0.1:5432/postgres
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres")
TEST_DB = "complanning_e2e"
PLATFORM_EMAIL = "owner@comp11labs.test"
PLATFORM_PASSWORD = "Initial#Pass2026"


def _db_url(name: str) -> str:
    base, _, _ = ADMIN_URL.rpartition("/")
    return f"{base}/{name}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    """Minimal browser-like client with its own cookie jar."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body=None, csrf: bool = True, raw: bool = False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if csrf:
            req.add_header("X-Requested-With", "complanning")
        try:
            with self.opener.open(req) as resp:
                content = resp.read()
                return resp.status, (content if raw else json.loads(content or b"{}")), resp.headers
        except urllib.error.HTTPError as e:
            content = e.read()
            return e.code, (content if raw else json.loads(content or b"{}")), e.headers

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body if body is not None else {}, **kw)

    def patch(self, path, body, **kw):
        return self.call("PATCH", path, body, **kw)

    def put(self, path, body, **kw):
        return self.call("PUT", path, body, **kw)

    def login(self, email: str, password: str):
        return self.post("/api/auth/login", {"email": email, "password": password})


@pytest.fixture(scope="session")
def db_url():
    import psycopg
    conn = psycopg.connect(ADMIN_URL, autocommit=True)
    conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    conn.close()
    return _db_url(TEST_DB)


class FakeAI:
    """Stands in for an OpenAI-compatible chat API (Qwen on Model Studio): scripted tool calls, recorded requests."""

    def __init__(self):
        import http.server
        import threading
        self.requests: list[dict] = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                out = json.dumps(fake.reply(body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @staticmethod
    def reply(body):
        msgs = body["messages"]
        last = msgs[-1]
        usage = {"prompt_tokens": 100, "completion_tokens": 20}
        if "tools" not in body:
            return {"choices": [{"message": {"role": "assistant", "content": "OK"}}], "usage": usage}
        if last["role"] == "tool":
            return {"choices": [{"message": {"role": "assistant", "content": "ANSWER " + last["content"][:400]}}], "usage": usage}
        text = last["content"].lower()
        call = None
        if "late" in text:
            call = ("explain_delivery", {"product_code": "FG-PCM-20-EG"})
        elif "how" in text:
            call = ("search_help", {"query": text})
        elif "setup" in text:
            call = ("check_setup", {})
        elif "plans" in text:
            call = ("list_plans", {})
        elif "bogus" in text:
            call = ("get_plan", {"plan_id": "00000000-0000-0000-0000-000000000000"})
        if not call:
            return {"choices": [{"message": {"role": "assistant", "content": "Hello"}}], "usage": usage}
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": call[0], "arguments": json.dumps(call[1])}}]}}], "usage": usage}


@pytest.fixture(scope="session")
def fake_ai():
    f = FakeAI()
    yield f
    f.httpd.shutdown()


@pytest.fixture(scope="session")
def server(db_url, fake_ai):
    port = _free_port()
    env = dict(os.environ, DATABASE_URL=db_url, COOKIE_SECURE="false",
               AI_API_KEY="test-key", AI_BASE_URL=fake_ai.url, AI_MODEL="qwen-plus", AI_DAILY_LIMIT="12",
               PLATFORM_ADMIN_EMAIL=PLATFORM_EMAIL, PLATFORM_ADMIN_PASSWORD=PLATFORM_PASSWORD,
               FRONTEND_DIST=str(BACKEND / "tests" / "no-frontend"), LOG_LEVEL="WARNING")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
                             "--host", "127.0.0.1"], cwd=BACKEND, env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("Server exited during start-up")
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("Server did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def client(server):
    return Client(server)


@pytest.fixture(scope="session")
def platform(server):
    """A signed-in platform administrator who has already changed the first password."""
    c = Client(server)
    status, body, _ = c.login(PLATFORM_EMAIL, PLATFORM_PASSWORD)
    assert status == 200, body
    status, body, _ = c.post("/api/auth/change-password",
                             {"current_password": PLATFORM_PASSWORD, "new_password": "Owner#Secure2026"})
    assert status == 200, body
    return c


def sign_in_first_time(server: str, email: str, temp: str, new_password: str) -> Client:
    c = Client(server)
    status, body, _ = c.login(email, temp)
    assert status == 200, body
    status, body, _ = c.post("/api/auth/change-password", {"current_password": temp, "new_password": new_password})
    assert status == 200, body
    return c
