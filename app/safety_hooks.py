import json
import os
import re
from datetime import datetime, timezone
from typing import Tuple

COMMAND_LOG_PATH = os.path.join("logs", "commands.jsonl")

# Block patterns for prompt injection exfiltration and host/destructive sabotage
DANGEROUS_PATTERNS = [
    re.compile(r"curl\s+.*-(?:d|-data)\s+.*(?:token|secret|env|password)", re.IGNORECASE),
    re.compile(r"curl\s+.*attacker-c2", re.IGNORECASE),
    re.compile(r"wget\s+.*attacker", re.IGNORECASE),
    re.compile(r"rm\s+-rf\s+/(?:\s+|$)", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE), # fork bomb
    re.compile(r"mkfs\.", re.IGNORECASE),
    re.compile(r"dd\s+if=.*of=/dev/(?:sd|nvme|vd)", re.IGNORECASE),
]

class CommandBlockedError(Exception):
    """Raised when a pre-execution safety hook detects a hazardous or exfiltrating command."""
    pass

def audit_command(sandbox_name: str, command: str) -> Tuple[bool, str]:
    """
    Evaluates command against pre-execution safety policies and logs to commands.jsonl.
    Enforces execution_target = 'celesto_sandbox'.
    """
    decision = "allow"
    reason = "Command approved for sandbox execution."

    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(command):
            decision = "block"
            reason = f"Command matched prohibited security pattern: {pattern.pattern}"
            break

    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sandbox_name": sandbox_name,
        "command": command,
        "decision": decision,
        "execution_target": "celesto_sandbox"
    }

    os.makedirs(os.path.dirname(COMMAND_LOG_PATH), exist_ok=True)
    with open(COMMAND_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    return (decision == "allow", reason)

def pre_exec_hook(sandbox_name: str, command: str) -> None:
    """
    Celesto safety hook: runs before command reaches the microVM guest.
    Raises CommandBlockedError if the command fails safety inspection.
    """
    allowed, reason = audit_command(sandbox_name, command)
    if not allowed:
        raise CommandBlockedError(f"[SAFETY HOOK BLOCKED] Sandbox '{sandbox_name}': {reason} | Command: {command}")
