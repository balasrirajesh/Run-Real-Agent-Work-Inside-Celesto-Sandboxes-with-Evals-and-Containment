import re
from typing import Optional, Dict, Any

SANDBOX_NAME_REGEX = re.compile(r"^sbx-[a-z0-9]{8,}$")
VALID_STATES = {"created", "ready", "running", "succeeded", "failed", "deleted"}
REQUIRED_EXECUTION_TARGET = "celesto_sandbox"

def validate_run_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validates run payload against hackathon schema rules."""
    for field in ["run_id", "sandbox_name", "problem_id", "state", "execution_target"]:
        if field not in payload or not isinstance(payload[field], str):
            raise ValueError(f"Field '{field}' is required and must be a string.")

    sandbox_name = payload["sandbox_name"]
    if not SANDBOX_NAME_REGEX.match(sandbox_name):
        raise ValueError(f"sandbox_name '{sandbox_name}' is invalid. Must match regex ^sbx-[a-z0-9]{{8,}}$")

    state = payload["state"]
    if state not in VALID_STATES:
        raise ValueError(f"state '{state}' is invalid. Must be one of: {sorted(VALID_STATES)}")

    execution_target = payload["execution_target"]
    if execution_target != REQUIRED_EXECUTION_TARGET:
        raise ValueError(f"execution_target '{execution_target}' is invalid. Must be exactly '{REQUIRED_EXECUTION_TARGET}'")

    return payload

try:
    from pydantic import BaseModel, field_validator

    class RunCreate(BaseModel):
        run_id: str
        sandbox_name: str
        problem_id: str
        state: str
        execution_target: str

        @field_validator("sandbox_name")
        @classmethod
        def validate_sandbox_name(cls, v: str) -> str:
            if not SANDBOX_NAME_REGEX.match(v):
                raise ValueError(f"sandbox_name '{v}' is invalid. Must match regex ^sbx-[a-z0-9]{{8,}}$")
            return v

        @field_validator("state")
        @classmethod
        def validate_state(cls, v: str) -> str:
            if v not in VALID_STATES:
                raise ValueError(f"state '{v}' is invalid. Must be one of: {sorted(VALID_STATES)}")
            return v

        @field_validator("execution_target")
        @classmethod
        def validate_execution_target(cls, v: str) -> str:
            if v != REQUIRED_EXECUTION_TARGET:
                raise ValueError(f"execution_target '{v}' is invalid. Must be exactly '{REQUIRED_EXECUTION_TARGET}'")
            return v

    class RunResponse(BaseModel):
        run_id: str
        sandbox_name: str
        problem_id: str
        state: str
        execution_target: str
        created_at: Optional[str] = None
        updated_at: Optional[str] = None

except ImportError:
    # Lightweight fallback for hosts without pydantic installed
    class RunCreate:
        def __init__(self, **kwargs):
            validated = validate_run_payload(kwargs)
            for k, v in validated.items():
                setattr(self, k, v)

        def model_dump(self):
            return {
                "run_id": self.run_id,
                "sandbox_name": self.sandbox_name,
                "problem_id": self.problem_id,
                "state": self.state,
                "execution_target": self.execution_target
            }

    class RunResponse:
        pass
