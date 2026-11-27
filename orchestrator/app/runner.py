from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


load_dotenv("/opt/pop-audit/config/.env", override=False)

ZABBIX_SERVICE_URL = os.getenv("ZABBIX_SERVICE_URL", "http://zabbix-service:8002")
CISCO_SERVICE_URL = os.getenv("CISCO_SERVICE_URL", "http://cisco-service:8003")
ERICSSON_SERVICE_URL = os.getenv("ERICSSON_SERVICE_URL", "http://ericsson-service:8004")
RADIO_SERVICE_URL = os.getenv("RADIO_SERVICE_URL", "http://radio-service:8005")
REPORT_SERVICE_URL = os.getenv("REPORT_SERVICE_URL", "http://report-service:8006")
POP_AUDIT_DB_PATH = Path(os.getenv(
    "POP_AUDIT_DB_PATH", "/opt/pop-audit/data/jobs.sqlite3"
))

STATUS_PRIORITY = {
    "CRITICAL": 5,
    "WARNING": 4,
    "UNKNOWN": 3,
    "NOT_AVAILABLE": 2,
    "PASS": 1,
    "NOT_EXISTS": 0,
}


class AuditRunner:
    def __init__(self, database_path: str | Path | None = None):
        self.jobs: dict[str, dict[str, Any]] = {}
        self.database_path = Path(database_path or POP_AUDIT_DB_PATH)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()
        self._load_jobs()

    def _connect_database(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize_database(self) -> None:
        with self._connect_database() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_jobs (
                    job_id TEXT PRIMARY KEY,
                    site_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def _load_jobs(self) -> None:
        with self._connect_database() as connection:
            rows = connection.execute(
                "SELECT job_id, payload_json FROM audit_jobs"
            ).fetchall()
        for job_id, payload in rows:
            try:
                job = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                continue
            # A process restart cannot resume in-flight in-memory tasks.
            # Preserve the job record and mark it explicitly as interrupted.
            if job.get("status") in {"QUEUED", "DISCOVERY", "RUNNING"}:
                job["status"] = "FAILED"
                job["audit_status"] = "UNKNOWN"
                job["error"] = "Audit process restarted before the job completed."
                self.jobs[job_id] = job
                self._persist_job(job)
            else:
                self.jobs[job_id] = job

    def _persist_job(self, job: dict[str, Any]) -> None:
        payload = json.dumps(job, ensure_ascii=False, default=str)
        with self._connect_database() as connection:
            connection.execute(
                """
                INSERT INTO audit_jobs (job_id, site_code, status, updated_at, payload_json)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    site_code=excluded.site_code,
                    status=excluded.status,
                    updated_at=CURRENT_TIMESTAMP,
                    payload_json=excluded.payload_json
                """,
                (
                    str(job["job_id"]),
                    str(job["site_code"]),
                    str(job["status"]),
                    payload,
                ),
            )
            connection.commit()

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
            # Connection/command failures are not evidence of a physical fault.
            return "UNKNOWN"
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

    @staticmethod
    def _service_data(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        return data if isinstance(data, dict) else result

    def _build_categories(
        self,
        discovery: dict[str, Any] | None,
        results: dict[str, Any],
    ) -> dict[str, str]:
        discovery = discovery or {}
        cisco = self._service_data(results.get("cisco"))
        ericsson = self._service_data(results.get("ericsson"))
        radio = self._service_data(results.get("radio"))

        cisco_results = cisco.get("results") or []
        switches = cisco.get("switches")
        if not isinstance(switches, list):
            switches = [
                item for item in cisco_results
                if str(item.get("device_type", "")).lower() != "ncs540"
            ]
        ncs_results = cisco.get("ncs_devices")
        if not isinstance(ncs_results, list):
            ncs_results = [
                item for item in cisco_results
                if str(item.get("device_type", "")).lower() == "ncs540"
            ]

        bb_results = {
            str(item.get("zabbix_hostid")): item
            for item in (ericsson.get("results") or [])
            if item.get("zabbix_hostid")
        }
        discovered_basebands = discovery.get("basebands") or []
        bb_statuses = {}
        for fallback_name, slot in (("BB1", 0), ("BB2", 1)):
            bb = discovered_basebands[slot] if len(discovered_basebands) > slot else {}
            name = bb.get("name") or fallback_name
            if bb.get("exists") is False or not bb.get("zabbix_hostid"):
                status = bb.get("status") or "NOT_EXISTS"
            else:
                result = bb_results.get(str(bb.get("zabbix_hostid")))
                status = result.get("status", "UNKNOWN") if result else "UNKNOWN"
            bb_statuses[name] = status

        links = radio.get("links") or []
        by_type = {}
        for radio_type, key in (
            ("EBAND", "EBand"),
            ("RTN", "RTN"),
            ("INTRACOM", "Intracom"),
            ("NRAY", "NRay"),
        ):
            matching = [
                item.get("status", "UNKNOWN")
                for item in links
                if str(item.get("link_type") or item.get("type") or "").upper() == radio_type
            ]
            by_type[key] = self.aggregate_status(matching) if matching else "NOT_EXISTS"

        return {
            "Cisco Switch": self.aggregate_status([
                item.get("status", "UNKNOWN") for item in switches
            ]) if switches else "NOT_EXISTS",
            "BB1": bb_statuses.get("BB1", "NOT_EXISTS"),
            "BB2": bb_statuses.get("BB2", "NOT_EXISTS"),
            "NCS 540": self.aggregate_status([
                item.get("status", "UNKNOWN") for item in ncs_results
            ]) if ncs_results else "NOT_EXISTS",
            "EBand": by_type["EBand"],
            "Huawei RTN": by_type["RTN"],
            "Intracom": by_type["Intracom"],
            "NRay": by_type["NRay"],
        }

    def calculate_audit_status(
        self,
        results: dict[str, Any],
        discovery: dict[str, Any] | None = None,
    ) -> str:
        categories = self._build_categories(discovery, results)
        applicable = [
            status for status in categories.values()
            if status != "NOT_EXISTS"
        ]
        return self.aggregate_status(applicable)

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
        return self.jobs.get(job_id)

    async def _discover(self, site_code: str):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{ZABBIX_SERVICE_URL}/discover",
                json={"site_code": site_code},
            )
            response.raise_for_status()
            return response.json()

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
                "error": response.text,
            }
        except Exception as exc:
            return {
                "service": service_name,
                "status": "FAILED",
                "error": str(exc),
            }

    def build_summary(
        self,
        results: dict[str, Any],
        discovery: dict[str, Any] | None = None,
    ) -> dict:
        service_statuses = {
            name: self.extract_service_status(result)
            for name, result in results.items()
        }
        categories = self._build_categories(discovery, results)
        statuses = list(categories.values())
        return {
            "service_count": len(service_statuses),
            "category_count": len(categories),
            "critical": sum(status == "CRITICAL" for status in statuses),
            "warning": sum(status == "WARNING" for status in statuses),
            "unknown": sum(status == "UNKNOWN" for status in statuses),
            "not_available": sum(status == "NOT_AVAILABLE" for status in statuses),
            "not_exists": sum(status == "NOT_EXISTS" for status in statuses),
            "pass": sum(status == "PASS" for status in statuses),
            "services": service_statuses,
            "categories": categories,
        }

    async def _generate_report(self, job: dict[str, Any]) -> None:
        payload = {
            "site_code": job["site_code"],
            "discovery": job.get("discovery") or {},
            "results": job["results"],
            "summary": job.get("summary") or {},
            "audit_status": job.get("audit_status"),
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
            job["report"] = None
            job["report_error"] = str(exc)
        self._persist_job(job)

    async def run_job(self, job_id: str):
        job = self.jobs[job_id]
        site_code = job["site_code"]
        try:
            job["status"] = "DISCOVERY"
            self._persist_job(job)
            discovery = await self._discover(site_code)
            job["discovery"] = discovery
            job["status"] = "RUNNING"
            self._persist_job(job)

            async with httpx.AsyncClient() as client:
                tasks = [
                    self._call_service(
                        client,
                        f"{CISCO_SERVICE_URL}/check",
                        {
                            "site_code": site_code,
                            "devices": discovery.get("devices", []),
                            "ncs_devices": discovery.get("ncs_devices", []),
                        },
                        "cisco",
                    ),
                    self._call_service(
                        client,
                        f"{ERICSSON_SERVICE_URL}/check",
                        {
                            "site_code": site_code,
                            "basebands": discovery.get("basebands", []),
                        },
                        "ericsson",
                    ),
                    self._call_service(
                        client,
                        f"{RADIO_SERVICE_URL}/analyze",
                        {
                            "site_code": site_code,
                            "links": discovery.get("radio_links", []),
                        },
                        "radio",
                    ),
                ]
                service_results = await asyncio.gather(*tasks)

            for result in service_results:
                job["results"][result["service"]] = result
            job["audit_status"] = self.calculate_audit_status(
                job["results"], discovery
            )
            job["summary"] = self.build_summary(
                job["results"], discovery
            )
            job["status"] = "COMPLETED"
            self._persist_job(job)
            await self._generate_report(job)
        except Exception as exc:
            job["status"] = "FAILED"
            job["audit_status"] = "UNKNOWN"
            job["error"] = str(exc)
            job["summary"] = self.build_summary(
                job.get("results", {}),
                job.get("discovery"),
            )
            self._persist_job(job)
        return job
