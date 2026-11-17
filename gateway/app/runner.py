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


DEFAULT_DB_PATH = "/opt/pop-audit/data/jobs.sqlite3"


ZABBIX_SERVICE_URL = os.environ["ZABBIX_SERVICE_URL"]
CISCO_SERVICE_URL = os.environ["CISCO_SERVICE_URL"]
ERICSSON_SERVICE_URL = os.environ["ERICSSON_SERVICE_URL"]
RADIO_SERVICE_URL = os.environ["RADIO_SERVICE_URL"]

REPORT_SERVICE_URL = os.getenv(
    "REPORT_SERVICE_URL",
    "http://127.0.0.1:8006",
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
        self.db_path = Path(os.getenv("POP_AUDIT_DB_PATH", DEFAULT_DB_PATH))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_store()
        self._load_store()

    def _init_store(self) -> None:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=10000")
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
                "CREATE INDEX IF NOT EXISTS idx_audit_jobs_site_created "
                "ON audit_jobs(site_code, created_at)"
            )

    def _save_job(self, job: dict[str, Any]) -> None:
        payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute(
                """
                INSERT INTO audit_jobs(job_id, site_code, status, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    site_code=excluded.site_code,
                    status=excluded.status,
                    payload=excluded.payload,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (job["job_id"], job["site_code"], job["status"], payload),
            )

    def _load_store(self) -> None:
        with sqlite3.connect(self.db_path, timeout=10) as connection:
            rows = connection.execute(
                "SELECT payload FROM audit_jobs ORDER BY created_at"
            ).fetchall()

        for (payload,) in rows:
            try:
                job = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(job, dict) or not job.get("job_id"):
                continue
            if job.get("status") in {"QUEUED", "DISCOVERY", "RUNNING"}:
                job["status"] = "FAILED"
                job["audit_status"] = "UNKNOWN"
                job["error"] = (
                    "Backend restarted while this audit was running. "
                    "Please submit a new audit."
                )
                self._save_job(job)
            self.jobs[job["job_id"]] = job

    # ---------------------------------------------------------
    # STATUS HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def aggregate_status(
        statuses: list[str],
    ) -> str:

        if not statuses:
            return "UNKNOWN"

        return max(
            statuses,
            key=lambda x: STATUS_PRIORITY.get(x, 3),
        )

    @staticmethod
    def extract_service_status(
        result: dict[str, Any],
    ) -> str:

        if not isinstance(result, dict):
            return "UNKNOWN"

        wrapper_status = result.get(
            "status"
        )

        if wrapper_status == "FAILED":
            return "CRITICAL"

        data = result.get(
            "data"
        )

        if isinstance(data, dict):

            data_status = data.get(
                "status"
            )

            if data_status in STATUS_PRIORITY:
                return data_status

            nested = data.get(
                "result"
            )

            if isinstance(nested, dict):

                nested_status = nested.get(
                    "status"
                )

                if nested_status in STATUS_PRIORITY:
                    return nested_status

        if wrapper_status == "COMPLETED":
            return "UNKNOWN"

        return "UNKNOWN"

    def calculate_audit_status(
        self,
        results: dict[str, Any],
    ) -> str:

        statuses = []

        for result in results.values():

            statuses.append(
                self.extract_service_status(
                    result
                )
            )

        return self.aggregate_status(
            statuses
        )

    # ---------------------------------------------------------
    # JOB MANAGEMENT
    # ---------------------------------------------------------

    def create_job(
        self,
        site_code: str,
    ) -> str:

        job_id = str(
            uuid.uuid4()
        )

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

        self._save_job(self.jobs[job_id])
        return job_id

    def get_job(
        self,
        job_id: str,
    ):

        return self.jobs.get(
            job_id
        )

    # ---------------------------------------------------------
    # ZABBIX DISCOVERY
    # ---------------------------------------------------------

    async def _discover(
        self,
        site_code: str,
    ):

        async with httpx.AsyncClient(
            timeout=60
        ) as client:

            response = await client.post(
                f"{ZABBIX_SERVICE_URL}/discover",
                json={
                    "site_code": site_code
                },
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

            response = await client.post(
                url,
                json=payload,
                timeout=300,
            )

            if response.is_success:

                data = response.json()

                return {
                    "service": service_name,
                    "status": "COMPLETED",
                    "data": data,
                }

            return {
                "service": service_name,
                "status": "FAILED",
                "error": response.text,
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

    def build_summary(
        self,
        results: dict[str, Any],
    ) -> dict:

        service_statuses = {}

        for service_name, result in results.items():

            service_statuses[
                service_name
            ] = self.extract_service_status(
                result
            )

        statuses = list(
            service_statuses.values()
        )

        return {
            "service_count": len(
                service_statuses
            ),
            "critical": sum(
                1
                for status in statuses
                if status == "CRITICAL"
            ),
            "warning": sum(
                1
                for status in statuses
                if status == "WARNING"
            ),
            "unknown": sum(
                1
                for status in statuses
                if status == "UNKNOWN"
            ),
            "not_available": sum(
                1
                for status in statuses
                if status == "NOT_AVAILABLE"
            ),
            "pass": sum(
                1
                for status in statuses
                if status == "PASS"
            ),
            "services": service_statuses,
        }

    # ---------------------------------------------------------
    # REPORT GENERATION
    # ---------------------------------------------------------

    async def _generate_report(
        self,
        job: dict[str, Any],
    ) -> None:

        payload = {
            "site_code": job["site_code"],
            "results": job["results"],
        }

        try:

            async with httpx.AsyncClient(
                timeout=120
            ) as client:

                response = await client.post(
                    f"{REPORT_SERVICE_URL}/generate",
                    json=payload,
                )

                response.raise_for_status()

                report = response.json()

                job["report"] = report
                job["report_error"] = None

        except Exception as exc:

            # Report generation must NOT invalidate
            # an otherwise completed audit.
            job["report"] = None
            job["report_error"] = str(exc)

    # ---------------------------------------------------------
    # RUN COMPLETE AUDIT
    # ---------------------------------------------------------

    async def run_job(
        self,
        job_id: str,
    ):

        job = self.jobs[job_id]

        site_code = job[
            "site_code"
        ]

        try:

            # =================================================
            # PHASE 1 - DISCOVERY
            # =================================================

            job["status"] = "DISCOVERY"
            self._save_job(job)

            discovery = await self._discover(
                site_code
            )

            job["discovery"] = discovery
            self._save_job(job)

            # =================================================
            # PHASE 2 - SERVICES
            # =================================================

            job["status"] = "RUNNING"
            self._save_job(job)

            async with httpx.AsyncClient() as client:

                cisco_task = self._call_service(
                    client,
                    f"{CISCO_SERVICE_URL}/check",
                    {
                        "site_code": site_code,
                        "devices":
                            discovery.get(
                                "devices",
                                [],
                            ),
                    },
                    "cisco",
                )

                ericsson_task = self._call_service(
                    client,
                    f"{ERICSSON_SERVICE_URL}/check",
                    {
                        "site_code": site_code,
                        "basebands":
                            discovery.get(
                                "basebands",
                                [],
                            ),
                    },
                    "ericsson",
                )

                radio_task = self._call_service(
                    client,
                    f"{RADIO_SERVICE_URL}/analyze",
                    {
                        "site_code": site_code,
                        "links":
                            discovery.get(
                                "radio_links",
                                [],
                            ),
                    },
                    "radio",
                )

                results = await asyncio.gather(
                    cisco_task,
                    ericsson_task,
                    radio_task,
                )

            # =================================================
            # PHASE 3 - COLLECT RESULTS
            # =================================================

            for result in results:

                service_name = result[
                    "service"
                ]

                job["results"][
                    service_name
                ] = result

            # =================================================
            # PHASE 4 - HEALTH AGGREGATION
            # =================================================

            job["audit_status"] = (
                self.calculate_audit_status(
                    job["results"]
                )
            )

            job["summary"] = (
                self.build_summary(
                    job["results"]
                )
            )

            # =================================================
            # EXECUTION COMPLETED
            # =================================================

            job["status"] = "COMPLETED"

            # =================================================
            # PHASE 5 - AUTOMATIC EXCEL REPORT
            # =================================================

            await self._generate_report(
                job
            )
            self._save_job(job)

        except Exception as exc:

            job["status"] = "FAILED"

            job["audit_status"] = "CRITICAL"

            job["error"] = str(exc)

            job["summary"] = {
                "service_count": len(
                    job.get(
                        "results",
                        {}
                    )
                ),
                "critical": 1,
                "warning": 0,
                "unknown": 0,
                "not_available": 0,
                "pass": 0,
                "services": {},
            }
            self._save_job(job)

        return job
