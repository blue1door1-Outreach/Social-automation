"""One-off: fetch the failed job log and show the useful lines."""

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
jobs = requests.get(
    f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs",
    headers=headers,
    timeout=30,
).json()

for job in jobs.get("jobs", []):
    if job["conclusion"] != "failure":
        continue
    logs = requests.get(
        f"https://api.github.com/repos/{REPO}/actions/jobs/{job['id']}/logs",
        headers=headers,
        timeout=60,
    )
    print("job", job["name"], "log status", logs.status_code, "bytes", len(logs.content))
    text = logs.text
    keywords = (
        "error",
        "Error",
        "Traceback",
        "buffer",
        "Buffer",
        "rejected",
        "FAILED",
        "status:",
        "due",
        "gate",
        "Missing",
    )
    for line in text.splitlines():
        if any(word in line for word in keywords):
            print(line[:400])
