import atexit
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .tracing import start_recording, stop_recording

DEFAULT_URL = "http://127.0.0.1:8000"


class WorkbenchError(Exception):
    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class RunResult:
    run_id: str
    summary: dict
    url: str
    results: list = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.summary["passRate"]


class Client:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 30, retries: int = 3):
        self.base_url = (base_url or os.environ.get("EVAL_WORKBENCH_URL") or DEFAULT_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("EVAL_WORKBENCH_API_KEY")
        if not self.api_key:
            raise WorkbenchError("No API key. Pass api_key=... or set EVAL_WORKBENCH_API_KEY.")
        self.timeout = timeout
        self.retries = retries
        self._pending: list = []
        atexit.register(self.flush)  # short-lived scripts must not exit before their traces are uploaded

    def flush(self, timeout: float = 10) -> None:
        """Wait for traces from observe() that are still uploading. Called automatically at exit."""
        deadline = time.time() + timeout
        for t in list(self._pending):
            t.join(max(0.0, deadline - time.time()))
        self._pending = [t for t in self._pending if t.is_alive()]

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        # Some hosts (Google's front end) reject a POST with no body, so always send one.
        data = json.dumps(body).encode() if body is not None else (b"{}" if method in ("POST", "PUT", "PATCH") else None)
        last: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.base_url + path, data=data, method=method, headers={
                "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                try:
                    detail = json.loads(detail).get("detail", detail)
                except ValueError:
                    pass
                if e.code < 500:
                    raise WorkbenchError(f"{method} {path} failed ({e.code}): {detail}", e.code) from None
                last = WorkbenchError(f"{method} {path} failed ({e.code}): {detail}", e.code)
            except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                last = WorkbenchError(f"Could not reach Eval Workbench at {self.base_url}: {e}")
            if attempt < self.retries:
                time.sleep(0.5 * 2 ** attempt)
        raise last  # type: ignore[misc]

    def get_suite(self, suite_id: str) -> Optional[dict]:
        try:
            return self._request("GET", f"/suites/{suite_id}")
        except WorkbenchError as e:
            if e.status == 404:
                return None
            raise

    def import_suite(self, content: str, format: str = "json", name: Optional[str] = None) -> dict:
        """Create a suite from JSON or CSV text (same format as the Import suite dialog)."""
        return self._request("POST", "/suites/import", {"format": format, "content": content, "name": name})

    def observe(
        self,
        suite_id: str,
        fn: Callable[[str], Any],
        input_text: str,
        *,
        suite_name: Optional[str] = None,
        version: str = "",
        model: str = "",
        checks: Optional[list] = None,
    ) -> Any:
        """Call fn(input_text) for a real request and send its trace to the Workbench in the background.

        Use this in your running application. The trace is scored by `checks` (same format as suite checks).
        Sending never slows or breaks the request: failures to upload are dropped. Errors from fn are re-raised.
        """
        rec, token = start_recording()
        timestamp = int(time.time() * 1000)
        output, error, failure = "", None, None
        try:
            out = fn(input_text)
            output = out if isinstance(out, str) else ("" if out is None else json.dumps(out, default=str))
        except Exception as e:  # noqa: BLE001
            error, failure = f"{type(e).__name__}: {e}", e
        finally:
            latency = rec.now_ms()
            stop_recording(token)
        root = {"name": "request", "kind": "root", "start": 0, "dur": round(latency, 1), "depth": 0,
                "attrs": {"suite": suite_name or suite_id}}
        payload = {"suiteId": suite_id, "suiteName": suite_name, "input": input_text, "actual": output,
                   "latencyMs": max(1, round(latency)), "timestamp": timestamp, "spans": [root] + rec.spans,
                   "error": error, "version": version, "model": model, "checks": checks or []}

        def send() -> None:
            try:
                self._request("POST", "/ingest", payload)
            except Exception:  # noqa: BLE001 - monitoring must never affect the application
                pass

        upload = threading.Thread(target=send, daemon=True)
        self._pending = [t for t in self._pending if t.is_alive()] + [upload]
        upload.start()
        if failure is not None:
            raise failure
        return output

    def run_suite(
        self,
        suite_id: str,
        fn: Callable[[str], Any],
        *,
        version: str = "",
        model: str = "",
        note: str = "",
        batch_size: int = 10,
        on_result: Optional[Callable[[dict], None]] = None,
    ) -> RunResult:
        """Run every test case in a suite through fn(input), then upload outputs, timings and spans.

        fn runs in your own process. If it raises, that case is recorded as an execution error.
        """
        started = self._request("POST", "/runs", {"suiteId": suite_id, "version": version, "model": model, "note": note})
        run_id, cases = started["run"]["id"], started["cases"]
        suite_name = self._request("GET", f"/suites/{suite_id}")["name"]
        scored: list = []
        batch: list = []

        def flush() -> None:
            if not batch:
                return
            stored = self._request("POST", f"/runs/{run_id}/results", {"results": batch})["results"]
            scored.extend(stored)
            for row in stored:
                if on_result:
                    on_result(row)
            batch.clear()

        for case in cases:
            rec, token = start_recording()
            timestamp = int(time.time() * 1000)
            output, error = "", None
            try:
                out = fn(case["input"])
                output = out if isinstance(out, str) else ("" if out is None else json.dumps(out, default=str))
            except Exception as e:  # noqa: BLE001 - any failure in the user's code is an execution error
                error = f"{type(e).__name__}: {e}"
            finally:
                latency = rec.now_ms()
                stop_recording(token)
            root = {"name": "request", "kind": "root", "start": 0, "dur": round(latency, 1), "depth": 0,
                    "attrs": {"suite": suite_name, "case": case["id"]}}
            batch.append({"caseId": case["id"], "actual": output, "latencyMs": max(1, round(latency)), "timestamp": timestamp,
                          "spans": [root] + rec.spans, "error": error})
            if len(batch) >= batch_size:
                flush()
        flush()

        done = self._request("POST", f"/runs/{run_id}/complete")
        return RunResult(run_id=run_id, summary=done["summary"], url=f"{self.base_url}/#/results/{run_id}", results=scored)
