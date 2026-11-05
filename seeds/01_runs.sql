-- Initial seed for Celesto Run Ledger
-- Ensures idempotency: re-running this script will not duplicate entries.

CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR(255) PRIMARY KEY,
    sandbox_name VARCHAR(255) NOT NULL,
    problem_id VARCHAR(255) NOT NULL,
    state VARCHAR(50) NOT NULL,
    execution_target VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_runs_sandbox_name ON runs(sandbox_name);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state);

-- Seed row required by the evaluation harness:
-- sandbox name: sbx-seeddemo1, state: deleted, execution target: celesto_sandbox
INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
VALUES ('run-seeddemo1', 'sbx-seeddemo1', 'prob-seeddemo', 'deleted', 'celesto_sandbox')
ON CONFLICT (run_id) DO NOTHING;
