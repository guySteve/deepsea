from __future__ import annotations

import argparse
import base64
from collections import deque
import csv
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from pearl_solo import (
    SoloServiceError,
    get_status as get_solo_status,
    is_managed_endpoint,
    start_services as start_solo_services,
)


WALLET_PATTERN = re.compile(r"^prl1p[023456789acdefghjklmnpqrstuvwxyz]{58}$")
WORKER_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
HASHRATE_PATTERN = re.compile(r"\(([0-9.]+) TH/s")
JOB_PATTERN = re.compile(r"\bjob\s+(\S+)\s+target=2\^(\d+)")
SOLO_TARGET_PATTERN = re.compile(r"solo: new template target=2\^(\d+)\s+bound=2\^(\d+)")


class RunnerError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def handle_termination(_signum, _frame) -> None:
    raise KeyboardInterrupt


def version_tuple(value: str) -> tuple[int, ...]:
    matches = re.findall(r"\d+", value)
    return tuple(int(part) for part in matches[:3])


def find_nvidia_smi() -> str:
    candidates = [shutil.which("nvidia-smi"), "/usr/lib/wsl/lib/nvidia-smi"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RunnerError("nvidia-smi is unavailable inside WSL")


def run_command(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RunnerError(f"command failed: {' '.join(command)}\n{detail}")
    return result


def query_gpu(nvidia_smi: str, gpu_index: int, fields: list[str]) -> dict[str, str]:
    result = run_command([
        nvidia_smi,
        "-i",
        str(gpu_index),
        f"--query-gpu={','.join(fields)}",
        "--format=csv,noheader,nounits",
    ])
    rows = list(csv.reader(result.stdout.strip().splitlines()))
    if len(rows) != 1 or len(rows[0]) != len(fields):
        raise RunnerError(f"unexpected nvidia-smi response: {result.stdout.strip()}")
    return {field: value.strip() for field, value in zip(fields, rows[0])}


def normalize_endpoint(value: str, label: str) -> str:
    endpoint = value.strip()
    if "://" in endpoint:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"tcp", "stratum+tcp"}:
            raise RunnerError(f"{label} only supports tcp:// or stratum+tcp:// addresses")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
            raise RunnerError(f"{label} must contain only a host and port")
        host = parsed.hostname or ""
        try:
            port = parsed.port
        except ValueError as error:
            raise RunnerError(f"{label} contains an invalid port") from error
    else:
        if endpoint.count(":") != 1:
            raise RunnerError(f"{label} must use host:port format")
        host, port_text = endpoint.rsplit(":", 1)
        if not port_text.isdigit():
            raise RunnerError(f"{label} contains an invalid port")
        port = int(port_text)
    if not host or not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise RunnerError(f"{label} contains an invalid hostname")
    if port is None or not 1 <= int(port) <= 65535:
        raise RunnerError(f"{label} port must be between 1 and 65535")
    return f"{host}:{int(port)}"


def load_config(config_path: Path) -> dict:
    local = json.loads(config_path.read_text(encoding="utf-8"))
    profile_value = local.get("profile", "miner/rtx4070.json")
    profile_path = Path(profile_value)
    if not profile_path.is_absolute():
        profile_path = config_path.parent / profile_path
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile.update(local)
    profile.setdefault("mode", "pool")
    profile.setdefault("soloGateway", "127.0.0.1:8337")
    return profile


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_runtime(runtime_root: Path, config: dict) -> dict:
    manifest_path = runtime_root / "manifest.json"
    if not manifest_path.is_file():
        raise RunnerError(
            f"reviewed runtime is not installed at {runtime_root}; run scripts/install-pearl-runtime.sh")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if version_tuple(manifest["cudaToolkit"]) < version_tuple(config["minimumCudaToolkit"]):
        raise RunnerError("runtime CUDA toolkit is below the configured minimum")
    if manifest["cudaTarget"] != config["cudaTarget"]:
        raise RunnerError("runtime CUDA target does not match the RTX 4070 profile")
    if manifest["certificateVersion"] != 3:
        raise RunnerError("runtime is not pinned to Pearl certificate V3")
    for relative, metadata in manifest["artifacts"].items():
        artifact = runtime_root / relative
        if not artifact.is_file() or file_sha256(artifact) != metadata["sha256"]:
            raise RunnerError(f"runtime artifact failed checksum validation: {artifact}")
    return manifest


def validate_config(config: dict, mining: bool) -> None:
    target_power = int(config["powerLimitWatts"])
    target_clock = int(config["lockedCoreClockMHz"])
    if not 140 <= target_power <= 160:
        raise RunnerError("RTX 4070 power target must stay within 140-160 W")
    if not 2400 <= target_clock <= 2550:
        raise RunnerError("RTX 4070 locked core clock must stay within 2400-2550 MHz")
    if int(config["memoryClockOffsetMHz"]) != 0:
        raise RunnerError("memory overclocking is prohibited for this Pearl profile")
    if int(config["vramReserveMiB"]) < 1536:
        raise RunnerError("Windows VRAM reserve must be at least 1536 MiB")
    if int(config.get("region", 4096)) not in {2048, 4096, 8192}:
        raise RunnerError("Pearl work region must be 2048, 4096, or 8192")
    if int(config.get("foundBatch", 16)) not in {8, 16, 32, 64}:
        raise RunnerError("Pearl result batch must be one of 8, 16, 32, or 64 regions")
    if not mining:
        return
    mode = str(config.get("mode", "pool"))
    if mode not in {"pool", "solo"}:
        raise RunnerError("mining mode must be pool or solo")
    worker = str(config.get("worker", ""))
    if not WORKER_PATTERN.fullmatch(worker):
        raise RunnerError("worker must be 1-32 letters, numbers, dots, dashes, or underscores")
    config["pool"] = normalize_endpoint(str(config.get("pool", "")), "pool address")
    if mode == "pool":
        wallet = str(config.get("wallet", ""))
        if not WALLET_PATTERN.fullmatch(wallet):
            raise RunnerError("pool mode requires a valid Pearl mainnet payout address")
    else:
        config["soloGateway"] = normalize_endpoint(
            str(config.get("soloGateway", "")), "solo gateway")
    if bool(config.get("tls", False)):
        raise RunnerError("this reviewed miner supports plaintext LuckyPool V3 Stratum only")


def preflight_gpu(nvidia_smi: str, config: dict) -> dict[str, str]:
    fields = [
        "name",
        "driver_version",
        "compute_cap",
        "memory.total",
        "memory.free",
        "power.limit",
        "temperature.gpu",
        "clocks.max.graphics",
    ]
    gpu = query_gpu(nvidia_smi, int(config["gpuIndex"]), fields)
    if config["gpuNameContains"].lower() not in gpu["name"].lower():
        raise RunnerError(f"expected {config['gpuNameContains']}, found {gpu['name']}")
    if gpu["compute_cap"] != str(config["computeCapability"]):
        raise RunnerError(f"expected compute capability 8.9, found {gpu['compute_cap']}")
    if version_tuple(gpu["driver_version"]) < version_tuple(config["minimumDriver"]):
        raise RunnerError(
            f"NVIDIA driver {gpu['driver_version']} is below {config['minimumDriver']}")
    required_free = int(config["minerAllocationMiB"]) + int(config["vramReserveMiB"])
    if float(gpu["memory.free"]) < required_free:
        raise RunnerError(
            f"only {gpu['memory.free']} MiB VRAM is free; {required_free} MiB is required")
    if float(gpu["temperature.gpu"]) >= float(config["temperatureLimitC"]):
        raise RunnerError("GPU is already at or above the configured shutdown temperature")
    return gpu


class TuningSession:
    def __init__(self, nvidia_smi: str, config: dict):
        self.nvidia_smi = nvidia_smi
        self.config = config
        self.gpu_index = int(config["gpuIndex"])
        self.original_power: float | None = None
        self.active = False

    def apply(self) -> None:
        current = query_gpu(self.nvidia_smi, self.gpu_index, ["power.limit"])
        self.original_power = float(current["power.limit"])
        power = str(int(self.config["powerLimitWatts"]))
        clock = str(int(self.config["lockedCoreClockMHz"]))
        try:
            run_command([self.nvidia_smi, "-i", str(self.gpu_index), "-pl", power])
            run_command([
                self.nvidia_smi,
                "-i",
                str(self.gpu_index),
                "-lgc",
                f"{clock},{clock}",
            ])
        except RunnerError as error:
            self.restore()
            raise RunnerError(
                f"unable to apply the {power} W / {clock} MHz profile: {error}\n"
                "Run the Windows launcher as Administrator, or set the same limits manually.") from error
        self.active = True

    def restore(self) -> None:
        run_command([self.nvidia_smi, "-i", str(self.gpu_index), "-rgc"], check=False)
        if self.original_power is not None:
            run_command([
                self.nvidia_smi,
                "-i",
                str(self.gpu_index),
                "-pl",
                str(round(self.original_power)),
            ], check=False)
        self.active = False


class MinerStatus:
    def __init__(self, initial: dict):
        self._value = initial
        self._events: deque[dict] = deque(maxlen=80)
        self._logs: deque[str] = deque(maxlen=80)
        self._sequence = 0
        self._lock = threading.Lock()

    def update(self, **values) -> None:
        with self._lock:
            self._value.update(values)
            self._value["updatedAt"] = utc_now()

    def increment(self, name: str, amount: int = 1) -> int:
        with self._lock:
            value = int(self._value.get(name, 0)) + amount
            self._value[name] = value
            self._value["updatedAt"] = utc_now()
            return value

    def event(
        self,
        kind: str,
        title: str,
        detail: str = "",
        severity: str = "info",
    ) -> None:
        with self._lock:
            self._sequence += 1
            self._events.appendleft({
                "id": self._sequence,
                "timestamp": utc_now(),
                "kind": kind,
                "title": title,
                "detail": detail,
                "severity": severity,
            })
            self._value["updatedAt"] = utc_now()

    def append_log(self, line: str) -> None:
        with self._lock:
            self._logs.append(line[:700])
            self._value["lastMessage"] = line[:700]
            self._value["updatedAt"] = utc_now()

    def reset_session(self, **values) -> None:
        with self._lock:
            for key in (
                "acceptedShares",
                "acceptedUserShares",
                "acceptedDevShares",
                "rejectedShares",
                "proofCandidates",
                "blockCandidates",
                "submittedBlockProofs",
                "proofErrors",
                "jobsReceived",
                "staleJobs",
            ):
                self._value[key] = 0
            self._value.update(values)
            self._events.clear()
            self._logs.clear()
            self._value["updatedAt"] = utc_now()

    def snapshot(self) -> dict:
        with self._lock:
            value = dict(self._value)
            value["events"] = list(self._events)
            value["recentMessages"] = list(self._logs)
            return value


def create_initial_status(config: dict, manifest: dict, gpu: dict, state: str = "idle") -> MinerStatus:
    artifact_hash = manifest["artifacts"]["app/libp40cuda.so"]["sha256"]
    return MinerStatus({
        "state": state,
        "startedAt": None,
        "updatedAt": utc_now(),
        "worker": config.get("worker", "worker"),
        "mode": config.get("mode", "pool"),
        "pool": config.get("pool"),
        "soloGateway": config.get("soloGateway", "127.0.0.1:8337"),
        "endpoint": config.get("pool"),
        "connectionState": "idle",
        "gpuName": gpu["name"],
        "driverVersion": gpu["driver_version"],
        "gpuIndex": int(config["gpuIndex"]),
        "cudaTarget": config["cudaTarget"],
        "regionSize": int(config.get("region", 4096)),
        "foundBatch": int(config.get("foundBatch", 16)),
        "certificateVersion": 3,
        "devFeePercent": 2,
        "acceptedShares": 0,
        "acceptedUserShares": 0,
        "acceptedDevShares": 0,
        "rejectedShares": 0,
        "proofCandidates": 0,
        "blockCandidates": 0,
        "submittedBlockProofs": 0,
        "proofErrors": 0,
        "jobsReceived": 0,
        "staleJobs": 0,
        "hashrateTHs": None,
        "targetExponent": None,
        "boundExponent": None,
        "poolDifficulty": None,
        "verifiedBuild": True,
        "artifactSha256": artifact_hash,
        "minerCommit": manifest["minerSource"]["commit"],
        "pearlCommit": manifest["pearlSource"]["commit"],
        "profileName": config["profile"],
        "powerTargetWatts": int(config["powerLimitWatts"]),
        "coreTargetMHz": int(config["lockedCoreClockMHz"]),
        "temperatureLimitC": int(config["temperatureLimitC"]),
        "vramReserveMiB": int(config["vramReserveMiB"]),
        "soloNode": None,
    })


def record_miner_line(status: MinerStatus, line: str, mode: str) -> None:
    message = line.rstrip()
    if not message:
        return
    status.append_log(message)
    hashrate = HASHRATE_PATTERN.search(message)
    if hashrate:
        status.update(hashrateTHs=float(hashrate.group(1)))
    job = JOB_PATTERN.search(message)
    if job:
        status.increment("jobsReceived")
        status.update(currentJob=job.group(1), targetExponent=int(job.group(2)))
        status.event("job", "New pool job", f"{job.group(1)} · target 2^{job.group(2)}")
    solo_target = SOLO_TARGET_PATTERN.search(message)
    if solo_target:
        status.increment("jobsReceived")
        status.update(
            currentJob=f"template-{status.snapshot()['jobsReceived']}",
            targetExponent=int(solo_target.group(1)),
            boundExponent=int(solo_target.group(2)),
        )
        status.event(
            "job",
            "New solo template",
            f"network target 2^{solo_target.group(1)} · search bound 2^{solo_target.group(2)}",
        )
    if "[pool set_difficulty]" in message:
        difficulty = message.split("[pool set_difficulty]", 1)[1].strip()
        status.update(poolDifficulty=difficulty)
    if "HIT tile" in message:
        status.increment("proofCandidates")
        coordinates = message.split("HIT tile", 1)[1].split(";", 1)[0].strip()
        status.event("share", "Share candidate detected", coordinates, "candidate")
    if "BLOCK CANDIDATE" in message:
        status.increment("blockCandidates")
        detail = message.split("BLOCK CANDIDATE", 1)[1].strip(" !")
        status.event("block", "Potential block detected", detail, "candidate")
    if "SHARE ACCEPTED" in message:
        status.increment("acceptedShares")
        if "(DEV FEE)" in message:
            status.increment("acceptedDevShares")
            detail = "Developer-fee window"
        else:
            status.increment("acceptedUserShares")
            detail = "Credited to your pool account"
        status.event("share", "Share accepted", detail, "success")
    if "POOL RESPONSE" in message and '"result": false' in message.lower():
        status.increment("rejectedShares")
        status.event("share", "Share rejected", "Pool rejected the submitted proof", "warning")
    if "SUBMITTED BLOCK PROOF" in message:
        total = status.increment("submittedBlockProofs")
        status.event(
            "block",
            "Block proof submitted",
            f"Gateway submission #{total}; network confirmation remains pending",
            "success",
        )
    if "proof/submit error" in message or "solo: submit error" in message:
        status.increment("proofErrors")
        status.event("warning", "Proof submission failed", message.split(":", 1)[-1].strip(), "error")
    if "newer job" in message or "job superseded" in message:
        status.increment("staleJobs")
    if "authorized (" in message or "solo: connected to gateway" in message:
        status.update(connectionState="connected")
    if "connection issue" in message:
        status.update(connectionState="reconnecting")
    if "DEV FEE round" in message:
        status.update(workMode="developer-fee")
    elif "authorized (your wallet)" in message or (mode == "solo" and "connected to gateway" in message):
        status.update(workMode="user")


def monitor_gpu(
    process: subprocess.Popen[str],
    stop_event: threading.Event,
    status: MinerStatus,
    nvidia_smi: str,
    config: dict,
) -> None:
    fields = [
        "temperature.gpu",
        "power.draw",
        "power.limit",
        "clocks.current.graphics",
        "utilization.gpu",
        "memory.used",
        "memory.free",
    ]
    while process.poll() is None and not stop_event.wait(3):
        try:
            gpu = query_gpu(nvidia_smi, int(config["gpuIndex"]), fields)
        except RunnerError as error:
            status.update(telemetryError=str(error))
            continue
        status.update(
            temperatureC=float(gpu["temperature.gpu"]),
            powerDrawWatts=float(gpu["power.draw"]),
            powerLimitWatts=float(gpu["power.limit"]),
            coreClockMHz=float(gpu["clocks.current.graphics"]),
            utilizationPercent=float(gpu["utilization.gpu"]),
            memoryUsedMiB=float(gpu["memory.used"]),
            memoryFreeMiB=float(gpu["memory.free"]),
        )
        if float(gpu["temperature.gpu"]) >= float(config["temperatureLimitC"]):
            status.update(state="stopping", stopReason="temperature guardrail")
            status.event("guardrail", "Temperature guardrail tripped", message_for_gpu(gpu), "error")
            process.terminate()
            return
        if float(gpu["memory.free"]) < float(config["vramReserveMiB"]):
            status.update(state="stopping", stopReason="VRAM reserve guardrail")
            status.event("guardrail", "VRAM reserve guardrail tripped", message_for_gpu(gpu), "error")
            process.terminate()
            return
        if not 140 <= float(gpu["power.limit"]) <= 160:
            status.update(state="stopping", stopReason="power-limit guardrail")
            status.event("guardrail", "Power-limit guardrail tripped", message_for_gpu(gpu), "error")
            process.terminate()
            return


def message_for_gpu(gpu: dict[str, str]) -> str:
    return (
        f"{gpu.get('temperature.gpu', '?')} C · {gpu.get('power.limit', '?')} W limit · "
        f"{gpu.get('memory.free', '?')} MiB free")


def probe_endpoint(config: dict) -> dict:
    mode = str(config.get("mode", "pool"))
    endpoint = config["pool"] if mode == "pool" else config["soloGateway"]
    host, port_text = endpoint.rsplit(":", 1)
    started = time.monotonic()
    if mode == "pool":
        with socket.create_connection((host, int(port_text)), timeout=6) as connection:
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return {
            "ok": True,
            "mode": mode,
            "endpoint": endpoint,
            "latencyMs": round((time.monotonic() - started) * 1000, 1),
            "detail": "TCP reachable; LuckyPool V3 authorization occurs when mining starts",
        }
    request = json.dumps({
        "jsonrpc": "2.0",
        "method": "getMiningInfo",
        "id": 1,
        "params": {},
    }).encode("utf-8") + b"\n"
    with socket.create_connection((host, int(port_text)), timeout=8) as connection:
        connection.settimeout(8)
        connection.sendall(request)
        response = b""
        while b"\n" not in response and len(response) < 1024 * 1024:
            chunk = connection.recv(65536)
            if not chunk:
                break
            response += chunk
    if not response:
        raise RunnerError("solo gateway closed without returning getMiningInfo")
    payload = json.loads(response.split(b"\n", 1)[0])
    if payload.get("error"):
        error = payload["error"]
        raise RunnerError(f"solo gateway error: {error.get('message', error)}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RunnerError("solo gateway returned an invalid mining job")
    try:
        header = base64.b64decode(result["incomplete_header_bytes"], validate=True)
        target = int(result["target"])
        cert_version = int(result["cert_version"])
    except (KeyError, TypeError, ValueError) as error:
        raise RunnerError(
            "solo gateway mining job is missing a valid header, target, or certificate version"
        ) from error
    if not header or target <= 0:
        raise RunnerError("solo gateway returned an empty header or non-positive target")
    if cert_version != 3:
        raise RunnerError(
            f"solo gateway requires certificate version {cert_version}; this build only mines V3"
        )
    return {
        "ok": True,
        "mode": mode,
        "endpoint": endpoint,
        "latencyMs": round((time.monotonic() - started) * 1000, 1),
        "detail": f"Gateway returned a {len(header)}-byte Pearl V3 mining template",
    }


def build_miner_command(runtime_root: Path, config: dict, benchmark_regions: int | None) -> list[str]:
    command = [sys.executable, str(runtime_root / "app" / "miner_capi.py")]
    if benchmark_regions is not None:
        return command + [
            "--benchmark",
            "--benchmark-regions",
            str(benchmark_regions),
            "--region",
            str(config["region"]),
        ]
    if config.get("mode", "pool") == "solo":
        return command + [
            "--solo",
            str(config["soloGateway"]),
            "--pool",
            str(config["pool"]),
            "--worker",
            str(config["worker"]),
            "--region",
            str(config["region"]),
        ]
    return command + [
        "--single",
        "--wallet",
        str(config["wallet"]),
        "--worker",
        str(config["worker"]),
        "--pool",
        str(config["pool"]),
        "--region",
        str(config["region"]),
    ]


def run_miner(
    runtime_root: Path,
    config: dict,
    nvidia_smi: str,
    benchmark_regions: int | None,
    status: MinerStatus,
    process_callback=None,
) -> int:
    app = runtime_root / "app"
    site = runtime_root / "site"
    command = build_miner_command(runtime_root, config, benchmark_regions)
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = str(config["gpuIndex"])
    environment["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["P40_FOUND_BATCH"] = str(config.get("foundBatch", 16))
    environment["PYTHONPATH"] = os.pathsep.join((str(site), str(app)))
    environment["PATH"] = os.pathsep.join(("/usr/lib/wsl/lib", environment.get("PATH", "")))
    environment["LD_LIBRARY_PATH"] = os.pathsep.join(
        ("/usr/lib/wsl/lib", environment.get("LD_LIBRARY_PATH", "")))
    log_path = runtime_root / "logs" / "pearl-miner.log"
    stop_event = threading.Event()
    process: subprocess.Popen[str] | None = None
    mode = "benchmark" if benchmark_regions is not None else str(config.get("mode", "pool"))
    try:
        with log_path.open("a", encoding="utf-8", buffering=1) as log_file:
            process = subprocess.Popen(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            if process_callback:
                process_callback(process)
            status.update(
                state="running",
                processId=process.pid,
                connectionState="connecting" if benchmark_regions is None else "offline",
            )
            status.event("system", "Miner process started", f"PID {process.pid} · {mode} mode", "success")
            threading.Thread(
                target=monitor_gpu,
                args=(process, stop_event, status, nvidia_smi, config),
                daemon=True,
            ).start()
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
                log_file.write(line)
                record_miner_line(status, line, mode)
            return_code = process.wait()
            current = status.snapshot()
            if return_code == 0:
                next_state = "stopped" if benchmark_regions is None else "benchmark-complete"
            elif current.get("state") == "stopping":
                next_state = "stopped"
            else:
                next_state = "error"
            status.update(state=next_state, exitCode=return_code, connectionState="disconnected")
            if next_state == "error":
                status.event("system", "Miner exited unexpectedly", f"Exit code {return_code}", "error")
            else:
                status.event("system", "Miner stopped", f"Exit code {return_code}")
            return return_code
    except KeyboardInterrupt:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        status.update(state="stopped", stopReason="operator interrupt", connectionState="disconnected")
        return 130
    finally:
        stop_event.set()
        if process_callback:
            process_callback(None)


class MinerController:
    def __init__(
        self,
        runtime_root: Path,
        base_config: dict,
        manifest: dict,
        nvidia_smi: str,
        status: MinerStatus,
        tuning_ready: bool,
    ):
        self.runtime_root = runtime_root
        self.base_config = dict(base_config)
        self.manifest = manifest
        self.nvidia_smi = nvidia_smi
        self.status = status
        self.tuning_ready = tuning_ready
        self.shutdown_event = threading.Event()
        self._cancel_event = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        threading.Thread(target=self._idle_telemetry_loop, daemon=True).start()
        threading.Thread(target=self._solo_telemetry_loop, daemon=True).start()

    def public_config(self) -> dict:
        return {
            "mode": self.base_config.get("mode", "pool"),
            "wallet": self.base_config.get("wallet", ""),
            "worker": self.base_config.get("worker", "blockhunter"),
            "pool": self.base_config.get("pool", ""),
            "soloGateway": self.base_config.get("soloGateway", "127.0.0.1:8337"),
            "poolProtocol": "LuckyPool V3 plaintext Stratum",
            "soloProtocol": "pearl-gateway JSON-RPC over TCP",
            "tuningReady": self.tuning_ready,
            "powerTargetWatts": int(self.base_config["powerLimitWatts"]),
            "coreTargetMHz": int(self.base_config["lockedCoreClockMHz"]),
            "temperatureLimitC": int(self.base_config["temperatureLimitC"]),
            "vramReserveMiB": int(self.base_config["vramReserveMiB"]),
            "regionSize": int(self.base_config.get("region", 4096)),
            "devFeePercent": int(self.manifest["devFeePercent"]),
        }

    def _config_from_payload(self, payload: dict) -> dict:
        config = dict(self.base_config)
        for key in ("mode", "wallet", "worker", "pool", "soloGateway"):
            if key in payload:
                config[key] = str(payload[key]).strip()
        validate_config(config, mining=True)
        return config

    def _set_process(self, process: subprocess.Popen[str] | None) -> None:
        with self._lock:
            self._process = process

    def start(self, payload: dict) -> dict:
        with self._lock:
            if self._worker and self._worker.is_alive():
                raise RunnerError("the miner is already starting or running")
        if not self.tuning_ready and bool(self.base_config["requirePowerAndClockTuning"]):
            raise RunnerError(
                "GPU tuning is not armed; use start-pearl-mining.cmd so settings are applied and restored")
        if bool(self.base_config["requirePowerAndClockTuning"]):
            current = query_gpu(
                self.nvidia_smi,
                int(self.base_config["gpuIndex"]),
                ["power.limit"],
            )
            if not 140 <= float(current["power.limit"]) <= 160:
                raise RunnerError(
                    f"GPU power limit is {current['power.limit']} W; the approved range is 140-160 W")
        config = self._config_from_payload(payload)
        endpoint = config["pool"] if config["mode"] == "pool" else config["soloGateway"]
        self._cancel_event.clear()
        self.status.reset_session(
            state="starting",
            startedAt=utc_now(),
            mode=config["mode"],
            worker=config["worker"],
            pool=config["pool"],
            soloGateway=config["soloGateway"],
            endpoint=endpoint,
            connectionState="checking",
            hashrateTHs=None,
            currentJob=None,
            targetExponent=None,
            boundExponent=None,
            poolDifficulty=None,
            stopReason=None,
            exitCode=None,
            workMode="user",
        )
        self.status.event("system", "Start requested", f"{config['mode']} · {endpoint}")
        worker = threading.Thread(target=self._run_session, args=(config,), daemon=True)
        with self._lock:
            self._worker = worker
        worker.start()
        return {"ok": True, "state": "starting", "mode": config["mode"], "endpoint": endpoint}

    def _run_session(self, config: dict) -> None:
        try:
            preflight_gpu(self.nvidia_smi, config)
            if config["mode"] == "solo" and is_managed_endpoint(config["soloGateway"]):
                result = self._wait_for_local_solo(config)
                if result is None:
                    self.status.update(
                        state="stopped",
                        connectionState="disconnected",
                        stopReason="cancelled while waiting for node sync",
                    )
                    return
            else:
                result = probe_endpoint(config)
            self.status.update(connectionState="reachable", endpointLatencyMs=result["latencyMs"])
            self.status.event("network", "Endpoint ready", result["detail"], "success")
            if self._cancel_event.is_set():
                self.status.update(state="stopped", stopReason="cancelled before launch")
                return
            run_miner(
                self.runtime_root,
                config,
                self.nvidia_smi,
                None,
                self.status,
                self._set_process,
            )
        except Exception as error:
            self.status.update(
                state="error",
                connectionState="failed",
                stopReason=str(error),
            )
            self.status.event("system", "Unable to start mining", str(error), "error")
        finally:
            self._set_process(None)

    def _wait_for_local_solo(self, config: dict) -> dict | None:
        try:
            solo = start_solo_services()
        except SoloServiceError as error:
            raise RunnerError(str(error)) from error
        previous_state = ""
        while not self._cancel_event.is_set():
            solo = get_solo_status()
            state = str(solo.get("state", "starting"))
            detail = str(solo.get("detail", "Waiting for the local Pearl node"))
            if state == "ready":
                try:
                    return probe_endpoint(config)
                except (OSError, RunnerError, json.JSONDecodeError):
                    state = "starting-gateway"
                    detail = "Synced node is waiting for a valid Pearl V3 gateway template"
            self.status.update(
                state="syncing",
                connectionState=state,
                soloNode=solo,
                stopReason=None,
            )
            if state != previous_state:
                self.status.event("network", "Solo node status", detail)
                previous_state = state
            if state == "not-installed":
                raise RunnerError(detail)
            if self._cancel_event.wait(5):
                return None
        return None

    def stop(self) -> dict:
        self._cancel_event.set()
        with self._lock:
            process = self._process
            worker_active = bool(self._worker and self._worker.is_alive())
        if process and process.poll() is None:
            self.status.update(state="stopping", stopReason="operator request")
            self.status.event("system", "Stop requested", "Waiting for the miner process to exit")
            process.terminate()
            return {"ok": True, "state": "stopping"}
        if worker_active:
            self.status.update(state="stopping", stopReason="operator request")
            return {"ok": True, "state": "stopping"}
        self.status.update(state="stopped", connectionState="disconnected")
        return {"ok": True, "state": "stopped"}

    def probe(self, payload: dict) -> dict:
        config = self._config_from_payload(payload)
        if config["mode"] != "solo" or not is_managed_endpoint(config["soloGateway"]):
            return probe_endpoint(config)
        try:
            start_solo_services()
            solo = get_solo_status()
            if solo.get("state") != "ready":
                raise RunnerError(str(solo.get("detail", "Local Pearl node is not synced")))
            return probe_endpoint(config)
        except (SoloServiceError, OSError, RunnerError, json.JSONDecodeError) as error:
            solo = get_solo_status()
            self.status.update(soloNode=solo)
            detail = solo.get("detail") or str(error)
            raise RunnerError(
                f"{detail}. BlockHunter will enable solo mining when TCP 8337 is ready"
            ) from error

    def shutdown(self) -> dict:
        self.stop()
        self.shutdown_event.set()
        return {"ok": True, "state": "shutting-down"}

    def wait_for_process(self, timeout: float = 12) -> None:
        with self._lock:
            process = self._process
            worker = self._worker
        if process and process.poll() is None:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
        if worker and worker.is_alive():
            worker.join(timeout=2)

    def _idle_telemetry_loop(self) -> None:
        fields = [
            "temperature.gpu",
            "power.draw",
            "power.limit",
            "clocks.current.graphics",
            "utilization.gpu",
            "memory.used",
            "memory.free",
        ]
        while not self.shutdown_event.wait(3):
            with self._lock:
                mining = self._process is not None
            if mining:
                continue
            try:
                gpu = query_gpu(self.nvidia_smi, int(self.base_config["gpuIndex"]), fields)
                self.status.update(
                    temperatureC=float(gpu["temperature.gpu"]),
                    powerDrawWatts=float(gpu["power.draw"]),
                    powerLimitWatts=float(gpu["power.limit"]),
                    coreClockMHz=float(gpu["clocks.current.graphics"]),
                    utilizationPercent=float(gpu["utilization.gpu"]),
                    memoryUsedMiB=float(gpu["memory.used"]),
                    memoryFreeMiB=float(gpu["memory.free"]),
                )
            except RunnerError as error:
                self.status.update(telemetryError=str(error))

    def _solo_telemetry_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                self.status.update(soloNode=get_solo_status())
            except Exception as error:
                self.status.update(soloNode={
                    "installed": False,
                    "state": "unavailable",
                    "detail": f"Solo status unavailable: {error}",
                    "gatewayReady": False,
                    "updatedAt": utc_now(),
                })
            if self.shutdown_event.wait(5):
                return


def start_status_server(
    status: MinerStatus,
    port: int,
    dashboard_root: Path,
    controller: MinerController | None,
) -> tuple[ThreadingHTTPServer, str]:
    session_token = secrets.token_urlsafe(32)
    static_root = dashboard_root.resolve()

    class Handler(BaseHTTPRequestHandler):
        def _host_allowed(self) -> bool:
            host = self.headers.get("Host", "")
            return host == "localhost" or host.startswith("localhost:") or host == "127.0.0.1" or host.startswith("127.0.0.1:")

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'",
            )

        def _json(self, payload: dict, status_code: int = 200) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            self.end_headers()
            self.wfile.write(encoded)

        def _serve_static(self) -> None:
            if not static_root.is_dir():
                self._json({
                    "error": "dashboard build is missing",
                    "action": "run npm run build",
                    "status": "/api/status",
                }, 503)
                return
            request_path = unquote(self.path.split("?", 1)[0])
            relative = "index.html" if request_path == "/" else request_path.lstrip("/")
            target = (static_root / relative).resolve()
            if static_root not in target.parents and target != static_root:
                self.send_error(404)
                return
            if not target.is_file():
                target = static_root / "index.html"
            if not target.is_file():
                self.send_error(404)
                return
            content = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header(
                "Cache-Control",
                "no-store" if target.name == "index.html" else "public, max-age=31536000, immutable",
            )
            self._security_headers()
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            if not self._host_allowed():
                self._json({"error": "invalid Host header"}, 403)
                return
            path = self.path.split("?", 1)[0]
            if path in {"/status", "/api/status"}:
                self._json(status.snapshot())
                return
            if path == "/api/session":
                self._json({"token": session_token})
                return
            if path == "/api/config":
                if controller is None:
                    self._json({"error": "interactive controls are unavailable"}, 409)
                else:
                    self._json(controller.public_config())
                return
            if path == "/api/health":
                self._json({"ok": True, "state": status.snapshot().get("state")})
                return
            self._serve_static()

        def do_POST(self) -> None:
            if not self._host_allowed():
                self._json({"error": "invalid Host header"}, 403)
                return
            supplied = self.headers.get("X-BlockHunter-Token", "")
            if not hmac.compare_digest(supplied, session_token):
                self._json({"error": "missing or invalid local session token"}, 403)
                return
            if controller is None:
                self._json({"error": "interactive controls are unavailable"}, 409)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 16384:
                    raise RunnerError("request body is too large")
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise RunnerError("request body must be a JSON object")
                path = self.path.split("?", 1)[0]
                if path == "/api/start":
                    result = controller.start(payload)
                elif path == "/api/stop":
                    result = controller.stop()
                elif path == "/api/probe":
                    result = controller.probe(payload)
                elif path == "/api/shutdown":
                    result = controller.shutdown()
                else:
                    self._json({"error": "not found"}, 404)
                    return
                self._json(result)
            except (RunnerError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
                self._json({"error": str(error)}, 400)

        def log_message(self, *_args) -> None:
            return

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        server.daemon_threads = True
    except OSError as error:
        raise RunnerError(f"cannot bind BlockHunter on 127.0.0.1:{port}: {error}") from error
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, session_token


def apply_cli_overrides(config: dict, args: argparse.Namespace) -> None:
    if args.mode:
        config["mode"] = args.mode
    if args.pool:
        config["pool"] = args.pool
    if args.solo_gateway:
        config["soloGateway"] = args.solo_gateway
    if args.wallet:
        config["wallet"] = args.wallet
    if args.worker:
        config["worker"] = args.worker


def print_preflight(gpu: dict, config: dict, manifest: dict) -> None:
    print("BlockHunter Pearl preflight")
    print(f"GPU:          {gpu['name']} (compute {gpu['compute_cap']})")
    print(f"Driver:       {gpu['driver_version']} (minimum {config['minimumDriver']})")
    print(f"CUDA build:   {manifest['cudaToolkit']} -> {manifest['cudaTarget']}")
    print(f"VRAM:         {gpu['memory.free']} MiB free; {config['vramReserveMiB']} MiB reserved")
    print(f"Target:       {config['powerLimitWatts']} W at {config['lockedCoreClockMHz']} MHz")
    print(f"Work region:  {config.get('region', 4096)} x {config.get('region', 4096)}")
    print("Memory clock: stock (offset 0 MHz)")
    print("Undervolt:    effective Ada V/F reduction via power cap + fixed core clock")
    print("Pearl:        certificate V3; reviewed source build; 2% upstream dev fee")


def main() -> int:
    parser = argparse.ArgumentParser(description="BlockHunter reviewed Pearl miner runner")
    parser.add_argument("--config", type=Path, default=Path("miner.local"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mine", action="store_true")
    mode.add_argument("--benchmark", action="store_true")
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--mode", choices=("pool", "solo"))
    parser.add_argument("--pool")
    parser.add_argument("--solo-gateway")
    parser.add_argument("--wallet")
    parser.add_argument("--worker")
    parser.add_argument("--benchmark-regions", type=int, default=64)
    parser.add_argument("--apply-tuning", action="store_true")
    parser.add_argument("--tuning-preapplied", action="store_true")
    parser.add_argument("--dashboard-root", type=Path, default=Path("dist"))
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path.home() / ".local" / "share" / "blockhunter-pearl",
    )
    args = parser.parse_args()

    if args.apply_tuning and args.tuning_preapplied:
        raise RunnerError("choose either --apply-tuning or --tuning-preapplied")
    if args.tuning_preapplied and not (args.mine or args.serve):
        raise RunnerError("--tuning-preapplied is only valid with --mine or --serve")

    signal.signal(signal.SIGTERM, handle_termination)
    config_path = args.config.expanduser().resolve()
    runtime_root = args.runtime_root.expanduser().resolve()
    dashboard_root = args.dashboard_root.expanduser().resolve()
    config = load_config(config_path)
    apply_cli_overrides(config, args)
    validate_config(config, mining=bool(args.mine))
    manifest = validate_runtime(runtime_root, config)
    nvidia_smi = find_nvidia_smi()
    gpu = preflight_gpu(nvidia_smi, config)
    print_preflight(gpu, config, manifest)

    tuning = TuningSession(nvidia_smi, config)
    server: ThreadingHTTPServer | None = None
    controller: MinerController | None = None
    try:
        if args.apply_tuning:
            tuning.apply()
            print("Tuning:       applied; original settings will be restored on exit")
        elif args.tuning_preapplied:
            if not 140 <= float(gpu["power.limit"]) <= 160:
                raise RunnerError(
                    f"pre-applied power limit is {gpu['power.limit']} W, outside 140-160 W")
            print("Tuning:       managed by the elevated Windows launcher")
        elif args.mine and bool(config["requirePowerAndClockTuning"]):
            if not 140 <= float(gpu["power.limit"]) <= 160:
                raise RunnerError(
                    f"reported power limit is {gpu['power.limit']} W; apply the 140-160 W profile")
            if not bool(config.get("manualClockLockConfirmed", False)):
                raise RunnerError(
                    "core-clock lock is not confirmed; use --apply-tuning or confirm a manual 2400-2550 MHz lock")

        if args.preflight_only or not (args.mine or args.benchmark or args.serve):
            print("Preflight:    PASS")
            return 0

        status = create_initial_status(config, manifest, gpu)
        if args.serve:
            tuning_ready = bool(
                args.apply_tuning
                or args.tuning_preapplied
                or config.get("manualClockLockConfirmed", False)
            )
            controller = MinerController(
                runtime_root,
                config,
                manifest,
                nvidia_smi,
                status,
                tuning_ready,
            )
            server, _token = start_status_server(
                status,
                int(config["apiPort"]),
                dashboard_root,
                controller,
            )
            print(f"Dashboard:    http://127.0.0.1:{config['apiPort']}")
            print("Controls:     localhost-only session; close with Stop & restore")
            try:
                while not controller.shutdown_event.wait(0.5):
                    pass
            except KeyboardInterrupt:
                controller.stop()
            finally:
                controller.wait_for_process()
            return 0

        server, _token = start_status_server(
            status,
            int(config["apiPort"]),
            dashboard_root,
            None,
        )
        benchmark_regions = args.benchmark_regions if args.benchmark else None
        if args.mine:
            validate_config(config, mining=True)
            endpoint_result = probe_endpoint(config)
            print(f"Endpoint:     {endpoint_result['detail']} ({endpoint_result['latencyMs']} ms)")
        status.reset_session(
            state="starting",
            startedAt=utc_now(),
            mode="benchmark" if args.benchmark else config.get("mode", "pool"),
        )
        return run_miner(runtime_root, config, nvidia_smi, benchmark_regions, status)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if tuning.active or tuning.original_power is not None:
            tuning.restore()
            print("Tuning:       restored")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RunnerError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"BlockHunter preflight failed: {error}", file=sys.stderr)
        raise SystemExit(2)
