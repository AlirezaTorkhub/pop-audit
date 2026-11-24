import asyncio
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


load_dotenv("/opt/pop-audit/config/.env")


ZABBIX_SERVICE_URL = os.environ["ZABBIX_SERVICE_URL"]
CISCO_SERVICE_URL = os.environ["CISCO_SERVICE_URL"]
ERICSSON_SERVICE_URL = os.environ["ERICSSON_SERVICE_URL"]
RADIO_SERVICE_URL = os.environ["RADIO_SERVICE_URL"]
REPORT_SERVICE_URL = os.getenv(
    "REPORT_SERVICE_URL",
    "http://report-service:8006",
)


STATUS_PRIORITY = {
    "CRITICAL": 5,
    "WARNING": 4,
    "UNKNOWN": 3,
    "NOT_AVAILABLE": 2,
    "PASS": 1,
}


class AuditRunner:
    def __init__(self):
        self.jobs: dict[str, dict[str, Any]] = {}
        self.db_path = Path(
            os.getenv(
                "POP_AUDIT_DB_PATH",
                "/opt/pop-audit/data/jobs.sqlite3",
            )
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _connect_db(self):
        connection = sqlite3.connect(str(self.db_path), timeout=20)
        connection.execute("PRAGMA busy_timeout = 20000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize_database(self) -> None:
        with self._connect_db() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_jobs (
                    job_id TEXT PRIMARY KEY,
                    site_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_jobs_updated_at "
                "ON audit_jobs(updated_at)"
            )

    def _persist_job(self, job: dict[str, Any]) -> None:
        payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"), default=str)
        with self._connect_db() as connection:
            connection.execute(
                """
                INSERT INTO audit_jobs(job_id, site_code, status, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    site_code = excluded.site_code,
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    str(job["job_id"]),
                    str(job["site_code"]),
                    str(job["status"]),
                    payload,
                ),
            )

    # ---------------------------------------------------------
    # STATUS HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def aggregate_status(statuses: list[str]) -> str:
        if not statuses:
            return "UNKNOWN"
        return max(statuses, key=lambda value: STATUS_PRIORITY.get(value, 3))

    @staticmethod
    def extract_service_status(result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return "UNKNOWN"

        wrapper_status = result.get("status")
        if wrapper_status == "FAILED":
            return "CRITICAL"

        data = result.get("data")
        if isinstance(data, dict):
            data_status = data.get("status")
            if data_status in STATUS_PRIORITY:
                return data_status

            nested = data.get("result")
            if isinstance(nested, dict):
                nested_status = nested.get("status")
                if nested_status in STATUS_PRIORITY:
                    return nested_status

        return "UNKNOWN"

    def calculate_audit_status(self, results: dict[str, Any]) -> str:
        statuses = [
            self.extract_service_status(result)
            for result in results.values()
        ]
        return self.aggregate_status(statuses)

    # ---------------------------------------------------------
    # JOB MANAGEMENT
    # ---------------------------------------------------------

    def create_job(self, site_code: str) -> str:
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = {
            "job_id": job_id,
            "site_code": site_code,
            "status": "QUEUED",
            "audit_status": "UNKNOWN",
            "discovery": None,
            "results": {},
            "summary": None,
            "report": None,
            "report_error": None,
            "error": None,
        }
        self._persist_job(self.jobs[job_id])
        return job_id

    def get_job(self, job_id: str):
        in_memory = self.jobs.get(job_id)
        if in_memory is not None:
            return in_memory

        with self._connect_db() as connection:
            row = connection.execute(
                "SELECT payload FROM audit_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()

        if not row:
            return None

        try:
            job = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None

        # A process restart cannot resume the previous asyncio task.
        # Mark an interrupted run explicitly instead of leaving it QUEUED/RUNNING forever.
        if job.get("status") in {"QUEUED", "DISCOVERY", "RUNNING"}:
            job["status"] = "FAILED"
            job["audit_status"] = "UNKNOWN"
            job["error"] = (
                "Orchestrator restarted while this audit was in progress. "
                "Start a new audit to obtain a fresh result."
            )
            self._persist_job(job)

        self.jobs[job_id] = job
        return job

    # ---------------------------------------------------------
    # ZABBIX DISCOVERY
    # ---------------------------------------------------------

    async def _discover(self, site_code: str):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{ZABBIX_SERVICE_URL}/discover",
                json={"site_code": site_code},
            )
            response.raise_for_status()
            return response.json()

    # ---------------------------------------------------------
    # GENERIC MICROSERVICE CALL
    # ---------------------------------------------------------

    async def _call_service(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict,
        service_name: str,
    ):
        try:
            response = await client.post(url, json=payload, timeout=300)
            if response.is_success:
                return {
                    "service": service_name,
                    "status": "COMPLETED",
                    "data": response.json(),
                }
            return {
                "service": service_name,
                "status": "FAILED",
                "error": f"HTTP {response.status_code}: {response.text}",
            }
        except Exception as exc:
            return {
                "service": service_name,
                "status": "FAILED",
                "error": str(exc),
            }

    # ---------------------------------------------------------
    # BUILD SUMMARY
    # ---------------------------------------------------------

    def build_summary(self, results: dict[str, Any]) -> dict:
        service_statuses = {
            service_name: self.extract_service_status(result)
            for service_name, result in results.items()
        }
        statuses = list(service_statuses.values())

        return {
            "service_count": len(service_statuses),
            "critical": sum(status == "CRITICAL" for status in statuses),
            "warning": sum(status == "WARNING" for status in statuses),
            "unknown": sum(status == "UNKNOWN" for status in statuses),
            "not_available": sum(status == "NOT_AVAILABLE" for status in statuses),
            "pass": sum(status == "PASS" for status in statuses),
            "services": service_statuses,
        }

    # ---------------------------------------------------------
    # REPORT GENERATION
    # ---------------------------------------------------------

    async def _generate_report(self, job: dict[str, Any]) -> None:
        payload = {
            "site_code": job["site_code"],
            "results": job["results"],
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{REPORT_SERVICE_URL}/generate",
                    json=payload,
                )
                response.raise_for_status()
                job["report"] = response.json()
                job["report_error"] = None
        except Exception as exc:
            # Report generation failure must not invalidate a completed audit.
            job["report"] = None
            job["report_error"] = str(exc)
        finally:
            self._persist_job(job)

    # ---------------------------------------------------------
    # RUN COMPLETE AUDIT
    # ---------------------------------------------------------

    async def run_job(self, job_id: str):
        job = self.jobs[job_id]
        site_code = job["site_code"]

        try:
            job["status"] = "DISCOVERY"
            self._persist_job(job)

            discovery = await self._discover(site_code)
            job["discovery"] = discovery
            self._persist_job(job)

            job["status"] = "RUNNING"
            self._persist_job(job)

            async with httpx.AsyncClient() as client:
                cisco_task = self._call_service(
                    client,
                    f"{CISCO_SERVICE_URL}/check",
                    {
                        "site_code": site_code,
                        "devices": discovery.get("devices", []),
                    },
                    "cisco",
                )

                ericsson_task = self._call_service(
                    client,
                    f"{ERICSSON_SERVICE_URL}/check",
                    {
                        "site_code": site_code,
                        "basebands": discovery.get("basebands", []),
                    },
                    "ericsson",
                )

                radio_task = self._call_service(
                    client,
                    f"{RADIO_SERVICE_URL}/analyze",
                    {
                        "site_code": site_code,
                        "links": discovery.get("radio_links", []),
                    },
                    "radio",
                )

                service_results = await asyncio.gather(
                    cisco_task,
                    ericsson_task,
                    radio_task,
                )

            for result in service_results:
                service_name = result["service"]
                job["results"][service_name] = result
                self._persist_job(job)

            job["audit_status"] = self.calculate_audit_status(job["results"])
            job["summary"] = self.build_summary(job["results"])
            job["status"] = "COMPLETED"
            self._persist_job(job)

            await self._generate_report(job)

        except Exception as exc:
            job["status"] = "FAILED"
            job["audit_status"] = "CRITICAL"
            job["error"] = str(exc)
            job["summary"] = {
                "service_count": len(job.get("results", {})),
                "critical": 1,
                "warning": 0,
                "unknown": 0,
                "not_available": 0,
                "pass": 0,
                "services": {},
            }
            self._persist_job(job)

        return job
