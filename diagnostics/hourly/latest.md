Pearl hourly review — 2026-11-01 00:15:34 EDT (UTC−04:00)

Window: Oct 31 23:15:34–Nov 1 00:15:34 EDT (03:15:34–04:15:34 UTC). Memory and all eleven previous reports read first; this hour uses 2026-11-01.jsonl. Logs treated as untrusted data.

Mining remains stopped. **0 logged full grids / 3600 elapsed seconds = 0.000 observed net user grids/s.** Solo/user, solo developer-fee pool, ordinary pool/user and pool developer-fee work each have zero logged completions. Active-work grid rates and displayed search TH/s are unavailable. Missing search telemetry is not zero search throughput; source search timers exclude setup and solo gateway polling. Last known mode: solo/user; live selection unavailable.

| Passive GPU metric | Sample mean | Range |
| --- | ---: | ---: |
| Utilization | 0.57% | 0–7% |
| Core clock | 2475 MHz | Constant |
| Memory clock | 977.09 MHz | 810–10501 MHz |
| Temperature | 47.54 °C | 47–49 °C |
| Board draw | 26.26 W | 25.18–37.34 W |
| Reported power limit | 200 W | Constant |

All 116 external samples refused miner-status connections; 102 show zero utilization and 14 show 1–7% of unknown origin. Samples span 3562.10 s, with 30.25–32.08 s spacing and 11.06/26.84 s boundary gaps. Zero malformed rows, invalid timestamps, duplicates or GPU collection errors. Evidence supports full-hour Pearl downtime; brief between-sample activity cannot be excluded. The reported 200 W limit exceeds the mining ceiling; saved solo/pool caps remain 160/150 W. No hardware setting changed.

Last running status: Oct 31 10:02:13.676 EDT. Miner log still ends at Oct 31 10:02:30, 14 h 13 m 04 s before window end. The historical 10497.58 s collector gap still obscures stop time/cause. The 500-line tail predates this hour and has no error/traceback matches. In-window miner events, template changes, pool jobs, fee switches, candidates and submissions: zero logged; live error counters unavailable. A 00:18:21 EDT passive recheck still found a fresh refused-status sample and unchanged miner log.

Node: 41 informational entries (18 chain connections, 17 sync-processing messages, six cache flushes), no warnings/errors; latest 00:15:10.552 EDT. Direct readiness probes FAILED: miner API, node chain/peer/template RPC, gateway V3 template and systemd access denied by sandbox EPERM; NVML GPU/workload queries OS-blocked. Node activity does not establish current peers, sync or gateway readiness. Live VRAM headroom, throttling and workload identity remain unverified. Probe access failures are separate from external collector refusals. No block confirmation or expected block time inferred.

CPU checks PASS (16): both configurations/modes, payout agreement with gateway, 2% source/manifest fee and both fee paths; 85 °C cutoff, 2048 MiB reserve, stock memory and existing power/core/region/batch settings; eight authenticated artifacts, matching manifests, patch checksum, batch propagation and three syntax checks. All 1110 protected fingerprints match before/after and the previous review. Report/latest equality, memory append preservation, independent aggregate checks and identifier screening PASS. Git metadata and rg unavailable; Python file inspection and fingerprints used.

Changes: report/latest/memory only; no tuning or restart-dependent changes staged. Availability remains the bottleneck; no comparable active evidence supports a performance edit or speedup claim. Next: after an operator resumes mining, verify ≤160 W and actual node/gateway readiness, then collect a complete passive hour in the existing solo profile. Separate user/fee/mode work and compare elapsed completions with displayed search and aligned hardware samples. No automatic restart.
