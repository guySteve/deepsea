#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any


DEFAULT_ROOT = Path(os.environ.get(
    "BLOCKHUNTER_SOLO_ROOT",
    Path.home() / ".local" / "share" / "blockhunter-pearl-solo",
))
NODE_SERVICE = "blockhunter-pearld.service"
GATEWAY_SERVICE = "blockhunter-pearl-gateway.service"
MANAGED_HOSTS = {"127.0.0.1", "localhost"}
MANAGED_PORT = 8337


class SoloServiceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_managed_endpoint(endpoint: str) -> bool:
    try:
        host, port_text = endpoint.rsplit(":", 1)
        return host.lower() in MANAGED_HOSTS and int(port_text) == MANAGED_PORT
    except (ValueError, AttributeError):
        return False


def _unit_path(service: str) -> Path:
    return Path.home() / ".config" / "systemd" / "user" / service


def is_installed(root: Path = DEFAULT_ROOT) -> bool:
    required = (
        root / "bin" / "pearld",
        root / "config" / "pearld.conf",
        root / "config" / "gateway.env",
        root / "app" / "pearl_gateway" / "cli.py",
        _unit_path(NODE_SERVICE),
        _unit_path(GATEWAY_SERVICE),
    )
    return all(path.is_file() for path in required)


def _service_state(service: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            text=True,
            capture_output=True,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return result.stdout.strip() or "inactive"


def _read_node_config(root: Path) -> dict[str, str]:
    config_path = root / "config" / "pearld.conf"
    values: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    for required in ("rpcuser", "rpcpass"):
        if not values.get(required):
            raise SoloServiceError(f"Pearl node config is missing {required}")
    return values


def _rpc_call(root: Path, method: str) -> Any:
    config = _read_node_config(root)
    token = base64.b64encode(
        f"{config['rpcuser']}:{config['rpcpass']}".encode("utf-8")
    ).decode("ascii")
    payload = json.dumps({
        "jsonrpc": "1.0",
        "id": "blockhunter-status",
        "method": method,
        "params": [],
    })
    connection = http.client.HTTPConnection("127.0.0.1", 44107, timeout=3)
    try:
        connection.request(
            "POST",
            "/",
            body=payload,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()
    if response.status != 200:
        raise SoloServiceError(f"Pearl RPC returned HTTP {response.status}")
    if body.get("error") is not None:
        raise SoloServiceError(f"Pearl RPC {method} failed: {body['error']}")
    return body.get("result")


def _gateway_ready() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", MANAGED_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def get_status(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    installed = is_installed(root)
    node_service = _service_state(NODE_SERVICE) if installed else "not-installed"
    gateway_service = _service_state(GATEWAY_SERVICE) if installed else "not-installed"
    gateway_ready = _gateway_ready() if installed else False
    result: dict[str, Any] = {
        "installed": installed,
        "state": "not-installed",
        "detail": "Install the local solo runtime first",
        "nodeService": node_service,
        "gatewayService": gateway_service,
        "nodeRpcReady": False,
        "gatewayReady": gateway_ready,
        "blocks": None,
        "headers": None,
        "networkHeight": None,
        "syncPercent": None,
        "initialBlockDownload": None,
        "peers": 0,
        "updatedAt": utc_now(),
    }
    if not installed:
        return result
    if node_service not in {"active", "activating"}:
        result.update(state="stopped", detail="Local Pearl node service is stopped")
        return result
    try:
        chain = _rpc_call(root, "getblockchaininfo")
        peers = _rpc_call(root, "getpeerinfo")
    except Exception as error:
        result.update(
            state="starting",
            detail="Pearl node is starting its RPC service",
            rpcError=f"{type(error).__name__}: {error}",
        )
        return result
    blocks = int(chain.get("blocks", 0))
    headers = int(chain.get("headers", blocks))
    peer_heights = [
        int(peer["currentheight"])
        for peer in peers
        if isinstance(peer, dict) and isinstance(peer.get("currentheight"), int)
    ]
    network_height = max(peer_heights, default=headers)
    initial_download = bool(chain.get("initialblockdownload", True))
    # Pearl 1.5.5 omits Bitcoin's initialblockdownload field. Its template
    # RPC checks chain readiness, so require a usable template as the fallback.
    if "initialblockdownload" not in chain and blocks > 0 and blocks >= max(headers, network_height):
        try:
            template = _rpc_call(root, "getblocktemplate")
            initial_download = not (
                isinstance(template, dict) and template.get("height") == blocks + 1
            )
        except Exception:
            initial_download = True
    progress_height = max(blocks, headers, network_height)
    height_progress = blocks / progress_height if progress_height > 0 else 0.0
    raw_progress = chain.get("verificationprogress")
    if initial_download or progress_height > blocks or raw_progress is None:
        progress = height_progress
    else:
        progress = float(raw_progress)
    progress = max(0.0, min(1.0, progress))
    peer_count = len(peers) if isinstance(peers, list) else 0
    result.update(
        nodeRpcReady=True,
        blocks=blocks,
        headers=headers,
        networkHeight=network_height,
        syncPercent=round(progress * 100, 3),
        initialBlockDownload=initial_download,
        peers=peer_count,
    )
    if peer_count == 0:
        result.update(state="waiting-peers", detail="Pearl node is searching for mainnet peers")
    elif initial_download or progress < 0.99999:
        result.update(
            state="syncing",
            detail=(
                f"Pearl node sync is {progress * 100:.3f}% "
                f"({blocks}/{network_height} blocks) with {peer_count} peers"
            ),
        )
    elif gateway_ready:
        result.update(
            state="ready",
            detail=f"Synced solo gateway ready at 127.0.0.1:{MANAGED_PORT}",
        )
    elif gateway_service in {"active", "activating"}:
        result.update(state="starting-gateway", detail="Chain is synced; gateway is starting")
    else:
        result.update(state="gateway-error", detail="Chain is synced but the gateway is not active")
    return result


def _systemctl(action: str, services: list[str]) -> None:
    result = subprocess.run(
        ["systemctl", "--user", action, *services],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise SoloServiceError(f"Unable to {action} local Pearl services: {detail}")


def start_services(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    if not is_installed(root):
        raise SoloServiceError(
            "local solo runtime is not installed; run scripts/install-pearl-solo.sh"
        )
    _systemctl("start", [NODE_SERVICE, GATEWAY_SERVICE])
    return get_status(root)


def stop_services(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    if not is_installed(root):
        return get_status(root)
    _systemctl("stop", [GATEWAY_SERVICE, NODE_SERVICE])
    return get_status(root)


def restart_services(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    if not is_installed(root):
        raise SoloServiceError(
            "local solo runtime is not installed; run scripts/install-pearl-solo.sh"
        )
    _systemctl("restart", [NODE_SERVICE, GATEWAY_SERVICE])
    return get_status(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage BlockHunter's local Pearl solo services")
    parser.add_argument("command", choices=("status", "start", "stop", "restart"), nargs="?", default="status")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.command == "start":
            status = start_services(arguments.root)
        elif arguments.command == "stop":
            status = stop_services(arguments.root)
        elif arguments.command == "restart":
            status = restart_services(arguments.root)
        else:
            status = get_status(arguments.root)
    except SoloServiceError as error:
        print(str(error), file=sys.stderr)
        return 1
    if arguments.json:
        print(json.dumps(status, indent=2))
    else:
        print(f"Pearl solo: {status['state']} — {status['detail']}")
        if status.get("blocks") is not None:
            print(
                f"Chain: {status['blocks']} blocks / {status['headers']} headers · "
                f"{status['syncPercent']}% · {status['peers']} peers"
            )
        print(
            f"Services: node={status['nodeService']} gateway={status['gatewayService']} · "
            f"TCP 8337 listener={'up' if status['gatewayReady'] else 'waiting'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
