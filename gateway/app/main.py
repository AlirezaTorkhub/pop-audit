from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .runner import AuditRunner


app = FastAPI(
    title="POP Audit Gateway",
    version="1.2.0",
)


ZABBIX_SERVICE_URL = os.getenv("ZABBIX_SERVICE_URL", "http://127.0.0.1:8002")
CISCO_SERVICE_URL = os.getenv("CISCO_SERVICE_URL", "http://127.0.0.1:8003")
ERICSSON_SERVICE_URL = os.getenv("ERICSSON_SERVICE_URL", "http://127.0.0.1:8004")
RADIO_SERVICE_URL = os.getenv("RADIO_SERVICE_URL", "http://127.0.0.1:8005")
REPORT_SERVICE_URL = os.getenv("REPORT_SERVICE_URL", "http://127.0.0.1:8006")

runner = AuditRunner()

FRONTEND_DIR = Path(
    "/opt/pop-audit/gateway/frontend"
)

STATIC_DIR = FRONTEND_DIR / "static"


class AuditRequest(BaseModel):
    site_code: str


def get_json(
    url: str,
    timeout: int = 30,
) -> dict[str, Any]:

    response = requests.get(
        url,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.json()


def post_json(
    url: str,
    payload: dict,
    timeout: int = 30,
) -> dict[str, Any]:

    response = requests.post(
        url,
        json=payload,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.json()


def get_audit_from_runner(job_id: str) -> dict[str, Any]:
    audit = runner.get_job(job_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return audit


def ensure_report(
    audit: dict[str, Any],
) -> dict[str, Any]:

    if audit.get("status") != "COMPLETED":

        raise HTTPException(
            status_code=409,
            detail={
                "message": "Audit is not completed yet.",
                "status": audit.get("status"),
                "job_id": audit.get("job_id"),
            },
        )

    existing_report = audit.get(
        "report"
    )

    if (
        isinstance(existing_report, dict)
        and existing_report.get("filename")
    ):

        return existing_report

    payload = {
        "site_code": audit.get(
            "site_code"
        ),
        "results": audit.get(
            "results",
            {},
        ),
    }

    try:

        return post_json(
            f"{REPORT_SERVICE_URL}/generate",
            payload,
            timeout=120,
        )

    except requests.HTTPError as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                "Report generation failed: "
                f"{exc.response.text if exc.response else str(exc)}"
            ),
        )

    except requests.RequestException as exc:

        raise HTTPException(
            status_code=502,
            detail=f"Report service unavailable: {exc}",
        )


# ============================================================
# Static frontend
# ============================================================

if STATIC_DIR.exists():

    app.mount(
        "/static",
        StaticFiles(
            directory=str(STATIC_DIR)
        ),
        name="static",
    )


@app.get("/")
def index():

    index_file = FRONTEND_DIR / "index.html"

    if not index_file.exists():

        raise HTTPException(
            status_code=500,
            detail="Frontend files are missing.",
        )

    return FileResponse(
        index_file,
        media_type="text/html",
    )


# ============================================================
# Health
# ============================================================

@app.get("/health")
def health():

    services = {}

    for name, url in [
        ("zabbix", ZABBIX_SERVICE_URL),
        ("cisco", CISCO_SERVICE_URL),
        ("ericsson", ERICSSON_SERVICE_URL),
        ("radio", RADIO_SERVICE_URL),
        ("report", REPORT_SERVICE_URL),
    ]:

        try:

            response = requests.get(
                f"{url}/health",
                timeout=5,
            )

            services[name] = (
                "UP"
                if response.ok
                else "DOWN"
            )

        except Exception:

            services[name] = "DOWN"

    return {
        "service": "gateway",
        "status": (
            "ok"
            if all(
                value == "UP"
                for value in services.values()
            )
            else "degraded"
        ),
        "services": services,
    }


# ============================================================
# Audit
# ============================================================

@app.post("/audit")
async def create_audit(request: AuditRequest):
    site_code = request.site_code.strip()
    if not site_code:
        raise HTTPException(status_code=400, detail="Site code is required.")

    job_id = runner.create_job(site_code)
    asyncio.create_task(runner.run_job(job_id))

    return {
        "job_id": job_id,
        "site_code": site_code,
        "status": "QUEUED",
    }


@app.get("/audit/{job_id}/report/download")
def download_report(
    job_id: str,
):

    audit = get_audit_from_runner(
        job_id
    )

    report = ensure_report(
        audit
    )

    filename = report.get(
        "filename"
    )

    if not filename:

        raise HTTPException(
            status_code=502,
            detail="Report filename is missing.",
        )

    if (
        "/" in filename
        or "\\" in filename
        or filename in (".", "..")
        or not filename.endswith(".xlsx")
    ):

        raise HTTPException(
            status_code=502,
            detail="Invalid report filename.",
        )

    try:

        response = requests.get(
            f"{REPORT_SERVICE_URL}/download/{filename}",
            timeout=120,
        )

        response.raise_for_status()

    except requests.HTTPError as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                "Report download failed: "
                f"{exc.response.text if exc.response else str(exc)}"
            ),
        )

    except requests.RequestException as exc:

        raise HTTPException(
            status_code=502,
            detail=f"Report service unavailable: {exc}",
        )

    return Response(
        content=response.content,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition":
                f'attachment; filename="{filename}"'
        },
    )


@app.get("/audit/{job_id}/report")
def get_report(
    job_id: str,
):

    audit = get_audit_from_runner(
        job_id
    )

    report = ensure_report(
        audit
    )

    return {
        "job_id": job_id,
        "site_code": audit.get(
            "site_code"
        ),
        "status": audit.get(
            "status"
        ),
        "audit_status": audit.get(
            "audit_status"
        ),
        "report": report,
    }


@app.get("/audit/{job_id}")
def get_audit(
    job_id: str,
):

    return get_audit_from_runner(
        job_id
    )
