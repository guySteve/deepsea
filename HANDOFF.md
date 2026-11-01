# Continue on another PC

Open the cloned repository folder to continue development. The dashboard source,
Python and PowerShell scripts, CUDA source patches, profiles, pinned runtime
manifest, and hourly review notes are included.

## Dashboard development

Install Node.js and run:

```bash
npm ci
npm run dev
```

Run `npm run build` to produce the dashboard used by the local mining console.

## Local configuration

Copy `miner.example.json` to `miner.local` and set your payout address and worker.
For the block-hunt launcher, also create `miner.block-hunt.local` using that
example with `profile` set to `miner/rtx4070-block-hunt.json` and `mode` set to
`solo`. These local files are intentionally ignored by Git.

## Mining runtime is separate

The compiled CUDA library, Python native extension, WSL runtime, node database,
and generated RPC credentials live outside this repository on the original PC.
Cloning alone does not transfer them. The existing runtime installer expects
prebuilt artifacts under `~/.cache/blockhunter-miner`; it is not a complete
fresh-machine build script. See `miner/BUILD.md` for the pinned sources and build
instructions, and `miner/runtime-manifest.json` for expected artifact hashes.
Rebuild or securely transfer the verified runtime artifacts before mining.

The supplied GPU profiles target an RTX 4070 / CUDA sm_89. Review compatibility
before using them on different hardware. Start with the README setup steps once
the runtime is available.

## Recent work

`diagnostics/hourly/latest.md` and `diagnostics/hourly/memory.md` record the latest
observations and next experiments. Raw telemetry, local configuration, dependencies,
and generated dashboard output are excluded from Git.
