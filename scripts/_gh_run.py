"""One-off: check the dispatch run status and its jobs."""

from __future__ import annotations

import subprocess
import sys

import requests

REPO = "blue1door1-Outreach/Social-automation"
credential = subprocess.run(
    ["git", "credential", "fill"],
    input="protocol=https\nhost=github.com\npath=blue1door1-Outreach/Social-automation.git\n\n",
    text=True,
    capture_output=True,
    check=True,
).stdout
token = ""
for line in credential.splitlines():
    if line.startswith("password="):
        token = line.split("=", 1)[1].strip()

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "khuje-nao-setup",
}
run_id = sys.argv[1]
run = requests.get(
    f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}",
    headers=headers,
    timeout=30,
).json()
print("status", run["status"], "conclusion", run["conclusion"])
jobs = requests.get(
    f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs",
    headers=headers,
    timeout=30,
).json()
for job in jobs.get("jobs", []):
    print("job", job["name"], job["status"], job["conclusion"])
    for step in job.get("steps", []):
        print("   ", step["number"], step["name"], step["status"], step.get("conclusion"))
