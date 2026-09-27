import datetime
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

from eval_workbench import Client, WorkbenchError, span, trace

BACKEND = Path(__file__).resolve().parents[3] / "backend"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _call(base, method, path, body=None, key="test-admin"):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp}/sdk.db", "EVAL_WORKBENCH_ADMIN_KEY": "test-admin"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=BACKEND, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/health")
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("server did not start")
    _call(base, "POST", "/admin/projects", {"name": "SDK test"})
    key = _call(base, "POST", "/admin/projects/sdk-test/keys", {"name": "t"})["key"]
    yield base, key
    proc.kill()


@pytest.fixture()
def suite(server):
    base, key = server
    s = _call(base, "POST", "/suites", {"name": "Greeter", "slaMs": 5000}, key)
    for text, needle in [("Say hi to Ann", "Ann"), ("Say hi to Bob", "Bob"), ("Say hi to Cy", "Cy")]:
        _call(base, "POST", f"/suites/{s['id']}/cases", {"input": text, "checks": [{"type": "contains_all", "values": [needle]}]}, key)
    return s["id"]


def test_ten_line_script_runs_a_suite(server, suite):
    base, key = server
    from eval_workbench import Client

    client = Client(base_url=base, api_key=key)
    result = client.run_suite(suite, lambda text: "Hello " + text.split()[-1], version="v1", model="none")
    assert result.summary["Pass"] == 3 and result.pass_rate == 1
    assert _call(base, "GET", f"/runs/{result.run_id}", key=key)["finishedAt"]
    assert result.url.endswith(f"/#/results/{result.run_id}")


def test_traces_are_nested_and_uploaded(server, suite):
    base, key = server

    @trace(name="prompt.build")
    def build(text):
        return text.upper()

    @trace(name="llm.generate", kind="llm")
    def generate(prompt):
        with span("llm.http", kind="other", attempt=1) as s:
            time.sleep(0.02)
            s.set(tokens=7)
        return "Hello " + prompt.split()[-1].title()

    def app(text):
        with span("pipeline"):
            return generate(build(text))

    result = Client(base_url=base, api_key=key).run_suite(suite, app)
    detail = _call(base, "GET", f"/runs/{result.run_id}/results/{result.results[0]['caseId']}", key=key)
    spans = {s["name"]: s for s in detail["spans"]}
    assert [s["name"] for s in detail["spans"]][:2] == ["request", "pipeline"]
    assert (spans["request"]["depth"], spans["pipeline"]["depth"], spans["prompt.build"]["depth"]) == (0, 1, 2)
    assert spans["llm.generate"]["kind"] == "llm" and spans["llm.http"]["depth"] == 3
    assert spans["llm.http"]["attrs"] == {"attempt": 1, "tokens": 7} and spans["llm.http"]["dur"] >= 15
    assert spans["request"]["dur"] >= spans["pipeline"]["dur"]


def test_errors_in_fn_become_execution_errors(server, suite):
    base, key = server

    def flaky(text):
        if "Bob" in text:
            raise RuntimeError("model unavailable")
        return "Hello " + text.split()[-1]

    result = Client(base_url=base, api_key=key).run_suite(suite, flaky)
    by_case = {r["caseId"]: r for r in result.results}
    bob = next(r for r in result.results if r["verdict"] == "Fail")
    assert bob["category"] == "Execution error" and "model unavailable" in bob["reason"]
    assert result.summary["Pass"] == 2 and len(by_case) == 3


def test_uploads_retry_then_fail_clearly(server):
    base, key = server
    dead = f"http://127.0.0.1:{_free_port()}"
    started = time.time()
    with pytest.raises(WorkbenchError, match="Could not reach"):
        Client(base_url=dead, api_key=key, retries=2).run_suite("x", lambda t: t)
    assert time.time() - started >= 1.4  # backed off between attempts
    with pytest.raises(WorkbenchError) as e:
        Client(base_url=base, api_key="ewb_wrong").run_suite("x", lambda t: t)
    assert e.value.status == 401


def test_trace_is_a_noop_outside_a_run():
    @trace
    def add(a, b):
        with span("inner"):
            return a + b

    assert add(1, 2) == 3


def test_observe_sends_a_live_trace_without_blocking_the_app(server):
    base, key = server
    client = Client(base_url=base, api_key=key)

    @trace(name="llm.generate", kind="llm")
    def app(text):
        return "Story about " + text

    def llm(text):
        with span("llm.call", kind="llm") as s:
            s.set(input_tokens=12, output_tokens=30, cost_usd=0.0004)
            return app(text)

    assert client.observe("live-suite", llm, "a fox", suite_name="Live suite", version="live", model="m", user_id=42,
                          session_id="chat-1", tags=["fables"], metadata={"plan": "free", "at": datetime.date(2026, 9, 27)}) == "Story about a fox"
    for _ in range(40):  # the upload happens in a background thread
        runs = _call(base, "GET", "/runs?suite_id=live-suite", key=key)
        if runs and runs[0]["results"] is None and _call(base, "GET", f"/runs/{runs[0]['id']}", key=key)["results"]:
            break
        time.sleep(0.25)
    detail = _call(base, "GET", f"/runs/{runs[0]['id']}", key=key)["results"][0]
    assert detail["input"] == "a fox" and detail["actual"] == "Story about a fox"
    one = _call(base, "GET", f"/production/traces/{runs[0]['id']}/{detail['caseId']}", key=key)["result"]
    assert [s["name"] for s in one["spans"]] == ["request", "llm.call", "llm.generate"]
    assert (one["userId"], one["sessionId"], one["tags"]) == ("42", "chat-1", ["fables"])
    assert one["metadata"] == {"plan": "free", "at": "2026-09-27"}  # values JSON can't hold are sent as text
    assert (one["tokensIn"], one["tokensOut"], one["costUsd"], one["verdict"]) == (12, 30, 0.0004, "Pass")

    with pytest.raises(ValueError):
        client.observe("live-suite", lambda t: (_ for _ in ()).throw(ValueError("boom")), "x")
    # Errors the app marks as not about quality (such as a rejected key) are re-raised but never sent.
    with pytest.raises(PermissionError):
        client.observe("ignored-suite", lambda t: (_ for _ in ()).throw(PermissionError("bad key")), "x", ignore_errors=(PermissionError,))
    client.flush()
    assert _call(base, "GET", "/runs?suite_id=ignored-suite", key=key) == []
    dead = Client(base_url=f"http://127.0.0.1:{_free_port()}", api_key=key, retries=0)
    assert dead.observe("live-suite", lambda t: "still works", "x") == "still works"


def test_short_lived_script_still_delivers_its_trace(server):
    """A script that exits right after observe() must not lose the trace."""
    base, key = server
    script = ("from eval_workbench import Client\n"
              f"Client(base_url={base!r}, api_key={key!r}).observe('exit-test', lambda t: 'done', 'hi', suite_name='Exit test')\n")
    subprocess.run([sys.executable, "-c", script], check=True, timeout=60)
    runs = _call(base, "GET", "/runs?suite_id=exit-test", key=key)
    assert runs and _call(base, "GET", f"/runs/{runs[0]['id']}", key=key)["results"][0]["actual"] == "done"


def test_post_without_a_body_still_sends_one(tmp_path):
    """Google Cloud Run answers 411 to a POST with no Content-Length, which broke run completion."""
    import http.server
    import threading

    seen = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["length"] = self.headers.get("Content-Length")
            seen["body"] = self.rfile.read(int(seen["length"] or 0))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Client(base_url=f"http://127.0.0.1:{srv.server_port}", api_key="k")._request("POST", "/runs/x/complete")
    srv.shutdown()
    assert seen["length"] == "2" and seen["body"] == b"{}"


def test_delete_project_removes_everything_and_the_key(server):
    base, _ = server
    _call(base, "POST", "/admin/projects", {"name": "Short lived"})
    key = _call(base, "POST", "/admin/projects/short-lived/keys", {"name": "t"})["key"]
    client = Client(base_url=base, api_key=key, retries=0)
    s = client.import_suite(json.dumps({"name": "Tmp", "cases": [{"input": "hi", "checks": [{"type": "contains_any", "values": ["hi"]}]}]}))
    client.run_suite(s["id"], lambda text: text)
    with pytest.raises(WorkbenchError) as e:
        client.delete_project("wrong-id")
    assert e.value.status == 400
    out = client.delete_project("short-lived")
    assert out["deleted"]["results"] == 1 and out["deleted"]["projects"] == 1
    with pytest.raises(WorkbenchError) as e:
        client.get_suite(s["id"])
    assert e.value.status == 401
