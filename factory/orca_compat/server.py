#!/usr/bin/env python3
"""A small, local Orca-compatible MCP server for Software Factory V1."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTECTED_BRANCHES = {"main", "master", "develop"}
PASS_VERDICTS = {"PASS", "PASS_WITH_NOTES"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(args: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        args, cwd=cwd, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{' '.join(args)} failed ({completed.returncode}): {detail}")
    return completed.stdout.strip()


class StateStore:
    def __init__(self, root: Path):
        self.root = root
        self.runs = root / "runs"
        self.pods = root / "pods"
        self.runs.mkdir(parents=True, exist_ok=True)
        self.pods.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str, item_id: str) -> Path:
        if not re.fullmatch(r"[a-z]+_[a-f0-9]{12}", item_id):
            raise ValueError(f"invalid {kind} id")
        return (self.runs if kind == "run" else self.pods) / f"{item_id}.json"

    def save(self, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        target = self._path(kind, item["id"])
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        ) as handle:
            json.dump(item, handle, indent=2, sort_keys=True)
            temp_name = handle.name
        os.replace(temp_name, target)
        return item

    def load(self, kind: str, item_id: str) -> dict[str, Any]:
        path = self._path(kind, item_id)
        if not path.exists():
            raise KeyError(f"unknown {kind}: {item_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[dict[str, Any]]:
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.runs.glob("*.json"))]


class FactoryService:
    def __init__(self, state_root: Path | None = None):
        root = state_root or Path(os.environ.get("SOFTWARE_FACTORY_ROOT", ".factory-state"))
        self.store = StateStore(root.resolve())
        self.worktrees_root = self.store.root / "worktrees"
        self.worktrees_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _repo(path: str) -> Path:
        repo = Path(path).resolve()
        if not repo.is_dir():
            raise ValueError(f"repository does not exist: {repo}")
        run_command(["git", "rev-parse", "--show-toplevel"], repo)
        return repo

    def create_run(
        self, goal: str, repository: str, implementer: str, base_branch: str = "main", pod_id: str | None = None
    ) -> dict[str, Any]:
        if not goal.strip() or not implementer.strip():
            raise ValueError("goal and implementer are required")
        repo = self._repo(repository)
        run_id = self._id("run")
        branch = f"agent/{run_id}"
        worktree = self.worktrees_root / run_id
        run_command(["git", "show-ref", "--verify", f"refs/heads/{base_branch}"], repo)
        run_command(["git", "worktree", "add", "-b", branch, str(worktree), base_branch], repo)
        item = {
            "id": run_id, "pod_id": pod_id, "goal": goal, "repository": str(repo),
            "base_branch": base_branch, "branch": branch, "worktree": str(worktree),
            "implementer": implementer, "status": "running", "created_at": now(),
            "reviews": [], "gate_evidence": {}, "candidate_pr": None,
        }
        return self.store.save("run", item)

    def create_pod(
        self, goal: str, repository: str, implementer: str, tasks: list[str], base_branch: str = "main"
    ) -> dict[str, Any]:
        if not tasks:
            raise ValueError("tasks must contain at least one explicitly decomposed task")
        pod_id = self._id("pod")
        pod = {"id": pod_id, "goal": goal, "tasks": tasks, "run_ids": [], "created_at": now()}
        self.store.save("pod", pod)
        try:
            for task in tasks:
                created = self.create_run(task, repository, implementer, base_branch, pod_id)
                pod["run_ids"].append(created["id"])
                self.store.save("pod", pod)
        except Exception:
            pod["status"] = "blocked"
            pod["updated_at"] = now()
            self.store.save("pod", pod)
            raise
        pod["status"] = "running"
        pod["updated_at"] = now()
        return self.store.save("pod", pod)

    def list_runs(self, status: str | None = None) -> dict[str, Any]:
        runs = self.store.list_runs()
        if status:
            runs = [item for item in runs if item["status"] == status]
        return {"runs": runs}

    def stage(self, run_id: str, gate_evidence: dict[str, Any], commit_message: str) -> dict[str, Any]:
        item = self.store.load("run", run_id)
        if item["branch"] in PROTECTED_BRANCHES or not item["branch"].startswith("agent/"):
            raise RuntimeError("refusing to stage a protected or non-worker branch")
        required = {"build", "lint", "typecheck", "unit_tests", "integration_tests", "golden_paths"}
        missing = sorted(required - set(gate_evidence))
        failing = sorted(k for k in required if gate_evidence.get(k, {}).get("exit_code") != 0)
        if missing or failing:
            raise RuntimeError(f"quality gates incomplete; missing={missing}, failing={failing}")
        worktree = Path(item["worktree"])
        run_command(["git", "add", "-A"], worktree)
        if run_command(["git", "status", "--porcelain"], worktree):
            run_command(["git", "commit", "-m", commit_message], worktree)
        item["gate_evidence"] = gate_evidence
        item["status"] = "ready"
        item["updated_at"] = now()
        return self.store.save("run", item)

    def review(self, run_id: str, reviewer: str, verdict: str, notes: str = "") -> dict[str, Any]:
        item = self.store.load("run", run_id)
        verdict = verdict.upper()
        if item["status"] != "ready":
            raise RuntimeError("run must be ready before review")
        if reviewer == item["implementer"]:
            raise RuntimeError("implementer cannot independently review their own run")
        if verdict not in {"PASS", "PASS_WITH_NOTES", "FAIL"}:
            raise ValueError("verdict must be PASS, PASS_WITH_NOTES, or FAIL")
        diff = run_command(["git", "diff", f"{item['base_branch']}...HEAD"], Path(item["worktree"]))
        item["reviews"] = [r for r in item["reviews"] if r["reviewer"] != reviewer]
        item["reviews"].append({"reviewer": reviewer, "verdict": verdict, "notes": notes, "at": now()})
        if verdict == "FAIL":
            item["status"] = "blocked"
        item["updated_at"] = now()
        self.store.save("run", item)
        return {"run": item, "diff": diff}

    def ship(self, run_id: str, title: str, body: str, draft: bool = True) -> dict[str, Any]:
        item = self.store.load("run", run_id)
        if item["status"] != "ready":
            raise RuntimeError("only a ready run may be shipped")
        independent_passes = [r for r in item["reviews"] if r["reviewer"] != item["implementer"] and r["verdict"] in PASS_VERDICTS]
        if not independent_passes:
            raise RuntimeError("at least one independent passing review is required")
        worktree = Path(item["worktree"])
        run_command(["git", "push", "-u", "origin", item["branch"]], worktree)
        args = ["gh", "pr", "create", "--base", item["base_branch"], "--head", item["branch"], "--title", title, "--body", body]
        if draft:
            args.append("--draft")
        url = run_command(args, worktree).splitlines()[-1]
        item["status"] = "shipped"
        item["candidate_pr"] = url
        item["updated_at"] = now()
        self.store.save("run", item)
        return {"run_id": run_id, "candidate_pr": url}


TOOLS = [
    ("orca_create_run", "Create an isolated worker run and Git worktree", {"goal": "string", "repository": "string", "implementer": "string", "base_branch": "string"}),
    ("orca_create_pod", "Create explicitly decomposed runs in isolated worktrees", {"goal": "string", "repository": "string", "implementer": "string", "tasks": "array", "base_branch": "string"}),
    ("orca_list_runs", "List persistent runs", {"status": "string"}),
    ("orca_stage", "Commit a run only after deterministic gates pass", {"run_id": "string", "gate_evidence": "object", "commit_message": "string"}),
    ("orca_review", "Record an independent review with the complete diff", {"run_id": "string", "reviewer": "string", "verdict": "string", "notes": "string"}),
    ("orca_ship", "Push and create a reviewed candidate pull request", {"run_id": "string", "title": "string", "body": "string", "draft": "boolean"}),
]


def tool_definitions() -> list[dict[str, Any]]:
    definitions = []
    for name, description, fields in TOOLS:
        properties = {}
        for field, kind in fields.items():
            properties[field] = {"type": kind}
        optional = {"base_branch", "status", "notes", "draft"}
        definitions.append({"name": name, "description": description, "inputSchema": {"type": "object", "properties": properties, "required": [f for f in fields if f not in optional], "additionalProperties": False}})
    return definitions


def handle(service: FactoryService, request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {"protocolVersion": request.get("params", {}).get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}}, "serverInfo": {"name": "codeup-orca-compat", "version": "0.1.0"}}
    elif method == "tools/list":
        result = {"tools": tool_definitions()}
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        dispatch = {
            "orca_create_run": service.create_run, "orca_create_pod": service.create_pod,
            "orca_list_runs": service.list_runs, "orca_stage": service.stage,
            "orca_review": service.review, "orca_ship": service.ship,
        }
        if name not in dispatch:
            raise ValueError(f"unknown tool: {name}")
        value = dispatch[name](**arguments)
        result = {"content": [{"type": "text", "text": json.dumps(value)}], "structuredContent": value}
    else:
        raise ValueError(f"unsupported method: {method}")
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def serve() -> int:
    service = FactoryService()
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        try:
            response = handle(service, request)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32000, "message": str(exc)}}
        if response is not None:
            print(json.dumps(response, separators=(",", ":")), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="codeup-orca")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")
    mcp = sub.add_parser("mcp")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_sub.add_parser("serve")
    args = parser.parse_args()
    if args.command == "version":
        print("codeup-orca-compat 0.1.0")
        return 0
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
