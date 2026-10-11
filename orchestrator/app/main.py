import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .runner import AuditRunner


app = FastAPI(
    title="POP Audit - Orchestrator",
    version="1.0.0",
)

runner = AuditRunner()


class AuditRequest(BaseModel):
    site_code: str


@app.get("/health")
def health():

    return {
        "service": "orchestrator",
        "status": "ok",
    }


@app.post("/audit")
async def create_audit(
    request: AuditRequest,
):

    site_code = request.site_code.strip()

    if not site_code:
        raise HTTPException(
            status_code=400,
            detail="Site code is required.",
        )

    job_id = runner.create_job(
        site_code
    )

    asyncio.create_task(
        runner.run_job(job_id)
    )

    return {
        "job_id": job_id,
        "site_code": site_code,
        "status": "QUEUED",
    }


@app.get("/audit/{job_id}")
def get_audit(job_id: str):

    job = runner.get_job(job_id)

    if not job:

        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    return job
