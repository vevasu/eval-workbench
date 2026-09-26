"""Operator commands for the private beta. Run from the backend folder:

    python -m app.manage requests            list pending access requests
    python -m app.manage approve 3           approve request 3: creates a project and prints its API key once
    python -m app.manage reject 3
    python -m app.manage projects            list projects with usage
    python -m app.manage newkey <project>    create another key for a project
    python -m app.manage revoke <key id>
    python -m app.manage delete-project <project>   delete a project and all its data (asks you to type its id)
    python -m app.manage delete-request 3           delete an access request and the email in it
"""
import argparse
import secrets
import sys

from sqlmodel import Session, select

from . import beta
from .auth import hash_key, new_key
from .db import engine, init_db
from .limits import result_count, suite_count
from .models import AccessRequest, ApiKey, Project, now_ms
from .settings import limits

QUICKSTART = """
Send this to the requester:

  pip install <your Workbench address>/sdk/eval_workbench-0.1.0-py3-none-any.whl
  set EVAL_WORKBENCH_URL=<your Workbench address>
  set EVAL_WORKBENCH_API_KEY={key}

  from eval_workbench import Client
  client = Client()
  client.run_suite("my-suite", my_app)      # or client.observe(...) for live traffic
"""


def main() -> None:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="python -m app.manage")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("requests").add_argument("--all", action="store_true")
    for name in ("approve", "reject"):
        sub.add_parser(name).add_argument("id", type=int)
    sub.add_parser("projects")
    sub.add_parser("newkey").add_argument("project")
    sub.add_parser("revoke").add_argument("key_id")
    sub.add_parser("delete-project").add_argument("project")
    sub.add_parser("delete-request").add_argument("id", type=int)
    a = p.parse_args()

    init_db()
    with Session(engine) as s:
        if a.cmd == "requests":
            rows = s.exec(select(AccessRequest).order_by(AccessRequest.created_at)).all()
            for x in rows:
                if a.all or x.status == "pending":
                    print(f"#{x.id}  {x.status:<9} {x.email:<32} {x.name}  {x.use_case[:70]}")
            if not rows:
                print("No access requests yet.")
        elif a.cmd == "approve":
            out = beta.approve(s, a.id)
            print(f"Approved #{out['requestId']} ({out['email']}). Project: {out['projectId']}")
            print(QUICKSTART.format(key=out["key"]))
            print("This key is shown only once.")
        elif a.cmd == "reject":
            beta.reject(s, a.id)
            print(f"Rejected #{a.id}.")
        elif a.cmd == "projects":
            cap = limits()
            for pr in s.exec(select(Project)).all():
                print(f"{pr.id:<24} {result_count(s, pr.id):>6}/{cap['max_results']} executions  "
                      f"{suite_count(s, pr.id):>3}/{cap['max_suites']} suites  {pr.name}")
        elif a.cmd == "newkey":
            if s.get(Project, a.project) is None:
                raise SystemExit(f"No project '{a.project}'.")
            key = new_key()
            s.add(ApiKey(id=secrets.token_hex(6), project_id=a.project, name="extra", prefix=key[:12], key_hash=hash_key(key)))
            s.commit()
            print(QUICKSTART.format(key=key))
        elif a.cmd == "revoke":
            k = s.get(ApiKey, a.key_id)
            if k is None:
                raise SystemExit("No such key id.")
            k.revoked_at = now_ms()
            s.add(k)
            s.commit()
            print(f"Revoked key {k.prefix}...")
        elif a.cmd == "delete-project":
            if s.get(Project, a.project) is None:
                raise SystemExit(f"No project '{a.project}'.")
            print(f"This permanently deletes project '{a.project}': its suites, runs, results, traces, keys and access request.")
            if input("Type the project id to confirm: ").strip() != a.project:
                raise SystemExit("Not deleted.")
            out = beta.delete_project(s, a.project)
            print("Deleted: " + ", ".join(f"{n} {k}" for k, n in out["deleted"].items()))
        elif a.cmd == "delete-request":
            beta.delete_request(s, a.id)
            print(f"Deleted access request #{a.id}.")


if __name__ == "__main__":
    main()
