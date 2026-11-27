from openpyxl import load_workbook

import app.main as report


def test_workbook_contains_eight_categories_basebands_ncs_and_unified_links(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path)
    results = {
        "cisco": {
            "status": "COMPLETED",
            "data": {
                "status": "PASS",
                "results": [],
                "switches": [],
                "ncs_devices": [],
            },
        },
        "ericsson": {
            "status": "COMPLETED",
            "data": {"status": "PASS", "results": []},
        },
        "radio": {
            "status": "COMPLETED",
            "data": {
                "status": "PASS",
                "links": [{
                    "link_type": "EBAND",
                    "name": "Bijan-2488-To-Kurosh-EBand",
                    "source_site": "2488",
                    "destination_name": "Kurosh",
                    "zabbix_hostid": "r1",
                    "status": "PASS",
                    "analysis": {"status": "PASS", "checks": {"difference": {"slots": []}}},
                }],
            },
        },
    }
    discovery = {
        "basebands": [
            {"name": "BB1", "exists": True, "hostname": "Bijan-2488", "ip": "192.0.2.1", "zabbix_hostid": "bb1"},
            {"name": "BB2", "exists": False, "status": "NOT_EXISTS"},
        ]
    }
    summary = {
        "categories": {
            "Cisco Switch": "PASS", "BB1": "PASS", "BB2": "NOT_EXISTS",
            "NCS 540": "NOT_EXISTS", "EBand": "PASS", "Huawei RTN": "NOT_EXISTS",
            "Intracom": "NOT_EXISTS", "NRay": "NOT_EXISTS",
        }
    }

    output, overall = report.create_workbook(
        "2488", results, discovery, summary, "PASS"
    )
    assert output.exists()
    assert overall == "PASS"

    workbook = load_workbook(output, read_only=True)
    assert {"Summary", "Basebands", "Cisco Switches", "NCS 540", "Links", "CRC Problems", "Device Logs"}.issubset(workbook.sheetnames)

    summary_sheet = workbook["Summary"]
    component_names = {
        summary_sheet.cell(row=row, column=1).value
        for row in range(8, 16)
    }
    assert component_names == {
        "Cisco Switch", "BB1", "BB2", "NCS 540",
        "EBand", "Huawei RTN", "Intracom", "NRay",
    }

    eband_sheet = workbook["EBand"]
    headers = [cell.value for cell in next(eband_sheet.iter_rows(min_row=1, max_row=1))]
    assert "Capacity Health" not in headers
    assert "Capacity Profile Input" in headers
    workbook.close()
