#!/usr/bin/env python3
"""Record bounded local mining telemetry without controlling the miner."""
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("state", "mode", "hashrateTHs", "temperatureC", "temperatureLimitC",
          "powerDrawWatts", "jobsReceived", "blockCandidates", "submittedBlockProofs",
          "proofErrors", "workMode", "stopReason")

def sample():
    row = {"timestamp": datetime.now(timezone.utc).isoformat()}
    try:
        with urllib.request.urlopen("http://127.0.0.1:21550/api/status", timeout=5) as response:
            status = json.load(response)
        row["status"] = {k: status[k] for k in FIELDS if k in status}
    except Exception as error:
        row["statusError"] = str(error)
    try:
        result = subprocess.run([
            "/usr/lib/wsl/lib/nvidia-smi",
            "--query-gpu=utilization.gpu,temperature.gpu,power.draw,power.limit,clocks.gr,clocks.mem",
            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10, check=True)
        row["gpu"] = dict(zip(("utilizationPercent", "temperatureC", "powerWatts",
                              "powerLimitWatts", "coreMHz", "memoryMHz"),
                             map(float, result.stdout.strip().split(","))))
    except Exception as error:
        row["gpuError"] = str(error)
    return row

if __name__ == "__main__":
    folder = ROOT / "diagnostics" / "hourly"
    folder.mkdir(parents=True, exist_ok=True)
    while True:
        row = sample()
        with (folder / (row["timestamp"][:10] + ".jsonl")).open("a") as output:
            output.write(json.dumps(row) + "\n")
        time.sleep(30)
