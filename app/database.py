import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ledger:ledger@ledger:5432/ledger")

# Thread-safe in-memory SQLite connection for isolated testing without PostgreSQL
_MEMORY_CONN = None

def get_connection() -> Tuple[Any, str]:
    """
    Attempts to connect to PostgreSQL if configured and reachable;
    falls back to a shared in-memory SQLite database for zero-disk-dependency testing.
    """
    global _MEMORY_CONN

    if PSYCOPG2_AVAILABLE and DATABASE_URL.startswith("postgresql://"):
        try:
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
            return conn, "postgres"
        except Exception:
            pass
    
    if _MEMORY_CONN is None:
        _MEMORY_CONN = sqlite3.connect("file:ledger_mem?mode=memory&cache=shared", uri=True, check_same_thread=False)
        _MEMORY_CONN.row_factory = sqlite3.Row
    return _MEMORY_CONN, "sqlite"

def close_db():
    """Explicitly closes local memory database connection during testing teardown."""
    global _MEMORY_CONN
    if _MEMORY_CONN is not None:
        try:
            _MEMORY_CONN.close()
        except Exception:
            pass
        _MEMORY_CONN = None

def init_db():
    conn, engine = get_connection()
    try:
        cur = conn.cursor()
        if engine == "postgres":
            cur.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id VARCHAR(255) PRIMARY KEY,
                    sandbox_name VARCHAR(255) NOT NULL,
                    problem_id VARCHAR(255) NOT NULL,
                    state VARCHAR(50) NOT NULL,
                    execution_target VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
                VALUES ('run-seeddemo1', 'sbx-seeddemo1', 'prob-seeddemo', 'deleted', 'celesto_sandbox')
                ON CONFLICT (run_id) DO NOTHING;
            """)
            conn.commit()
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    sandbox_name TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    execution_target TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                INSERT OR IGNORE INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
                VALUES ('run-seeddemo1', 'sbx-seeddemo1', 'prob-seeddemo', 'deleted', 'celesto_sandbox');
            """)
            conn.commit()
    finally:
        if engine == "postgres":
            conn.close()

def list_runs() -> List[Dict[str, Any]]:
    conn, engine = get_connection()
    try:
        cur = conn.cursor()
        if engine == "postgres":
            cur.execute("SELECT run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at FROM runs ORDER BY created_at ASC;")
            rows = cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    "run_id": r[0],
                    "sandbox_name": r[1],
                    "problem_id": r[2],
                    "state": r[3],
                    "execution_target": r[4],
                    "created_at": r[5].isoformat() if r[5] else None,
                    "updated_at": r[6].isoformat() if r[6] else None,
                })
            return results
        else:
            cur.execute("SELECT run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at FROM runs ORDER BY created_at ASC;")
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        if engine == "postgres":
            conn.close()

def insert_run(run_data: Dict[str, Any]) -> Dict[str, Any]:
    conn, engine = get_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.cursor()
        if engine == "postgres":
            cur.execute("""
                INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (run_id) DO UPDATE SET
                    sandbox_name = EXCLUDED.sandbox_name,
                    problem_id = EXCLUDED.problem_id,
                    state = EXCLUDED.state,
                    execution_target = EXCLUDED.execution_target,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at;
            """, (
                run_data["run_id"],
                run_data["sandbox_name"],
                run_data["problem_id"],
                run_data["state"],
                run_data["execution_target"]
            ))
            row = cur.fetchone()
            conn.commit()
            return {
                "run_id": row[0],
                "sandbox_name": row[1],
                "problem_id": row[2],
                "state": row[3],
                "execution_target": row[4],
                "created_at": row[5].isoformat() if row[5] else now_iso,
                "updated_at": row[6].isoformat() if row[6] else now_iso,
            }
        else:
            cur.execute("""
                INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    sandbox_name = excluded.sandbox_name,
                    problem_id = excluded.problem_id,
                    state = excluded.state,
                    execution_target = excluded.execution_target,
                    updated_at = excluded.updated_at;
            """, (
                run_data["run_id"],
                run_data["sandbox_name"],
                run_data["problem_id"],
                run_data["state"],
                run_data["execution_target"],
                now_iso,
                now_iso
            ))
            conn.commit()
            return {
                "run_id": run_data["run_id"],
                "sandbox_name": run_data["sandbox_name"],
                "problem_id": run_data["problem_id"],
                "state": run_data["state"],
                "execution_target": run_data["execution_target"],
                "created_at": now_iso,
                "updated_at": now_iso
            }
    finally:
        if engine == "postgres":
            conn.close()
