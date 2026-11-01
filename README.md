# BlockHunter

BlockHunter is a local control and monitoring console for a reviewed, source-built Pearl GPU miner. It is tuned for an NVIDIA RTX 4070 and exposes pool or solo mining without hiding the distinction between a share candidate, a submitted block proof, and a network-confirmed block.

## What makes it different

- Runs the pinned Ada `sm_89` CUDA miner rather than the quarantined third-party Windows executable.
- Verifies every installed runtime artifact against its recorded SHA-256 hash before startup.
- Applies a reversible `150 W / 2475 MHz` RTX 4070 profile, with a separate capped `160 W / 2475 MHz` block-hunt launcher.
- Stops on temperature, power-limit, or desktop-VRAM guardrail violations.
- Reports live hashrate, watts, efficiency, clocks, temperature, VRAM, jobs, candidates, accepted shares, rejected shares, and proof errors.
- Shows a visual candidate radar without presenting pool shares as confirmed blocks.
- Supports LuckyPool V3 pool mining or solo mining through a local `pearl-gateway` TCP endpoint.
- Keeps control endpoints on `127.0.0.1` and requires a random same-origin session token for start, stop, probe, and shutdown actions.
- Exports a one-click JSON diagnostics report with the payout address shortened.
- Retains the upstream miner's disclosed 2% developer fee.

## Start the console

Build the dashboard once:

```bash
npm install
npm run build
```

Install and verify the reviewed WSL runtime:

```bash
bash scripts/install-pearl-runtime.sh
python3 scripts/pearl_runner.py --config miner.local --preflight-only
```

For local solo mining, install the pinned node and gateway once:

```bash
bash scripts/install-pearl-solo.sh
python3 scripts/pearl_solo.py status
```

The solo installer uses the payout address in `miner.local` unless an address is passed as its first argument. It verifies the official Pearl `v1.5.5` archive and pinned source revision, generates random RPC credentials, and creates persistent WSL user services.

Double-click `start-pearl-mining.cmd`. The launcher:

1. Requests Windows administrator approval.
2. Saves the current NVIDIA power limit.
3. Applies the reviewed RTX 4070 profile.
4. Starts the localhost BlockHunter service in WSL.
5. Opens `http://127.0.0.1:21550` in the default browser.
6. Restores the original power and clock settings after **Stop & restore** closes the service.

The miner does not begin hashing when the dashboard opens. Choose a mode, test the endpoint, and press **Start mining**.

For an opt-in solo block-hunt session, double-click `start-pearl-block-hunt.cmd`. It starts in solo mode with the separately capped `160 W / 2475 MHz` profile. It keeps the same `85 °C` cutoff, stock memory clock, `2048 MiB` desktop reserve, and automatic restoration on exit.

## Pool mining

Choose **Pool mining** and enter:

- A Pearl mainnet payout address beginning with `prl1p`.
- A worker name containing letters, numbers, dots, dashes, or underscores.
- A pool endpoint in `host:port` format.

The pinned miner currently implements **LuckyPool V3 plaintext Stratum**. Entering an arbitrary Stratum address does not make another pool protocol compatible. TLS Stratum is rejected rather than silently downgraded.

The reviewed default is:

```text
pearl-eu2.luckypool.io:3360
```

Pool radar hits are qualifying share proofs. The pool decides whether a submitted share also satisfies the current network block target, so BlockHunter does not label pool hits as confirmed blocks.

## Solo mining

Choose **Solo mining** and use the managed local endpoint:

```text
127.0.0.1:8337
```

BlockHunter starts the local services, displays node height, headers, peers, and sync progress, and waits without using the GPU until initial block download completes. Mining begins only after the synced gateway returns a valid Pearl V3 template.

Solo mode requires:

- A fully synced `pearld` full node.
- The pinned, source-installed `pearl-gateway` connected to that node.
- The reward address configured in the gateway.
- The gateway miner transport configured for TCP.

BlockHunter calls `getMiningInfo`, mines the returned template, and sends a qualifying `PlainProof` through `submitPlainProof`. The gateway is responsible for proof conversion and block submission. A **Potential block** event means a qualifying proof was found; **Block proof submitted** means the gateway accepted the RPC request. Final network acceptance remains external and must not be inferred from either event.

The retired Windows executable bundle is not used for solo mode. Do not restore the Defender-quarantined executable, disable Defender, or create an antivirus exclusion.

Manage the local services from WSL:

```bash
python3 scripts/pearl_solo.py status
python3 scripts/pearl_solo.py restart
python3 scripts/pearl_solo.py stop
```

Node RPC uses generated credentials over plaintext only on `127.0.0.1:44107`; neither RPC nor the gateway is exposed to the LAN. The full node remains active after the dashboard closes so it can finish syncing and stay current.

## Monitor semantics

| Metric | Meaning |
| --- | --- |
| Hashrate | Production kernel throughput parsed from the miner |
| Efficiency | Live TH/s divided by `nvidia-smi` board power |
| Share candidate | A tile that meets the pool share target |
| Accepted work | User-wallet shares accepted by the pool |
| Potential block | A solo tile that meets the gateway template target |
| Block proof submitted | `submitPlainProof` returned without an RPC error |
| Network confirmation | Not claimed by BlockHunter; confirm through the node or explorer |

The dashboard uses real session telemetry only. It does not synthesize candidate events or estimate a block win from pool difficulty.

## RTX 4070 guardrails

- Driver `550+` and compute capability `8.9` are mandatory.
- CUDA kernels are compiled for `sm_89` only with no PTX fallback.
- Mining requires a `140-160 W` power limit and `2400-2550 MHz` locked core.
- The default profile uses `150 W` and `2475 MHz`.
- The optional block-hunt profile uses `160 W` with the measured `2475 MHz` sweet spot; `2550 MHz` was slower under sustained power throttling. It does not alter voltage or memory clocks.
- A matched 60-grid production test measured `53.08 TH/s` effective at the block-hunt profile versus `50.86 TH/s` at the default profile, a `4.4%` gain on this card.
- Memory clock offset must remain `0 MHz`.
- `2048 MiB` VRAM remains reserved for Windows and DWM.
- Mining stops at `85 °C`, below the VRAM reserve, or outside the approved power-limit range.
- Large mining workspaces are allocated once at startup.
- The validated `8192 x 8192` work region improves sustained search throughput while preserving byte-for-byte proof results.
- The reviewed result queue is fixed at 16 regions to limit stale work.

## Other launch modes

Run the offline production-kernel benchmark without connecting or submitting:

```text
benchmark-pearl-mining.cmd
```

Start the opt-in solo block-hunt console:

```text
start-pearl-block-hunt.cmd
```

Start direct pool mining without the browser console:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-pearl-miner.ps1 -Direct -ApplyTuning
```

Inspect the active service from PowerShell:

```powershell
powershell -NoProfile -File scripts/check-pearl-miner.ps1
```

The compatibility status endpoint is `http://127.0.0.1:21550/status`; the dashboard uses `/api/status`.

## Configuration

`miner.local` is intentionally ignored. Its supported session defaults are:

```json
{
  "profile": "miner/rtx4070.json",
  "mode": "pool",
  "wallet": "prl1p...",
  "worker": "blockhunter",
  "pool": "pearl-eu2.luckypool.io:3360",
  "soloGateway": "127.0.0.1:8337",
  "tls": false,
  "manualClockLockConfirmed": false
}
```

Use `miner.example.json` as a template. Values entered in the dashboard apply to the current service session and do not overwrite `miner.local`.

## Build provenance

| Component | Pinned revision |
| --- | --- |
| Open Pearl Miner | `ac3d992d7eb6ca1bb344d5d3ee125eecb182248d` |
| Official Pearl | `d7c517d267f10f5bcbbdc366f3e603942f9a5ab5` |
| NVIDIA CUTLASS | `291300ffffa3533a78ee104f08a8490a29ce9ccb` |

Artifact hashes and CUDA package versions are in `miner/runtime-manifest.json`. Reviewed source changes are in `patches/open-pearl-miner-v3-sm89.patch`; build and validation details are in `miner/BUILD.md`.

## Project layout

```text
src/App.tsx                       Mining control and telemetry dashboard
src/styles.css                    Responsive visual system
scripts/pearl_runner.py           Local control API, guardrails, and process runner
scripts/pearl_solo.py             Node/gateway lifecycle and sync telemetry
scripts/install-pearl-solo.sh     Verified node, gateway, and user-service installer
scripts/start-pearl-miner.ps1     Elevated Windows lifecycle and tuning restoration
miner/rtx4070.json                Hardware safety profile
miner/rtx4070-block-hunt.json     Capped opt-in block-hunt profile
miner/runtime-manifest.json       Runtime provenance and artifact hashes
patches/open-pearl-miner-v3-sm89.patch
patches/pearl-gateway-torch-optional.patch
```
