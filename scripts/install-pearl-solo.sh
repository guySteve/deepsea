#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
SOLO_ROOT=${BLOCKHUNTER_SOLO_ROOT:-"$HOME/.local/share/blockhunter-pearl-solo"}
MINER_RUNTIME=${BLOCKHUNTER_RUNTIME_ROOT:-"$HOME/.local/share/blockhunter-pearl"}
CACHE_ROOT=${BLOCKHUNTER_BUILD_CACHE:-"$HOME/.cache/blockhunter-miner"}
PEARL_SOURCE="$CACHE_ROOT/sources/pearl-d7c517d"
PEARL_COMMIT=d7c517d267f10f5bcbbdc366f3e603942f9a5ab5
PEARL_VERSION=v1.5.5
PEARL_ARCHIVE="pearl-linux-amd64-$PEARL_VERSION.tar.gz"
PEARL_ARCHIVE_SHA256=dfc545ec64b4109a86748ebd924469c2a744184a8e783673c9f862671769bd19
UV_VERSION=0.11.1
UV_ARCHIVE=uv-x86_64-unknown-linux-gnu.tar.gz
UV_ARCHIVE_SHA256=7c0c8069053e6e99e5911ff32b916be571f3419cd8e11bd28fb7da2c7dcaa553
GATEWAY_PATCH="$PROJECT_ROOT/patches/pearl-gateway-torch-optional.patch"

for command in curl git python3 sha256sum systemctl tar; do
  command -v "$command" >/dev/null || { echo "missing required command: $command" >&2; exit 1; }
done

MINING_ADDRESS=${1:-${BLOCKHUNTER_MINING_ADDRESS:-}}
if [[ -z "$MINING_ADDRESS" && -f "$PROJECT_ROOT/miner.local" ]]; then
  MINING_ADDRESS=$(python3 - "$PROJECT_ROOT/miner.local" <<'PY'
import json, pathlib, sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")).get("wallet", ""))
PY
)
fi
python3 - "$MINING_ADDRESS" <<'PY'
import re, sys
if not re.fullmatch(r"prl1p[023456789acdefghjklmnpqrstuvwxyz]{58}", sys.argv[1]):
    raise SystemExit("a valid Pearl mainnet prl1p mining address is required")
PY

mkdir -p \
  "$CACHE_ROOT/releases/$PEARL_VERSION/staging" \
  "$CACHE_ROOT/tools/uv-$UV_VERSION" \
  "$SOLO_ROOT/app" \
  "$SOLO_ROOT/bin" \
  "$SOLO_ROOT/config" \
  "$SOLO_ROOT/logs/node" \
  "$SOLO_ROOT/node/data" \
  "$SOLO_ROOT/site" \
  "$SOLO_ROOT/tools" \
  "$HOME/.config/systemd/user"

if [[ ! -d "$PEARL_SOURCE/.git" ]]; then
  git clone --filter=blob:none https://github.com/pearl-research-labs/pearl.git "$PEARL_SOURCE"
  git -C "$PEARL_SOURCE" checkout --detach "$PEARL_COMMIT"
fi
test "$(git -C "$PEARL_SOURCE" rev-parse HEAD)" = "$PEARL_COMMIT"

PEARL_CACHE="$CACHE_ROOT/releases/$PEARL_VERSION"
PEARL_URL="https://github.com/pearl-research-labs/pearl/releases/download/$PEARL_VERSION"
if [[ ! -s "$PEARL_CACHE/checksums.txt" ]]; then
  curl -fL --retry 3 "$PEARL_URL/checksums.txt" -o "$PEARL_CACHE/checksums.txt"
fi
if [[ ! -s "$PEARL_CACHE/$PEARL_ARCHIVE" ]]; then
  curl -fL --retry 3 "$PEARL_URL/$PEARL_ARCHIVE" -o "$PEARL_CACHE/$PEARL_ARCHIVE"
fi
RELEASE_SHA=$(awk -v file="$PEARL_ARCHIVE" '$2 == file || $2 == "*" file {print $1}' "$PEARL_CACHE/checksums.txt")
ACTUAL_PEARL_SHA=$(sha256sum "$PEARL_CACHE/$PEARL_ARCHIVE" | awk '{print $1}')
test "$RELEASE_SHA" = "$PEARL_ARCHIVE_SHA256"
test "$ACTUAL_PEARL_SHA" = "$PEARL_ARCHIVE_SHA256"
tar -xzf "$PEARL_CACHE/$PEARL_ARCHIVE" -C "$PEARL_CACHE/staging"
for binary in pearld prlctl; do
  source_binary=$(find "$PEARL_CACHE/staging" -type f -name "$binary" -print -quit)
  test -n "$source_binary"
  install -m 0755 "$source_binary" "$SOLO_ROOT/bin/$binary"
done
test "$("$SOLO_ROOT/bin/pearld" --version | awk '{print $3}')" = "1.5.5+d7c517d"

UV_CACHE="$CACHE_ROOT/tools/uv-$UV_VERSION"
UV_URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"
if [[ ! -s "$UV_CACHE/$UV_ARCHIVE" ]]; then
  curl -fL --retry 3 "$UV_URL/$UV_ARCHIVE" -o "$UV_CACHE/$UV_ARCHIVE"
fi
test "$(sha256sum "$UV_CACHE/$UV_ARCHIVE" | awk '{print $1}')" = "$UV_ARCHIVE_SHA256"
tar -xzf "$UV_CACHE/$UV_ARCHIVE" -C "$UV_CACHE"
UV_BINARY=$(find "$UV_CACHE" -type f -name uv -perm -u+x -print -quit)
test -n "$UV_BINARY"
install -m 0755 "$UV_BINARY" "$SOLO_ROOT/tools/uv"

test -f "$MINER_RUNTIME/site/pearl_mining.so"
cp -a "$MINER_RUNTIME/site/." "$SOLO_ROOT/site/"
"$SOLO_ROOT/tools/uv" pip install --python python3 --target "$SOLO_ROOT/site" \
  aiohttp==3.13.4 \
  fastjsonschema==2.21.2 \
  loguru==0.7.3 \
  prometheus-client==0.24.1 \
  pybase64==1.4.3 \
  pydantic==2.12.5 \
  pydantic-settings==2.13.1 \
  pyyaml==6.0.3
"$SOLO_ROOT/tools/uv" pip install --python python3 --target "$SOLO_ROOT/site" --no-deps bitcoin-utils==0.7.3
"$SOLO_ROOT/tools/uv" pip install --python python3 --target "$SOLO_ROOT/site" ecdsa==0.19.1

cp -a "$PEARL_SOURCE/miner/pearl-gateway/src/pearl_gateway" "$SOLO_ROOT/app/"
cp -a "$PEARL_SOURCE/miner/miner-utils/src/miner_utils" "$SOLO_ROOT/app/"
if (cd "$SOLO_ROOT/app" && git apply --check "$GATEWAY_PATCH" 2>/dev/null); then
  (cd "$SOLO_ROOT/app" && git apply "$GATEWAY_PATCH")
elif ! (cd "$SOLO_ROOT/app" && git apply --reverse --check "$GATEWAY_PATCH" 2>/dev/null); then
  echo "installed gateway source does not match the reviewed compatibility patch" >&2
  exit 1
fi

python3 - "$SOLO_ROOT/config/pearld.conf" "$SOLO_ROOT" "$MINING_ADDRESS" <<'PY'
import pathlib, secrets, sys
path = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
address = sys.argv[3]
existing = {}
if path.is_file():
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            existing[key.strip()] = value.strip()
password = existing.get("rpcpass") or secrets.token_urlsafe(48)
username = existing.get("rpcuser") or "blockhunter"
path.write_text(f'''# BlockHunter Pearl mainnet node; RPC is localhost-only.
rpcuser={username}
rpcpass={password}
rpclisten=127.0.0.1:44107
notls=1
miningaddr={address}
datadir={root / "node" / "data"}
logdir={root / "logs" / "node"}
nolisten=1
maxpeers=32
nocfilters=1
utxocachemaxsize=2048
''', encoding="utf-8")
path.chmod(0o600)
PY

python3 - "$SOLO_ROOT/config/pearld.conf" "$SOLO_ROOT/config/gateway.env" "$MINING_ADDRESS" <<'PY'
import pathlib, sys
node_path = pathlib.Path(sys.argv[1])
environment_path = pathlib.Path(sys.argv[2])
address = sys.argv[3]
config = {}
for line in node_path.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()
environment_path.write_text(f'''PEARLD_RPC_URL=http://127.0.0.1:44107
PEARLD_RPC_USER={config["rpcuser"]}
PEARLD_RPC_PASSWORD={config["rpcpass"]}
PEARLD_MINING_ADDRESS={address}
PEARLD_REFRESH_INTERVAL_SECONDS=1
MINER_RPC_TRANSPORT=tcp
MINER_RPC_HOST=127.0.0.1
MINER_RPC_PORT=8337
PEARL_LOG_LEVEL=INFO
PYTHONUNBUFFERED=1
''', encoding="utf-8")
environment_path.chmod(0o600)
PY

cat >"$HOME/.config/systemd/user/blockhunter-pearld.service" <<EOF
[Unit]
Description=BlockHunter Pearl v1.5.5 full node
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
Environment=GOGC=200
ExecStart=$SOLO_ROOT/bin/pearld -C $SOLO_ROOT/config/pearld.conf
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=120
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF

cat >"$HOME/.config/systemd/user/blockhunter-pearl-gateway.service" <<EOF
[Unit]
Description=BlockHunter Pearl solo mining gateway
Requires=blockhunter-pearld.service
After=blockhunter-pearld.service

[Service]
Type=simple
EnvironmentFile=$SOLO_ROOT/config/gateway.env
Environment=PYTHONPATH=$SOLO_ROOT/site:$SOLO_ROOT/app
ExecStart=/usr/bin/python3 -m pearl_gateway.cli start
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF

PYTHONPATH="$SOLO_ROOT/site:$SOLO_ROOT/app" python3 - <<'PY'
from bitcoinutils.transactions import Transaction
import pearl_gateway.cli
import pearl_mining
print("Pearl gateway imports: verified")
PY

python3 - "$SOLO_ROOT" "$PEARL_COMMIT" "$PEARL_ARCHIVE_SHA256" "$UV_VERSION" "$UV_ARCHIVE_SHA256" "$GATEWAY_PATCH" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
patch = pathlib.Path(sys.argv[6])
artifacts = {}
for relative in ("bin/pearld", "bin/prlctl", "site/pearl_mining.so"):
    path = root / relative
    artifacts[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
manifest = {
    "schemaVersion": 1,
    "pearlCommit": sys.argv[2],
    "pearlReleaseArchiveSha256": sys.argv[3],
    "uvVersion": sys.argv[4],
    "uvArchiveSha256": sys.argv[5],
    "gatewayPatchSha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
    "artifacts": artifacts,
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

systemctl --user daemon-reload
systemctl --user enable --now blockhunter-pearld.service blockhunter-pearl-gateway.service
echo "Installed verified Pearl solo services at $SOLO_ROOT"
python3 "$PROJECT_ROOT/scripts/pearl_solo.py" status
