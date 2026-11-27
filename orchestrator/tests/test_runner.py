from app.runner import AuditRunner


def test_absent_optional_components_do_not_degrade_overall_health(tmp_path):
    runner = AuditRunner(tmp_path / "jobs.sqlite3")
    discovery = {
        "basebands": [
            {"name": "BB1", "exists": True, "zabbix_hostid": "bb1", "status": "UNKNOWN"},
            {"name": "BB2", "exists": False, "zabbix_hostid": None, "status": "NOT_EXISTS"},
        ],
        "devices": [{"zabbix_hostid": "sw1"}],
        "ncs_devices": [],
        "ncs_status": "NOT_EXISTS",
        "errors": [],
    }
    results = {
        "cisco": {
            "status": "COMPLETED",
            "data": {
                "status": "PASS",
                "switches": [{"status": "PASS"}],
                "ncs_devices": [],
                "results": [{"status": "PASS", "zabbix_hostid": "sw1"}],
            },
        },
        "ericsson": {
            "status": "COMPLETED",
            "data": {
                "status": "PASS",
                "results": [{"status": "PASS", "zabbix_hostid": "bb1"}],
            },
        },
        "radio": {
            "status": "COMPLETED",
            "data": {
                "status": "WARNING",
                "links": [{"link_type": "EBAND", "status": "WARNING"}],
            },
        },
    }

    categories = runner._build_categories(discovery, results)
    assert categories == {
        "Cisco Switch": "PASS",
        "BB1": "PASS",
        "BB2": "NOT_EXISTS",
        "NCS 540": "NOT_EXISTS",
        "EBand": "WARNING",
        "Huawei RTN": "NOT_EXISTS",
        "Intracom": "NOT_EXISTS",
        "NRay": "NOT_EXISTS",
    }
    assert runner.calculate_audit_status(results, discovery) == "WARNING"


def test_failed_backend_call_is_unknown_not_a_physical_critical():
    assert AuditRunner.extract_service_status({
        "service": "radio",
        "status": "FAILED",
        "error": "service unavailable",
    }) == "UNKNOWN"


def test_jobs_are_persisted_and_restart_interruption_is_explicit(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    first = AuditRunner(database)
    job_id = first.create_job("2488")
    assert first.get_job(job_id)["status"] == "QUEUED"

    restarted = AuditRunner(database)
    job = restarted.get_job(job_id)
    assert job is not None
    assert job["status"] == "FAILED"
    assert "restarted" in job["error"]
