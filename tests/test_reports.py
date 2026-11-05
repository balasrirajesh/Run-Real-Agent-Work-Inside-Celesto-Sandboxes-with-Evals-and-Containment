import os
import sys
import re
import json
import math
import unittest
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.models import (
    validate_run_payload,
    SANDBOX_NAME_REGEX,
    VALID_STATES,
    REQUIRED_EXECUTION_TARGET,
)
from app.database import init_db, list_runs, insert_run

def get_path(rel_path: str) -> str:
    return os.path.join(REPO_ROOT, rel_path)

class TestCelestoReports(unittest.TestCase):

    def setUp(self):
        init_db()

    def tearDown(self):
        from app.database import close_db
        close_db()

    def test_docker_compose_and_dockerfile(self):
        compose_path = get_path("docker-compose.yml")
        dockerfile_path = get_path("Dockerfile")
        self.assertTrue(os.path.exists(compose_path), "docker-compose.yml must exist at repository root")
        self.assertTrue(os.path.exists(dockerfile_path), "Dockerfile must exist at repository root")

        with open(compose_path, "r", encoding="utf-8") as f:
            compose_content = f.read()

        self.assertIn("api:", compose_content, "api service must be defined in docker-compose.yml")
        self.assertIn("ledger:", compose_content, "ledger service must be defined in docker-compose.yml")

        # Port 8080 published
        self.assertTrue("8080:8080" in compose_content or '"8080:8080"' in compose_content)
        # Seeds mounted
        self.assertTrue("seeds:" in compose_content or "./seeds" in compose_content)
        # API waits for ledger health
        self.assertIn("service_healthy", compose_content)
        # Healthchecks
        self.assertIn("pg_isready", compose_content, "ledger healthcheck must use pg_isready")
        self.assertIn("http://localhost:8080/health", compose_content, "api healthcheck must request http://localhost:8080/health")

        for field in ["interval:", "timeout:", "retries:", "start_period:"]:
            self.assertGreaterEqual(compose_content.count(field), 2, f"Both healthchecks must configure {field}")

    def test_env_example_and_no_live_env(self):
        env_example_path = get_path(".env.example")
        live_env_path = get_path(".env")

        self.assertTrue(os.path.exists(env_example_path), ".env.example must exist at root")
        self.assertFalse(os.path.exists(live_env_path), ".env must NOT be present at repository root")

        with open(env_example_path, "r", encoding="utf-8") as f:
            env_content = f.read()

        required_keys = [
            "CELESTO_PROVIDER",
            "CELESTO_API_KEY",
            "LLM_API_KEY",
            "LLM_MODEL",
            "DATABASE_URL",
            "API_PORT"
        ]
        for key in required_keys:
            self.assertTrue(
                bool(re.search(rf"^{key}=", env_content, re.MULTILINE)),
                f"Missing required env key {key} in .env.example"
            )

    def test_seeds_sql(self):
        seeds_path = get_path("seeds/01_runs.sql")
        self.assertTrue(os.path.exists(seeds_path), "seeds/01_runs.sql must exist")

        with open(seeds_path, "r", encoding="utf-8") as f:
            sql_content = f.read()

        self.assertIn("sbx-seeddemo1", sql_content, "Seed row must include sandbox name sbx-seeddemo1")
        self.assertIn("deleted", sql_content, "Seed row state must be deleted")
        self.assertIn("celesto_sandbox", sql_content, "Seed row execution target must be celesto_sandbox")
        self.assertIn("ON CONFLICT", sql_content.upper(), "Seed SQL must be idempotent")

    def test_problem_json(self):
        problem_path = get_path("reports/problem.json")
        self.assertTrue(os.path.exists(problem_path), "reports/problem.json must exist")

        with open(problem_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for key in ["who", "agent_work", "proof_output", "idea_source"]:
            self.assertIn(key, data, f"Missing key {key} in problem.json")

        self.assertIn(data["idea_source"], ["idea_bank", "original"])
        self.assertGreaterEqual(len(data["who"]), 40)
        self.assertGreaterEqual(len(data["agent_work"]), 40)
        self.assertGreaterEqual(len(data["proof_output"]), 20)

    def test_commands_jsonl(self):
        commands_path = get_path("logs/commands.jsonl")
        self.assertTrue(os.path.exists(commands_path), "logs/commands.jsonl must exist")

        lines = []
        with open(commands_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))

        self.assertGreaterEqual(len(lines), 1, "logs/commands.jsonl must have at least one JSON line")

        has_allow = False
        has_block = False
        for entry in lines:
            for key in ["ts", "sandbox_name", "command", "decision", "execution_target"]:
                self.assertIn(key, entry, f"Missing key {key} in command log line")

            datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
            self.assertTrue(bool(SANDBOX_NAME_REGEX.match(entry["sandbox_name"])), f"Invalid sandbox_name: {entry['sandbox_name']}")
            self.assertGreater(len(entry["command"]), 0)
            self.assertIn(entry["decision"], ["allow", "block"])
            self.assertEqual(entry["execution_target"], "celesto_sandbox")

            if entry["decision"] == "allow":
                has_allow = True
            if entry["decision"] == "block":
                has_block = True

        self.assertTrue(has_allow, "logs/commands.jsonl should have allowed commands")
        self.assertTrue(has_block, "logs/commands.jsonl should have blocked commands")

    def test_capabilities_json(self):
        caps_path = get_path("reports/capabilities.json")
        self.assertTrue(os.path.exists(caps_path), "reports/capabilities.json must exist")

        with open(caps_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("capabilities", data)
        caps = data["capabilities"]
        self.assertGreaterEqual(len(caps), 2)

        allowed_ids = {
            "persistence", "snapshots", "celestofs", "browser", "published_ports",
            "network_policy", "safety_hooks", "host_mounts", "coding_agent_preset", "agentor_durable"
        }

        seen_ids = set()
        for cap in caps:
            cid = cap.get("id")
            self.assertIn(cid, allowed_ids)
            self.assertNotIn(cid, seen_ids)
            seen_ids.add(cid)

            why = cap.get("why", "")
            self.assertGreaterEqual(len(why), 80)

            evidence_path = cap.get("evidence_path", "")
            self.assertTrue(os.path.exists(get_path(evidence_path)), f"evidence_path '{evidence_path}' does not exist")

    def test_lifecycle_json(self):
        lifecycle_path = get_path("reports/lifecycle.json")
        self.assertTrue(os.path.exists(lifecycle_path), "reports/lifecycle.json must exist")

        with open(lifecycle_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIs(data.get("cleanup_on_success"), True)
        self.assertIs(data.get("cleanup_on_failure"), True)
        self.assertIs(data.get("cleanup_on_interrupt"), True)

        sandbox_names = data.get("sandbox_names", [])
        self.assertGreater(len(sandbox_names), 0)
        self.assertEqual(len(sandbox_names), len(set(sandbox_names)))

        for name in sandbox_names:
            self.assertTrue(bool(SANDBOX_NAME_REGEX.match(name)))

        commands_path = get_path("logs/commands.jsonl")
        command_sbxs = set()
        with open(commands_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    command_sbxs.add(json.loads(line.strip())["sandbox_name"])

        reliability_path = get_path("reports/reliability.json")
        reliability_sbxs = set()
        with open(reliability_path, "r", encoding="utf-8") as f:
            rel_data = json.load(f)
            for r in rel_data.get("runs", []):
                reliability_sbxs.add(r["sandbox_name"])

        for name in sandbox_names:
            self.assertTrue(
                name in command_sbxs or name in reliability_sbxs,
                f"Sandbox {name} must appear in commands log or reliability report"
            )

    def test_reliability_json_and_postmortem(self):
        rel_path = get_path("reports/reliability.json")
        self.assertTrue(os.path.exists(rel_path), "reports/reliability.json must exist")

        with open(rel_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        runs = data.get("runs", [])
        run_count = data.get("run_count")
        self.assertGreaterEqual(run_count, 20)
        self.assertEqual(run_count, len(runs))

        seen_names = set()
        for r in runs:
            name = r["sandbox_name"]
            self.assertTrue(bool(SANDBOX_NAME_REGEX.match(name)))
            self.assertNotIn(name, seen_names)
            seen_names.add(name)
            self.assertIs(r["fresh"], True)
            self.assertIsInstance(r["success"], bool)
            self.assertGreaterEqual(r["wall_clock_s"], 0)
            self.assertGreaterEqual(r["boot_to_ready_s"], 0)
            self.assertGreaterEqual(r["cost_usd"], 0)

        # Statistical arithmetic
        successes = sum(1 for r in runs if r["success"])
        expected_success_rate = successes / run_count
        self.assertLessEqual(abs(data["success_rate"] - expected_success_rate), 0.001)

        sorted_wall = sorted([r["wall_clock_s"] for r in runs])
        expected_median_wall = (sorted_wall[run_count // 2 - 1] + sorted_wall[run_count // 2]) / 2.0
        self.assertLessEqual(abs(data["median_wall_clock_s"] - expected_median_wall), 0.001)

        p90_rank = math.ceil(0.90 * run_count)
        expected_p90 = sorted_wall[p90_rank - 1]
        self.assertLessEqual(abs(data["p90_wall_clock_s"] - expected_p90), 0.001)

        sorted_boot = sorted([r["boot_to_ready_s"] for r in runs])
        expected_median_boot = (sorted_boot[run_count // 2 - 1] + sorted_boot[run_count // 2]) / 2.0
        self.assertLessEqual(abs(data["median_boot_to_ready_s"] - expected_median_boot), 0.001)

        expected_total_cost = sum(r["cost_usd"] for r in runs)
        self.assertLessEqual(abs(data["total_cost_usd"] - expected_total_cost), 0.01)

        postmortem_rel = data.get("postmortem_path")
        self.assertEqual(postmortem_rel, "reports/postmortem.md")
        postmortem_full = get_path(postmortem_rel)
        self.assertTrue(os.path.exists(postmortem_full))

        with open(postmortem_full, "r", encoding="utf-8") as f:
            pm_text = f.read()
        self.assertGreaterEqual(len(pm_text), 200)

    def test_containment_json(self):
        containment_path = get_path("reports/containment.json")
        self.assertTrue(os.path.exists(containment_path), "reports/containment.json must exist")

        with open(containment_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn(data["attack"], ["prompt_injection_exfil", "destructive_command", "suspicious_package"])
        self.assertIs(data["blocked"], True)
        self.assertIs(data["host_untouched"], True)

        evidence_paths = data.get("evidence_paths", [])
        self.assertGreaterEqual(len(evidence_paths), 1)
        for p in evidence_paths:
            self.assertTrue(os.path.exists(get_path(p)), f"Containment evidence path '{p}' does not exist")

    def test_failure_policy_and_trace(self):
        policy_path = get_path("reports/failure_policy.json")
        self.assertTrue(os.path.exists(policy_path), "reports/failure_policy.json must exist")

        with open(policy_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["failed_step"], 7)
        self.assertEqual(data["total_steps"], 10)
        self.assertIn(data["policy"], ["resume", "rollback", "fresh"])
        self.assertGreaterEqual(len(data["rationale"]), 200)

        trace_rel = data.get("trace_path")
        self.assertEqual(trace_rel, "reports/failure_trace.jsonl")
        trace_full = get_path(trace_rel)
        self.assertTrue(os.path.exists(trace_full))

        found_policy_event = False
        with open(trace_full, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line.strip())
                    if item.get("event") == "policy_applied" and item.get("policy") == data["policy"]:
                        found_policy_event = True
                        break

        self.assertTrue(found_policy_event, f"Missing policy_applied event with policy '{data['policy']}' in trace")

    def test_concurrency_json(self):
        concurrency_path = get_path("reports/concurrency.json")
        self.assertTrue(os.path.exists(concurrency_path), "reports/concurrency.json must exist")

        with open(concurrency_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        jobs = data.get("jobs", [])
        self.assertGreaterEqual(len(jobs), 5)

        seen_sbx = set()
        for job in jobs:
            sbx = job["sandbox_name"]
            self.assertTrue(bool(SANDBOX_NAME_REGEX.match(sbx)))
            self.assertNotIn(sbx, seen_sbx)
            seen_sbx.add(sbx)
            self.assertGreater(len(job["started_at"]), 0)

        breakage_notes = data.get("breakage_notes", "")
        self.assertGreaterEqual(len(breakage_notes), 40)

    def test_api_endpoints_logic(self):
        # 1. Test database list runs includes seed demo run
        runs = list_runs()
        self.assertTrue(any(r.get("sandbox_name") == "sbx-seeddemo1" for r in runs))

        # 2. Test valid run creation
        valid_payload = {
            "run_id": "run-testapi001",
            "sandbox_name": "sbx-testapirun01",
            "problem_id": "prob-test01",
            "state": "running",
            "execution_target": "celesto_sandbox"
        }
        validated = validate_run_payload(valid_payload)
        stored = insert_run(validated)
        self.assertEqual(stored["sandbox_name"], "sbx-testapirun01")
        self.assertEqual(stored["execution_target"], "celesto_sandbox")

        # 3. Test invalid execution_target
        bad_target = dict(valid_payload, execution_target="host")
        with self.assertRaises(ValueError):
            validate_run_payload(bad_target)

        # 4. Test invalid state
        bad_state = dict(valid_payload, state="bad_state")
        with self.assertRaises(ValueError):
            validate_run_payload(bad_state)

        # 5. Test invalid sandbox_name
        bad_name = dict(valid_payload, sandbox_name="invalid-name")
        with self.assertRaises(ValueError):
            validate_run_payload(bad_name)

        # If FastAPI is available, test with TestClient
        try:
            from fastapi.testclient import TestClient
            from app.main import app
            if app is not None:
                client = TestClient(app)
                res = client.get("/health")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json(), {"status": "ok"})

                res = client.get("/api/runs")
                self.assertEqual(res.status_code, 200)

                res = client.post("/api/runs", json=valid_payload)
                self.assertEqual(res.status_code, 201)

                res = client.post("/api/runs", json=bad_target)
                self.assertEqual(res.status_code, 400)

                res = client.post("/api/runs", json=bad_state)
                self.assertEqual(res.status_code, 400)

                res = client.post("/api/runs", json=bad_name)
                self.assertEqual(res.status_code, 400)
        except ImportError:
            pass

    def test_demo_walkthrough_exists(self):
        demo_path = get_path("demo/walkthrough.mp4")
        self.assertTrue(os.path.exists(demo_path), "demo/walkthrough.mp4 must exist")
        self.assertGreater(os.path.getsize(demo_path), 0, "demo/walkthrough.mp4 must not be empty")

    def test_readme_phrases(self):
        readme_path = get_path("README.md")
        self.assertTrue(os.path.exists(readme_path), "README.md must exist at root")

        with open(readme_path, "r", encoding="utf-8") as f:
            readme_content = f.read()

        required_phrases = [
            "Problem statement",
            "How I used Celesto",
            "Eval report",
            "Containment test",
            "State and failure design",
            "Setup"
        ]

        for phrase in required_phrases:
            self.assertIn(phrase, readme_content, f"Missing required phrase in README.md: '{phrase}'")

if __name__ == "__main__":
    unittest.main()
