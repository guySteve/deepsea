#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
CACHE_ROOT=${BLOCKHUNTER_BUILD_CACHE:-"$HOME/.cache/blockhunter-miner"}
RUNTIME_ROOT=${BLOCKHUNTER_RUNTIME_ROOT:-"$HOME/.local/share/blockhunter-pearl"}
MINER_SOURCE=${BLOCKHUNTER_MINER_SOURCE:-"$CACHE_ROOT/sources/open-pearl-miner-v3"}
CUDA_LIBRARY="$CACHE_ROOT/miner-build-cuda129-sm89-v1/libp40cuda.so"
PYTHON_SITE="$CACHE_ROOT/python-site-v1"
MINER_COMMIT=ac3d992d7eb6ca1bb344d5d3ee125eecb182248d
MINER_PATCH="$PROJECT_ROOT/patches/open-pearl-miner-v3-sm89.patch"

if [ ! -d "$MINER_SOURCE/.git" ]; then
  mkdir -p "$(dirname "$MINER_SOURCE")"
  git clone --filter=blob:none https://github.com/Muskwak/Open-Pearl-Miner.git "$MINER_SOURCE"
  git -C "$MINER_SOURCE" checkout --detach "$MINER_COMMIT"
fi

test "$(git -C "$MINER_SOURCE" rev-parse HEAD)" = "$MINER_COMMIT"
if git -C "$MINER_SOURCE" apply --check "$MINER_PATCH" 2>/dev/null; then
  git -C "$MINER_SOURCE" apply "$MINER_PATCH"
elif ! git -C "$MINER_SOURCE" apply --reverse --check "$MINER_PATCH" 2>/dev/null; then
  echo "pinned miner source does not match the reviewed patch" >&2
  exit 1
fi

test -d "$MINER_SOURCE/python"
test -f "$MINER_SOURCE/LICENSE"
test -f "$CUDA_LIBRARY"
test -f "$PYTHON_SITE/pearl_mining.so"

mkdir -p "$RUNTIME_ROOT/app" "$RUNTIME_ROOT/site" "$RUNTIME_ROOT/logs"
cp "$MINER_SOURCE"/python/*.py "$RUNTIME_ROOT/app/"
cp "$CUDA_LIBRARY" "$RUNTIME_ROOT/app/libp40cuda.so"
cp -a "$PYTHON_SITE/." "$RUNTIME_ROOT/site/"
cp "$MINER_SOURCE/LICENSE" "$RUNTIME_ROOT/LICENSE.open-pearl-miner"
cp "$PROJECT_ROOT/miner/runtime-manifest.json" "$RUNTIME_ROOT/manifest.json"

python3 - "$RUNTIME_ROOT" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
for relative, expected in manifest["artifacts"].items():
    digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    if digest != expected["sha256"]:
        raise SystemExit(f"artifact checksum mismatch: {relative}")
print(f"installed reviewed Pearl runtime at {root}")
PY

PYTHONPATH="$RUNTIME_ROOT/site:$RUNTIME_ROOT/app" \
LD_LIBRARY_PATH="/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
python3 - <<'PY'
import cuda_capi
import pearl_mining
print(f"CUDA devices: {cuda_capi.device_count()}")
print("Pearl V3 verifier: available")
PY
