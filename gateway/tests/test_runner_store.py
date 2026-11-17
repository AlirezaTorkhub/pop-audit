from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.runner import AuditRunner


class AuditRunnerPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        os.environ["POP_AUDIT_DB_PATH"] = str(
            Path(self.temp_dir.name) / "jobs.sqlite3"
        )
        self.runner = AuditRunner()

    def test_new_job_survives_runner_restart(self) -> None:
        job_id = self.runner.create_job("2488")
        original = self.runner.get_job(job_id)
        original["status"] = "COMPLETED"
        original["audit_status"] = "PASS"
        original["summary"] = {"pass": 3}
        self.runner._save_job(original)

        restarted_runner = AuditRunner()
        job = restarted_runner.get_job(job_id)

        self.assertIsNotNone(job)
        self.assertEqual(job["site_code"], "2488")
        self.assertEqual(job["status"], "COMPLETED")
        self.assertEqual(job["audit_status"], "PASS")
        self.assertEqual(job["summary"], {"pass": 3})

    def test_interrupted_job_is_marked_failed_on_restart(self) -> None:
        job_id = self.runner.create_job("2488")
        job = self.runner.get_job(job_id)
        job["status"] = "RUNNING"
        self.runner._save_job(job)

        restarted_runner = AuditRunner()
        recovered = restarted_runner.get_job(job_id)

        self.assertEqual(recovered["status"], "FAILED")
        self.assertEqual(recovered["audit_status"], "UNKNOWN")
        self.assertIn("restarted", recovered["error"])

    def test_audit_status_priority_is_preserved(self) -> None:
        self.assertEqual(
            self.runner.aggregate_status(["PASS", "WARNING", "CRITICAL"]),
            "CRITICAL",
        )
        self.assertEqual(
            self.runner.aggregate_status(["PASS", "UNKNOWN"]),
            "UNKNOWN",
        )

    def test_empty_status_list_is_unknown(self) -> None:
        self.assertEqual(self.runner.aggregate_status([]), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
