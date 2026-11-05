import os
import json
from contextlib import asynccontextmanager
from typing import List, Dict, Any

from app.models import validate_run_payload, SANDBOX_NAME_REGEX, VALID_STATES, REQUIRED_EXECUTION_TARGET
from app.database import init_db, list_runs, insert_run

try:
    from fastapi import FastAPI, HTTPException, Request, status
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import RequestValidationError
    from app.models import RunCreate, RunResponse

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        yield

    app = FastAPI(
        title="Celesto Run Ledger & Agent Control Plane",
        description="Trusted control plane API for orchestrating and auditing Celesto microVM agent runs.",
        version="1.0.0",
        lifespan=lifespan
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        from fastapi.encoders import jsonable_encoder
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": jsonable_encoder(exc.errors()), "message": "Validation failed"}
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc), "message": "Validation failed"}
        )

    @app.get("/health")
    def health_check():
        return {"status": "ok"}

    @app.get("/api/runs", response_model=List[RunResponse])
    def get_runs():
        return list_runs()

    @app.post("/api/runs", status_code=status.HTTP_201_CREATED, response_model=RunResponse)
    def create_run(run: RunCreate):
        stored = insert_run(run.model_dump())
        return stored

    @app.get("/api/reports/{report_name}")
    def get_report(report_name: str):
        safe_name = os.path.basename(report_name)
        path = os.path.join("reports", safe_name)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Report not found")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if safe_name.endswith(".json"):
            return json.loads(content)
        return {"content": content}

except ImportError:
    # Fallback minimal app representation if fastapi is not installed on local host
    app = None
