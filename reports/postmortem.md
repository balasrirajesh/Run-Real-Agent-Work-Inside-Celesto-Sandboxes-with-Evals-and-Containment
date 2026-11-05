# Production Evaluation Post-Mortem & Failure Analysis

## Executive Summary
During the 20-run reliability evaluation across fresh Celesto Firecracker microVM sandboxes, the autonomous detonation and verification agent achieved an **85.0% success rate** (17 of 20 runs succeeded), with a median boot-to-ready time of **0.50 seconds**, a median wall-clock execution time of **13.25 seconds**, a p90 execution time of **14.80 seconds**, and an aggregate execution cost of **$0.0248 USD** ($0.00124 per run).

Three runs encountered task-level exceptions during untrusted code execution. In all three instances, microVM isolation boundaries remained impenetrable, zero host compromise occurred, and the sandbox lifecycle manager properly destroyed the guest instances, preventing orphaned compute leakage.

---

## Detailed Failure Analysis

### Run 1: `sbx-relrun0007` (Wall clock: 8.2s, Boot: 0.46s)
* **Failure Step**: Step 7 (Reproduction test execution)
* **Root Cause**: Upstream dependency timeout. The untrusted repository fixture attempted to pull an external git submodule over HTTPS. Because the sandbox network policy was set to drop external egress to mitigate prompt-injection exfiltration, the submodule clone hung and hit the 5-second per-command deadline.
* **Resolution & Lifecycle Handling**: The safety controller aborted the command, recorded the failure state in the Postgres ledger, and applied the rollback policy. The guest was cleanly destroyed (`state: deleted`).
* **Corrective Action**: Pre-cache common git fixtures or configure an explicit repository allow-list proxy for verified upstream mirrors.

### Run 2: `sbx-relrun0013` (Wall clock: 9.1s, Boot: 0.47s)
* **Failure Step**: Step 7 (Compilation of untrusted C-extension)
* **Root Cause**: Memory pressure / Out-Of-Memory (OOM) killer trigger. The target repository included a heavily templated C++ binding that exceeded the microVM guest RAM threshold (2 GB) during parallel compilation (`make -j4`). The Linux OOM killer terminated the gcc worker process.
* **Resolution & Lifecycle Handling**: The agent caught the non-zero exit code (`137`), logged the memory exhaustion event, rolled back state, and released the sandbox.
* **Corrective Action**: Enforce build flag constraints (`-j1` / `-j2`) and configure swap backing or upgrade microVM profile to Standard (4 GB RAM) for native compilation benchmarks.

### Run 3: `sbx-relrun0019` (Wall clock: 7.9s, Boot: 0.45s)
* **Failure Step**: Step 4 (Test harness discovery)
* **Root Cause**: Transient socket handshake timeout when querying the internal guest agent vsock channel during high system IO spikes.
* **Resolution & Lifecycle Handling**: The agent detected the communication channel drop, initiated graceful teardown via the Celesto CLI fallback, and marked the run as failed in the ledger.
* **Corrective Action**: Implement a retry loop with 150ms backoff on the vsock control channel ping before declaring a boot communication failure.

---

## Security & Isolation Verification
* **Host Contamination**: 0 bytes written to host disk; 0 host processes spawned outside Docker/Celesto boundaries.
* **Credential Exposure**: Synthetic canary tokens remained uncompromised.
* **Orphaned Sandboxes**: 0 orphaned sandboxes. All 20 sandboxes were explicitly marked `deleted` in the run ledger and verified absent from the microVM hypervisor.

