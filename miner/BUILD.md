# Reviewed Pearl miner build

BlockHunter uses a locally compiled fork of the open-source miner rather than the executable that Windows Defender quarantined. Do not restore the quarantined executable, disable Defender, or add an antivirus exclusion.

## Pinned sources

| Component | Commit |
| --- | --- |
| `Muskwak/Open-Pearl-Miner` | `ac3d992d7eb6ca1bb344d5d3ee125eecb182248d` |
| `pearl-research-labs/pearl` | `d7c517d267f10f5bcbbdc366f3e603942f9a5ab5` |
| `NVIDIA/cutlass` | `291300ffffa3533a78ee104f08a8490a29ce9ccb` |

The reviewed changes are recorded in `patches/open-pearl-miner-v3-sm89.patch`. They add Pearl certificate V3 salted seed derivation, propagate pool and solo gateway certificate versions, fail closed on unsupported versions, add an offline no-submit benchmark, preallocate commitment scratch storage, and add asynchronous low-latency pool notifications.

## CUDA build

- NVIDIA CUDA Toolkit `12.9.86`
- Ada-only code generation: `-gencode arch=compute_89,code=sm_89`
- Minimum runtime driver: `550.0`
- CUTLASS int8 Tensor Core path with emitted `IMMA.16832.S8.S8` instructions
- No PTX fallback and no other GPU architecture embedded

The official NVIDIA Ubuntu 24.04 CUDA repository package hashes and final artifact hashes are pinned in `miner/runtime-manifest.json`.

Apply the patch and build the CUDA library from the pinned miner checkout with:

```bash
git apply /path/to/deepsea/patches/open-pearl-miner-v3-sm89.patch
GENCODE='-gencode arch=compute_89,code=sm_89' \
CUTLASS_DIR=/path/to/cutlass/include \
NVCC=/path/to/cuda-12.9/bin/nvcc \
EXTRA_NVCC_FLAGS='-ccbin=/path/to/g++' \
bash packaging/build_capi.sh
```

Build `py-pearl-mining` from the pinned official Pearl checkout with Cargo and expose the resulting `libpearl_mining.so` as `pearl_mining.so` on Python's module path.

## BlockHunter control plane

`scripts/pearl_runner.py --serve` exposes the built dashboard and control API on `127.0.0.1:21550`. Mutating requests require a random in-memory session token obtained by the same-origin dashboard. The service accepts either:

- LuckyPool V3 plaintext Stratum pool configuration (`wallet`, `worker`, and `host:port`).
- Pearl solo gateway configuration (`pearl-gateway` JSON-RPC over TCP using `getMiningInfo` and `submitPlainProof`).

Pool endpoints receive a TCP reachability probe before the miner starts. Solo endpoints must return a valid mining template from `getMiningInfo`. The service records jobs, share candidates, block candidates, accepted and rejected shares, submitted block proofs, proof errors, and hardware telemetry. It does not infer a network-confirmed block from a candidate or successful gateway RPC call.

`scripts/install-pearl-solo.sh` verifies the official Pearl `v1.5.5+d7c517d` Linux archive against both the release checksum and BlockHunter's pinned SHA-256. It installs `pearld`, copies the pinned gateway source, applies `patches/pearl-gateway-torch-optional.patch`, generates localhost-only RPC credentials, and enables WSL user services. The compatibility patch defers the gateway's unused PyTorch type import; proof generation still uses the pinned official `pearl_mining` extension.

Managed solo mode gates mining on `initialblockdownload=false`, a valid gateway response, and certificate version V3. A TCP listener alone is never treated as sufficient readiness.

The elevated Windows launcher owns the GPU tuning lifecycle while the service is open. The browser can terminate the miner without closing the service, or use **Stop & restore** to terminate the service and let the launcher restore the original power and clock settings.

## Local validation record

- CUDA 12.9 V3 GPU commitment matches Pearl's official pinned seed vector.
- Complete offline V3 plain proof verifies successfully.
- A 64-region offline RTX 4070 run completes without networking or share submission.
- In short offline sweeps at `150 W / 2475 MHz`, an `8192` region reaches `55.25 TH/s` search throughput versus the prior `52.37 TH/s` baseline; one complete setup-plus-search cycle measured `53.61 TH/s` effective throughput.
- Every digest from one `8192 x 8192` region matches the corresponding four `4096 x 4096` quadrant runs byte-for-byte.
- Short result-batch sweeps of 16, 32, and 64 regions all remain near `55.2 TH/s` with the `8192` region; the profile keeps 16 to bound candidate visibility and stale work.
- Matched sustained 60-grid production loops measured `50.86 TH/s` effective at `150 W / 2475 MHz` and `53.08 TH/s` at `160 W / 2475 MHz`, a `4.4%` block-hunt gain after matrix setup overhead.
- The `160 W / 2475 MHz` loop ended at `74 °C`; an earlier 55-second soak peaked at `70 °C`, retained more than `8 GiB` free VRAM, and completed every grid. The runtime cutoff remains `85 °C`.
- `160 W / 2550 MHz` was rejected as the default block-hunt setting because the higher voltage point power-throttled as low as `2415 MHz` and did not improve sustained effective throughput.
- A local concurrent notify/submit test and a read-only LuckyPool V3 handshake pass with `TCP_NODELAY`; no `mining.submit` was sent.
- The local gateway round-trips `cert_version` through the official `submitPlainProof` schema; the unsynced height-1 V1 template is rejected before GPU launch.
- The dashboard API enters cancellable `syncing` state while the node performs initial block download and does not spawn a miner process.
- `cuobjdump --list-elf` reports only `sm_89` cubins.
- The source miner retains its disclosed 2% developer fee.

No live share has been submitted during validation. The first pool session should remain supervised until accepted shares and temperatures are confirmed.
