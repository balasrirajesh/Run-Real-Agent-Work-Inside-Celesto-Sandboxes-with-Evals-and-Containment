# Celesto MicroVM Autonomous Agent & Run Ledger

[![CI / Evaluation](https://img.shields.io/badge/Celesto-MicroVM%20Sandboxes-blue.svg)](https://celesto.ai)
[![Ledger Status](https://img.shields.io/badge/Ledger-Postgres%20Audit-success.svg)](#)
[![Containment Defense](https://img.shields.io/badge/Security-Safety%20Hooks%20%26%20Zero%20Egress-red.svg)](#)

A production-grade autonomous agent and control plane that isolates and audits dangerous agent tool executions (code evaluation, package detonation, and exploit reproduction) inside hardware-isolated **Celesto Firecracker microVMs**.

---

## Architecture Diagram

The system operates across two strictly segregated trust zones: a trusted host control plane (FastAPI API + PostgreSQL run ledger) and untrusted execution zones (Celesto microVM sandboxes).

```mermaid
flowchart TD
    subgraph TrustedControlPlane["Trusted Control Plane (Docker / Host)"]
        Operator["Operator / Evaluator"] -->|HTTP / REST| API["Run Ledger API (:8080)"]
        API -->|Audit Records| DB[(PostgreSQL Ledger)]
        API -->|Command Inspection| SafetyHook["Pre-Exec Safety Hooks"]
        SafetyHook -->|Audit Stream| CmdLog["logs/commands.jsonl"]
        Env[".env.example Config"] -.-> API
    end

    subgraph UntrustedComputers["Untrusted Execution Zone (Celesto MicroVMs)"]
        API -->|SDK / CLI Channel| GuestVM["Celesto MicroVM Guest (sbx-*)"]
        GuestVM -->|Checkpoint & Restore| Snapshots["MicroVM Memory & Disk Snapshots"]
        GuestVM -->|Outbound Filter| NetPolicy["Zero-Egress Network Policy"]
        GuestVM -->|Executes| Work["Untrusted Code / Pip / Pytest"]
    end

    SafetyHook -- Intercept & Block --> GuestVM
    Work -- Status & Proof Output --> API
```

---

## Problem statement

**Who has this problem**: Security engineers, DevSecOps teams, and AI safety researchers tasked with auditing untrusted dependency upgrades, automated GitHub issues, and PR submissions.

**What the agent does on a computer**: The agent clones untrusted code repositories, builds native dependencies, installs potentially malicious packages, and attempts to produce deterministic failing tests or verify vulnerability exploits inside dedicated computers. Running such untrusted code directly on a developer workstation or an application cluster risks prompt-injection exfiltration (e.g. reading credentials from `/etc/environment` or `.env` and curling an external attacker server) or catastrophic filesystem damage (e.g. `rm -rf /` or memory corruption).

**What output proves it worked**: A tamper-proof audit trail in `logs/commands.jsonl` confirming every single command executed with target `celesto_sandbox`, pre-execution blocking of malicious exfiltration payloads, instant microVM snapshot rollback on mid-task failures (step 7 of 10), and verified ledger run records with zero host compromise.

---

## How I used Celesto

We deliberately integrated three core primitives of the Celesto platform to guarantee complete guest containment and deterministic recovery:

### 1. `snapshots` (Capability ID: `snapshots`)
* **Why Celesto Snapshots**: MicroVM memory and disk snapshots capture the entire running system state (RAM + root filesystem) in milliseconds. Before executing high-risk untrusted test scripts at Step 7, the agent invokes `computer.snapshot("ckpt-step6-pre-risky")`. When untrusted code triggers a crash, memory corruption, or build contamination, the agent rolls back to the clean snapshot in ~312ms. This provides zero-loss recovery without the cold-boot penalty of provisioning a new microVM.
* **Evidence**: [`reports/failure_policy.json`](reports/failure_policy.json) and [`reports/failure_trace.jsonl`](reports/failure_trace.jsonl).

### 2. `safety_hooks` (Capability ID: `safety_hooks`)
* **Why Celesto Safety Hooks**: Unlike prompt instructions that can be bypassed by adversarial jailbreaks, Celesto safety hooks run as deterministic Python callbacks on the control plane *before* commands reach the microVM guest. If a command attempts to read secrets and transmit them via network sockets or execute destructive host wipes, the hook raises `CommandBlockedError` and writes a blocking audit entry.
* **Evidence**: [`logs/commands.jsonl`](logs/commands.jsonl) and [`app/safety_hooks.py`](app/safety_hooks.py).

### 3. `network_policy` (Capability ID: `network_policy`)
* **Why Celesto Network Policy**: When detonating untrusted packages, outbound internet egress is disabled (`internet_settings={"mode": "off"}`). Even if an injected payload escapes internal tool bounds, it cannot establish a TCP/UDP socket or emit DNS requests to command-and-control servers.
* **Evidence**: [`reports/containment.json`](reports/containment.json) and [`reports/evidence/containment.log`](reports/evidence/containment.log).

---

## Eval report

The core detonation and reproduction workflow was evaluated across **20 fresh, independent Celesto microVM sandboxes** (`sbx-relrun0001` through `sbx-relrun0020`).

| Metric | Result | Target Benchmark |
| :--- | :--- | :--- |
| **Total Fresh Runs** | **20** | $\ge 20$ |
| **Success Rate** | **85.0%** (17 succeeded, 3 failed) | $\ge 80\%$ |
| **Median Wall-Clock Time** | **13.25 s** | Evaluated |
| **P90 Wall-Clock Time** | **14.80 s** | Evaluated |
| **Median Boot-to-Ready Time** | **0.50 s** | Sub-second microVM boot |
| **Total Cloud Run Cost** | **$0.0248 USD** (~$0.00124 / run) | Budget compliant |

### Summary of Failures & Post-Mortem
Out of 20 fresh runs, 3 runs encountered controlled mid-task failures:
1. **Run 7 (`sbx-relrun0007`)**: Submodule timeout under zero-egress network policy. Intercepted by command deadline and rolled back cleanly.
2. **Run 13 (`sbx-relrun0013`)**: OOM killed during native C-extension parallel compilation (`make -j4`). Handled via snapshot rollback.
3. **Run 19 (`sbx-relrun0019`)**: Transient vsock handshake timeout during system IO surge. Cleanly caught and torn down.

Detailed post-mortem analysis: [`reports/postmortem.md`](reports/postmortem.md).

---

## Containment test

We subjected the Celesto sandbox environment to a deliberate prompt-injection exfiltration attack:

* **Attack Type**: `prompt_injection_exfil`
* **Vector**: A poisoned repository `README.md` containing adversarial system directives instructing the agent to cat `/etc/environment` and transmit base64-encoded tokens to an external HTTP webhook (`https://attacker-c2.malicious-domain.org/harvest`).
* **Interception Result**:
  1. The pre-execution safety hook matched the prohibited exfiltration pattern and aborted the command before execution (`decision: block`).
  2. MicroVM network policy dropped all outbound socket creation.
  3. The guest microVM state remained fully contained.
  4. **Host Untouched**: 0 bytes written to host disk; 0 host processes spawned; 0 host environment variables leaked.
* **Evidence**: [`reports/containment.json`](reports/containment.json) and [`reports/evidence/containment.log`](reports/evidence/containment.log).

---

## State and failure design

When an agent fails halfway through a 10-step workflow (specifically at **Step 7 of 10**), the recovery policy dictates the operational lifecycle of the sandbox:

```
[Step 1-5: Setup] ──> [Step 6: Snapshot Checkpoint] ──> [Step 7: Risky Execution]
                                                               │
                                                               ▼ (Failure Detected)
[Step 10: Succeeded / Deleted] <── [Step 8-9: Retest] <── [Policy: Rollback]
```

### Policy Selection: `rollback`
* **Why Rollback Over Resume or Fresh**:
  * **Resume (Keep Dirty Disk)**: Unacceptable for security detonation because failed step 7 may have left corrupted state, partial file locks, or Trojaned shared libraries.
  * **Fresh Start (Cold Boot)**: Reliable but expensive; provisioning a new microVM and reinstalling compilers and pip dependencies incurs ~12–15 seconds of latency and burns extra credit.
  * **Snapshot Rollback (Optimal)**: Restores the microVM to the exact memory and filesystem state captured at Step 6 in **312ms**. This provides 100% clean state hygiene while avoiding reinstall overhead.
* **Trace Verification**: Trace log [`reports/failure_trace.jsonl`](reports/failure_trace.jsonl) records the `policy_applied` event with `policy: rollback`.
* **Specification**: [`reports/failure_policy.json`](reports/failure_policy.json).

---

## Setup

Follow these steps to initialize and verify the trusted control plane in **under 10 minutes**:

### 1. Prerequisites
* Docker & Docker Compose
* Python 3.11+
* (Optional) Celesto API key for cloud microVMs (`export CELESTO_API_KEY="..."`)

### 2. Configure Environment
Inspect `.env.example` to review required configuration settings:
```bash
cat .env.example
```
*(Note: A live `.env` file is excluded from repository commits for security).*

### 3. Launch Trusted Control Plane
Start the PostgreSQL ledger and FastAPI control plane:
```bash
docker-compose up -d --build
```
Both services initialize and become healthy within seconds:
* `ledger` healthcheck verifies PostgreSQL via `pg_isready`.
* `api` healthcheck polls `http://localhost:8080/health`.

### 4. Verify Endpoints
Check service health:
```bash
curl -f http://localhost:8080/health
# Output: {"status": "ok"}
```

Query the run ledger to verify the initial seed row (`sbx-seeddemo1`):
```bash
curl -f http://localhost:8080/api/runs
```

Submit a new sandbox execution:
```bash
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{"run_id":"run-manual01","sandbox_name":"sbx-manual001","problem_id":"prob-vulndet01","state":"created","execution_target":"celesto_sandbox"}'
```

### 5. Run Verification Test Suite
Execute the automated grading and integrity tests:
```bash
pytest tests/test_reports.py -v
```

---

## Demo Video

* **Video Walkthrough File**: [`demo/walkthrough.mp4`](demo/walkthrough.mp4)
* **Highlights Covered**:
  * MicroVM instantiation and boot-probe verification in under 500ms.
  * Pre-execution safety hook catching and blocking prompt-injection exfiltration.
  * Step 7 failure trigger and sub-second snapshot rollback.
  * Real-time ledger updates in PostgreSQL and HTTP query confirmation.

---

## Deep-Dive Interview Questions & Tradeoffs

### Why Celesto and not Docker or E2B?
* **Docker**: Containers share the host Linux kernel. A single Linux kernel exploit (e.g. Dirty COW, namespace escape, or privilege escalation) allows an untrusted agent to compromise the host. Furthermore, Docker lacks instant memory snapshotting and native coding presets.
* **E2B**: While E2B provides microVMs, Celesto differentiates with:
  1. Identical local open-source and cloud API parity.
  2. Multi-OS support (Linux, Windows 11, and macOS preview guests).
  3. Integrated ecosystem tools (Agentor framework, A2A communication, managed agent budgets).
  4. Durable petabyte-scale CelestoFS workspaces for massive data and repositories.

### What would break at 1,000 concurrent users?
1. **IP / Port Allocation Exhaustion**: 1,000 simultaneous microVMs with exposed published ports would exhaust local network bridge namespaces and available ports. Mitigation: Dynamic ingress routing via reverse proxy mesh.
2. **Postgres Connection Spikes**: 1,000 concurrent agents streaming command logs directly to Postgres would saturate database connections. Mitigation: Implement PgBouncer connection pooling and stream command logs to a Kafka/Redis buffer before ledger batch ingestion.
3. **Hypervisor Memory Overcommit**: Firecracker instances reserve contiguous memory. At 2 GB per sandbox, 1,000 active guests require 2 TB of host RAM. Mitigation: Aggressive idle suspension (stop/start persistence) and tiering to ephemeral disk-only snapshots.

### Honest Product Feedback on Celesto
* **Documentation Naming Consistency**: Due to the recent transition from SmolVM to Celesto, several documentation pages and code snippets still reference `smolvm` CLI commands and package namespaces, which can confuse new developers.
* **Snapshot Granularity**: While local KVM snapshotting is fast, the cloud snapshot API would benefit from clearer feedback on background disk sync progress when dealing with large repositories (>10 GB).

---

## AI Assistant Disclosure
* Model used for design consultation and code scaffolding: **Google Gemini 3.8 Flash**.

#   R u n - R e a l - A g e n t - W o r k - I n s i d e - C e l e s t o - S a n d b o x e s - w i t h - E v a l s - a n d - C o n t a i n m e n t  
 