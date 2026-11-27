# POP Audit

POP Audit discovers devices from Zabbix and performs read-only checks for Cisco switches, Cisco NCS 540 (IOS XR), Ericsson Basebands, and outgoing radio links. Site Codes must be exactly four digits. Audit results are available from the web dashboard and as an Excel workbook.

## Architecture

| Service | Internal address | Responsibility |
|---|---:|---|
| Gateway | `gateway:8000` | Web UI and public API |
| Orchestrator | `orchestrator:8001` | Job lifecycle, service fan-out, aggregation, SQLite persistence |
| Zabbix | `zabbix-service:8002` | Inventory discovery, item metadata, numerical history, triggers |
| Cisco | `cisco-service:8003` | Cisco IOS and Cisco NCS 540 IOS XR read-only SSH checks |
| Ericsson | `ericsson-service:8004` | Remote Moshell session and Baseband checks |
| Radio | `radio-service:8005` | EBand, Huawei RTN, Intracom, and NRay analysis |
| Report | `report-service:8006` | Excel workbook generation and download |

The Compose file defines all seven services, including the required `orchestrator` service. The Gateway calls it over Docker DNS at `http://orchestrator:8001`; the Orchestrator calls the five backend services over their internal service names. Only the Gateway publishes a host port. The default is `18000:8000`; change `POP_AUDIT_HOST_PORT` to select another port.

## Deploy

1. Copy `config/.env.example` to `config/.env` on the deployment host.
2. Replace every `CHANGE_ME` value and the example Zabbix URL with the values for your environment. `MOSHELL_PATH` is the path to the Moshell executable on `MOSHELL_HOST` (the remote SSH host), not a path inside the Docker container.
3. Check the Zabbix group names. The defaults are:
   - `LTE-Backhaul-eNodeB`
   - `LTE-Backhaul-Switch`
   - `LTE-Backhaul-Switch-Aggregation`
   - `LTE-Backhaul-Radio`
   - `LTE-Backhaul-Radio-Huawei`
4. Start or update the containers:

```bash
docker compose --env-file config/.env config
docker compose --env-file config/.env up -d --build
docker compose ps
docker compose logs --tail=100 gateway orchestrator zabbix-service cisco-service ericsson-service radio-service report-service
```

Open `http://<server-address>:<POP_AUDIT_HOST_PORT>`. The default host port is `18000`.

Audit jobs are persisted by the Orchestrator alone in `./data/jobs.sqlite3` (the Gateway does not mount or open the SQLite database). Excel workbooks are persisted under `./reports`. Back up these directories as appropriate for your operational policy.

## Discovery and matching

- Zabbix is the source of truth for device inventory, groups, templates, interfaces, item metadata, values, timestamps, and triggers.
- BB1 is the Baseband whose four-digit identifier exactly matches the entered Site Code.
- BB2 is a distinct Baseband candidate with the same final three digits and a different leading digit. A 7xxx/8xxx candidate is never promoted to BB1 when the exact device is absent.
- Ambiguous device matches are returned as `UNKNOWN`; missing required groups are `NOT_AVAILABLE`.
- Primary Cisco switches are selected from the primary switch group for the exact Site Code. MikroTik devices are not presented as Cisco switches.
- NCS 540 devices are selected from the aggregation group and associated using shared POP location tokens from Zabbix metadata. Multiple candidates are reported as ambiguous.
- Only radio links whose left/source endpoint is the requested POP are included. Reverse/incoming links are excluded. There is no static destination whitelist.

## Health interpretation

The API distinguishes `PASS`, `WARNING`, `CRITICAL`, `UNKNOWN`, `NOT_AVAILABLE`, and `NOT_EXISTS`.

- `NOT_EXISTS` means inventory discovery did not find an optional component.
- `NOT_AVAILABLE` means the required source/group/metric was not available.
- `UNKNOWN` means the source exists but matching, parsing, history, or audit evidence is insufficient.
- Missing measurements are not converted to zero and do not become a healthy result.

### Ericsson

The Moshell command sequence remains `lt all`, `st cel`, `alt`, `get . clock`, `q`. Cell health requires Admin `UNLOCKED` and Operational `ENABLED`. The clock check requires `radioClockState 6 (RNT_TIME_LOCKED)`. Door and AC/power/cooling-related alarms affect field health; unrelated alarms remain visible as context.

### Cisco IOS and NCS 540

Cisco IOS checks use the read-only `show` command profile. An administratively disabled interface is not treated as a physical failure. Other down/error-disabled states are surfaced. Gigabit interfaces negotiating at 100 Mbps are flagged. CRC and error counters remain null when the device did not return the counter; only measured positive CRC values appear in the CRC Problems sheet.

NCS 540 uses a dedicated Netmiko `cisco_xr` profile and only the supported IOS XR commands `show interfaces description`, `show interfaces`, and `show logging last 10`.

### Radio

- EBand RX: below -45 dBm is CRITICAL; -45 to below -37 dBm is WARNING; -37 dBm and above is PASS.
- EBand difference: strictly below 7 dB is PASS; 7 dB or above is CRITICAL.
- Huawei RTN `modulation_huawei[...] ` items are evaluated from numerical Zabbix history for the last `RADIO_MODULATION_HISTORY_HOURS` (default 12). The Zabbix item `value_type` chooses the numeric history table. Stale/insufficient history is never treated as healthy.
- Intracom and NRay metrics preserve their Zabbix keys, values, units, timestamps and linked trigger context. No generic traffic threshold is invented.

## API

- `GET /health` — Gateway and dependency health.
- `POST /audit` — Start an audit with JSON body `{"site_code":"2488"}`.
- `GET /audit/{job_id}` — Poll the job.
- `GET /audit/{job_id}/report` — Resolve the workbook metadata.
- `GET /audit/{job_id}/report/download` — Download the Excel workbook.

The Zabbix service also exposes inventory/debug endpoints and a validated numerical-history endpoint at `GET /host/{hostid}/history`.

## CI and local checks

GitHub Actions runs service-local pytest suites, Python compilation, frontend JavaScript syntax validation, Docker Compose configuration validation, and builds all service images. The tests use fixtures/mocks and do not connect to live switches, Basebands, or Zabbix.

To run one service's suite locally:

```bash
cd radio-service
python -m pip install -r requirements.txt pytest
python -m pytest -q tests
```

## Credential handling

Do not commit `config/.env`, SSH passwords, tokens, or private keys. Supply them through the deployment host's untracked `config/.env` file. Credentials that were present in earlier public commits must be rotated; deleting the file in a later commit does not remove it from Git history.
