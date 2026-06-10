#!/usr/bin/env python3
"""Local live dashboard server for the LCC Domain report automation."""

from __future__ import annotations

import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
MONITOR_DIR = BASE_DIR / "monitor"
STATUS_DIR = BASE_DIR / "status"
LOGS_DIR = BASE_DIR / "logs"
PORT = 8767
TASK_NAME = "LCC Domain Meals Report Automation"


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def read_history(limit: int = 30):
    path = STATUS_DIR / "history.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    rows = []
    for line in lines[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def read_log_tail(lines: int = 120):
    path = LOGS_DIR / "report-automation.log"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-lines:]


def read_scheduler_status():
    script = f"""
$ErrorActionPreference = 'Stop'
$taskName = {json.dumps(TASK_NAME)}
$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
$action = $task.Actions | Select-Object -First 1
$trigger = $task.Triggers | Select-Object -First 1
[ordered]@{{
  name = $task.TaskName
  path = $task.TaskPath
  state = $task.State.ToString()
  enabled = ($task.State.ToString() -ne 'Disabled')
  last_run_time = if ($info.LastRunTime -and $info.LastRunTime.Year -gt 1900) {{ $info.LastRunTime.ToString('o') }} else {{ $null }}
  next_run_time = if ($info.NextRunTime -and $info.NextRunTime.Year -gt 1900) {{ $info.NextRunTime.ToString('o') }} else {{ $null }}
  last_task_result = $info.LastTaskResult
  action_execute = $action.Execute
  action_arguments = $action.Arguments
  trigger_start_boundary = $trigger.StartBoundary
  trigger_enabled = $trigger.Enabled
}} | ConvertTo-Json -Depth 6
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return {
                "name": TASK_NAME,
                "status": "error",
                "error": (result.stderr or result.stdout).strip(),
            }
        payload = json.loads(result.stdout)
        payload["status"] = scheduler_health(payload)
        return payload
    except Exception as exc:
        return {"name": TASK_NAME, "status": "error", "error": str(exc)}


def scheduler_health(payload):
    if not payload.get("enabled"):
        return "error"
    if payload.get("state") == "Running":
        return "running"
    if payload.get("last_task_result") not in (0, None):
        return "warning"
    return "success"


class MonitorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self.serve_file(MONITOR_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/api/status":
            payload = {
                "current": read_json(STATUS_DIR / "current-run.json", None),
                "last": read_json(STATUS_DIR / "last-run.json", None),
                "history": read_history(),
                "logs": read_log_tail(),
                "scheduler": read_scheduler_status(),
            }
            self.serve_json(payload)
            return
        if path == "/api/last-run":
            self.serve_json(read_json(STATUS_DIR / "last-run.json", {}))
            return
        if path == "/api/history":
            self.serve_json(read_history())
            return
        if path == "/api/logs":
            self.serve_json(read_log_tail())
            return

        self.send_error(404)

    def serve_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_json(self, payload):
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return


def main():
    STATUS_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), MonitorHandler)
    print(f"LCC Domain automation monitor: http://127.0.0.1:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
