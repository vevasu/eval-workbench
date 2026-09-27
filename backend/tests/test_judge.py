import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlmodel import Session

from app import judge
from app.db import engine
from app.models import Project
from app.routers import ingest

STORY_RULE = {"type": "not_contains", "values": ["…"], "category": "Incomplete answer"}
FOLLOWS = {"type": "llm_judge", "criteria": "Does what the person asked. If they ask for no story, it does not write one."}


class FakeModel(BaseHTTPRequestHandler):
    """Answers like OpenAI's chat completions. Fails a story written for someone who asked for none."""
    calls: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeModel.calls.append({"auth": self.headers.get("Authorization"), "model": body["model"], "prompt": body["messages"][1]["content"]})
        if self.headers.get("Authorization") == "Bearer sk-wrong":
            self._send(401, {"error": {"message": "Incorrect API key provided."}})
            return
        prompt = body["messages"][1]["content"]
        asked_none = "Dont suggest any story" in prompt
        verdict = {"pass": not asked_none, "reason": "The person asked not to get a story, and got one." if asked_none else "Does what was asked."}
        self._send(200, {"choices": [{"message": {"content": json.dumps(verdict)}}]})

    def _send(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def model(monkeypatch_module):
    srv = HTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch_module.setenv("EVAL_WORKBENCH_JUDGE_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    yield FakeModel.calls
    srv.shutdown()


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def team(client, admin, model):
    client.post("/admin/projects", headers=admin, json={"name": "Judged", "id": "judged"})
    auth = {"Authorization": "Bearer " + client.post("/admin/projects/judged/keys", headers=admin, json={"name": "t"}).json()["key"]}
    client.post("/suites", headers=auth, json={"name": "Stories live", "id": "stories-live"})
    return auth


def wait_for(client, auth, run_id, case_id, timeout=10):
    """Production requests are judged in the background: wait until the judge has answered."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/production/traces/{run_id}/{case_id}", headers=auth).json()["result"]
        if r["category"] != "Awaiting AI judge":
            return r
        time.sleep(0.1)
    raise AssertionError("the AI judge did not answer")


def send(client, auth, text, story, **extra):
    out = client.post("/ingest", headers=auth, json={"suiteId": "stories-live", "input": text, "actual": story, "checks": [STORY_RULE], **extra}).json()
    return out["runId"], out["result"]


def test_a_saved_model_key_is_encrypted_and_never_shown(client, team, model):
    assert client.get("/settings/judge", headers=team).json()["configured"] is False
    assert client.post("/settings/judge/test", headers=team).status_code == 400
    saved = client.put("/settings/judge", headers=team, json={"apiKey": "sk-test-judge-1234", "model": "gpt-4o-mini"}).json()
    assert saved == {"configured": True, "provider": "openai", "model": "gpt-4o-mini", "keyHint": "sk-…1234", "unreadable": False}
    assert "sk-test-judge-1234" not in json.dumps(client.get("/settings/judge", headers=team).json())
    with Session(engine) as s:
        stored = s.get(Project, "judged").judge_key
    assert stored and "sk-test-judge-1234" not in stored  # encrypted at rest
    assert client.post("/settings/judge/test", headers=team).json()["ok"] is True
    assert model[-1]["auth"] == "Bearer sk-test-judge-1234"


def test_checks_set_in_the_web_app_run_on_every_live_request(client, team, model):
    assert client.put("/suites/stories-live/live-checks", headers=team, json={"checks": [{"type": "llm_judge"}]}).status_code == 422
    assert client.put("/suites/stories-live/live-checks", headers=team, json={"checks": [{**FOLLOWS, "sample": 0}]}).status_code == 422
    assert client.put("/suites/stories-live/live-checks", headers=team, json={"checks": [FOLLOWS]}).json() == {"checks": [FOLLOWS]}
    state = client.get("/state", headers=team).json()
    assert state["suites"][0]["liveChecks"] == [FOLLOWS]

    run, first = send(client, team, "Dont suggest any story (genre: fantasy)", "In a hidden kingdom, a young sorceress named Lyra found a crystal.")
    assert (first["verdict"], first["category"]) == ("Review", "Awaiting AI judge")  # stored at once, judged just after
    judged = wait_for(client, team, run, first["caseId"])
    assert (judged["verdict"], judged["category"]) == ("Fail", "Instruction not followed")
    judge_check = next(c for c in judged["checks"] if c["type"] == "llm_judge")
    assert judge_check["pass"] is False and "asked not to get a story" in judge_check["detail"] and judge_check["judgedBy"] == "gpt-4o-mini"
    assert "pending" not in judge_check and "refusalExpected" not in judge_check

    run, ok = send(client, team, "A dragon who is scared of fire", "Ember the dragon feared fire, until the night she saved the village.")
    assert (wait_for(client, team, run, ok["caseId"])["verdict"]) == "Pass"


def test_the_judge_is_skipped_when_a_rule_already_failed(client, team, model):
    before = len(model)
    _, cut = send(client, team, "A pirate saga", "Captain Isla sailed for twenty years and…")
    assert (cut["verdict"], cut["category"]) == ("Fail", "Incomplete answer")
    skipped = next(c for c in cut["checks"] if c["type"] == "llm_judge")
    assert skipped["skipped"] is True and "Not judged" in skipped["detail"]
    time.sleep(0.3)
    assert len(model) == before  # no model call, so no cost


def test_a_judge_runs_only_on_its_sample(client, team, model, monkeypatch):
    client.put("/suites/stories-live/live-checks", headers=team, json={"checks": [{**FOLLOWS, "sample": 20}]})
    monkeypatch.setattr(ingest.random, "random", lambda: 0.5)  # 50 is outside a 20% sample
    _, out = send(client, team, "A cat", "A cat found a door.")
    assert out["verdict"] == "Pass" and not any(c["type"] == "llm_judge" for c in out["checks"])
    monkeypatch.setattr(ingest.random, "random", lambda: 0.1)  # 10 is inside
    _, out = send(client, team, "A cat", "A cat found a door.")
    assert out["category"] == "Awaiting AI judge"
    client.put("/suites/stories-live/live-checks", headers=team, json={"checks": [FOLLOWS]})


def test_without_a_working_key_a_person_decides_instead(client, team, model):
    client.put("/settings/judge", headers=team, json={"apiKey": "sk-wrong"})
    run, out = send(client, team, "A cat", "A cat found a door.")
    judged = wait_for(client, team, run, out["caseId"])
    assert (judged["verdict"], judged["category"]) == ("Review", "Awaiting human review")
    assert "rejected the saved key" in next(c for c in judged["checks"] if c["type"] == "llm_judge")["detail"]
    assert client.post("/settings/judge/test", headers=team).json()["ok"] is False
    client.delete("/settings/judge", headers=team)
    run, out = send(client, team, "A cat", "A cat found a door.")
    assert "no model key is saved" in next(c for c in wait_for(client, team, run, out["caseId"])["checks"] if c["type"] == "llm_judge")["detail"]
    client.put("/settings/judge", headers=team, json={"apiKey": "sk-test-judge-1234"})


def test_test_cases_can_use_the_judge_and_runs_are_judged_before_they_finish(client, team, model):
    suite = client.post("/suites", headers=team, json={"name": "Stories"}).json()["id"]
    case = client.post(f"/suites/{suite}/cases", headers=team, json={"input": "Dont suggest any story (genre: fantasy)", "checks": [FOLLOWS]}).json()["id"]
    run = client.post("/runs", headers=team, json={"suiteId": suite, "version": "v1"}).json()["run"]["id"]
    stored = client.post(f"/runs/{run}/results", headers=team, json={"results": [{"caseId": case, "actual": "Once upon a time, Lyra found a crystal."}]}).json()
    assert (stored["results"][0]["verdict"], stored["results"][0]["category"]) == ("Fail", "Instruction not followed")
    assert client.post(f"/runs/{run}/complete", headers=team).json()["summary"]["Fail"] == 1


def test_a_judgment_lost_earlier_is_picked_up_by_the_next_one(client, team, model, monkeypatch):
    lost = []
    monkeypatch.setattr(ingest, "judge_later", lambda *a: lost.append(a))  # as if the server restarted before judging
    old = int(time.time() * 1000) - 10 * 60 * 1000
    run, stuck = send(client, team, "Dont suggest any story", "Once upon a time.", timestamp=old)
    assert lost and stuck["category"] == "Awaiting AI judge"
    monkeypatch.setattr(ingest, "judge_later", judge.judge_later)
    send(client, team, "A dragon", "A dragon story.")
    assert wait_for(client, team, run, stuck["caseId"])["verdict"] == "Fail"
