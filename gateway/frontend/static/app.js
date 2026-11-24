"use strict";

const state = {
    jobId: null,
    siteCode: null,
    timer: null,
    audit: null,
    report: null,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function rawStatus(value) {
    const status = String(value || "UNKNOWN").trim().toUpperCase();
    return [
        "PASS", "HEALTHY", "WARNING", "CRITICAL",
        "UNKNOWN", "NOT_AVAILABLE", "NOT_EXISTS",
    ].includes(status) ? status : "UNKNOWN";
}

function displayStatus(value) {
    const status = rawStatus(value);
    if (status === "PASS" || status === "HEALTHY") return "HEALTHY";
    if (status === "NOT_EXISTS") return "NOT EXISTS";
    if (status === "UNKNOWN" || status === "NOT_AVAILABLE") return "WARNING";
    return status;
}

function statusClass(value) {
    const status = displayStatus(value);
    if (status === "HEALTHY") return "healthy";
    if (status === "WARNING") return "warning";
    if (status === "CRITICAL") return "critical";
    if (status === "NOT EXISTS") return "not-exists";
    return "unknown";
}

function statusPill(value) {
    const label = displayStatus(value);
    return `<span class="status-pill status-${statusClass(value)}">${escapeHtml(label)}</span>`;
}

function statusDot(value) {
    const label = displayStatus(value);
    return `<span class="status-dot-inline status-${statusClass(value)}"></span><span>${escapeHtml(label)}</span>`;
}

function aggregateRawStatus(values) {
    const statuses = (values || []).map(rawStatus);
    if (!statuses.length) return "NOT_EXISTS";
    const rank = {
        CRITICAL: 5,
        WARNING: 4,
        UNKNOWN: 3,
        NOT_AVAILABLE: 3,
        PASS: 1,
        HEALTHY: 1,
        NOT_EXISTS: 0,
    };
    return statuses.reduce(
        (worst, value) => (rank[value] || 0) > (rank[worst] || 0) ? value : worst,
        "NOT_EXISTS"
    );
}

function metricCard(label, value, status = null) {
    const shown = value === null || value === undefined || value === "" ? "—" : value;
    return `
        <div class="metric-card">
            <div class="metric-label">${escapeHtml(label)}</div>
            <div class="metric-value">${status ? statusPill(status) : escapeHtml(shown)}</div>
        </div>
    `;
}

function setFormMessage(message, error = false) {
    const el = $("formMessage");
    if (!message) {
        el.classList.add("hidden");
        el.textContent = "";
        return;
    }
    el.textContent = message;
    el.classList.remove("hidden");
    el.classList.toggle("message-error", Boolean(error));
    el.classList.toggle("message-info", !error);
}

async function apiJson(url, options = {}) {
    const response = await fetch(url, options);
    const text = await response.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = null;
    }
    if (!response.ok) {
        const detail = data?.detail || text || `HTTP ${response.status}`;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
}

async function checkApiHealth() {
    const dot = $("apiStatusDot");
    const text = $("apiStatusText");
    try {
        const data = await apiJson("/health");
        const online = data?.status === "ok";
        dot.className = `status-dot ${online ? "up" : "down"}`;
        text.textContent = online ? "API ONLINE" : "API DEGRADED";
    } catch {
        dot.className = "status-dot down";
        text.textContent = "API OFFLINE";
    }
}

function setProgress(status) {
    const normalized = String(status || "").toUpperCase();
    const width = ({
        QUEUED: 5,
        DISCOVERY: 28,
        RUNNING: 68,
        COMPLETED: 100,
        FAILED: 100,
    })[normalized] || 5;

    $("progressBar").style.width = `${width}%`;
    $("phaseDiscovery").classList.toggle("phase-active", width >= 28);
    $("phaseRunning").classList.toggle("phase-active", width >= 68);
    $("phaseCompleted").classList.toggle("phase-active", width >= 100);
}

function updateJobBadge(status) {
    const normalized = String(status || "UNKNOWN").toUpperCase();
    $("jobStatusBadge").textContent = normalized;
    $("jobStatusBadge").className = `status-badge status-${statusClass(normalized)}`;
    setProgress(normalized);

    const messages = {
        QUEUED: "Audit job is queued.",
        DISCOVERY: "Discovering Basebands, switches, NCS and outgoing radio links...",
        RUNNING: "Running Ericsson, Cisco/NCS and radio checks...",
        COMPLETED: "Audit completed.",
        FAILED: "Audit failed. See the error message below.",
    };
    $("jobStatusText").textContent = messages[normalized] || normalized;
}

function resetResults() {
    state.audit = null;
    state.report = null;
    $("resultPanel").classList.add("hidden");
    $("componentStatusGrid").innerHTML = "";
    $("basebandGrid").innerHTML = "";
    $("ciscoPanels").innerHTML = "";
    $("ncsPanels").innerHTML = "";
    for (const id of ["ebandLinks", "rtnLinks", "intracomLinks", "nrayLinks"]) {
        $(id).innerHTML = "";
    }
    for (const id of ["ebandStatus", "rtnStatus", "intracomStatus", "nrayStatus"]) {
        $(id).textContent = "UNKNOWN";
        $(id).className = "status-pill status-unknown";
    }
    $("overallStatus").textContent = "UNKNOWN";
    $("overallStatus").className = "status-pill status-unknown";
    $("excelBtn").disabled = true;
    $("pdfBtn").disabled = true;
}

function resultData(wrapper) {
    if (wrapper && wrapper.data && typeof wrapper.data === "object") return wrapper.data;
    return wrapper && typeof wrapper === "object" ? wrapper : {};
}

function serviceStatus(wrapper) {
    const data = resultData(wrapper);
    if (data.status) return rawStatus(data.status);
    if (wrapper?.status === "FAILED") return "CRITICAL";
    return "UNKNOWN";
}

function getRadioType(link) {
    const raw = String(link.link_type || link.type || "").toUpperCase().replaceAll(/[^A-Z]/g, "");
    if (raw.includes("EBAND")) return "EBAND";
    if (raw.includes("RTN") || raw.includes("HUAWEI")) return "RTN";
    if (raw.includes("INTRACOM") || raw.includes("INTRACOME") || raw.includes("INTROCOM")) return "INTRACOM";
    if (raw.includes("NRAY")) return "NRAY";
    return "UNKNOWN";
}

function renderStatusOverview(audit) {
    const results = audit.results || {};
    const ciscoData = resultData(results.cisco);
    const ericssonData = resultData(results.ericsson);
    const radioData = resultData(results.radio);

    const devices = Array.isArray(ciscoData.results) ? ciscoData.results : [];
    const basebands = Array.isArray(ericssonData.results) ? ericssonData.results : [];
    const links = Array.isArray(radioData.links) ? radioData.links : [];

    const normalSwitches = devices.filter(device =>
        !["ncs", "ncs540", "ncs_540"].includes(String(device.device_type || "").toLowerCase())
        && String(device.role || "primary_switch").toLowerCase() !== "ncs_aggregation"
    );
    const ncsDevices = devices.filter(device =>
        ["ncs", "ncs540", "ncs_540"].includes(String(device.device_type || "").toLowerCase())
        || String(device.role || "").toLowerCase() === "ncs_aggregation"
    );

    const bb1 = basebands.find(bb => String(bb.role || "").toUpperCase() === "BB1") || basebands[0];
    const bb2 = basebands.find(bb => String(bb.role || "").toUpperCase() === "BB2");
    const radiosOf = (type) => links.filter(link => getRadioType(link) === type);

    const categories = [
        {
            title: "Cisco Switch",
            description: normalSwitches.length ? `${normalSwitches.length} device(s) discovered` : "No site-specific Cisco switch",
            status: aggregateRawStatus(normalSwitches.map(device => device.status)),
        },
        {
            title: "Baseband 1",
            description: bb1?.hostname || "No BB1 discovered",
            status: bb1 ? bb1.status : "NOT_EXISTS",
        },
        {
            title: "Baseband 2",
            description: bb2?.hostname || "No matching second Baseband",
            status: bb2 ? bb2.status : "NOT_EXISTS",
        },
        {
            title: "NCS 540",
            description: ncsDevices.length ? ncsDevices.map(device => device.hostname).join(", ") : "No associated NCS",
            status: aggregateRawStatus(ncsDevices.map(device => device.status)),
        },
        {
            title: "EBand Radios",
            description: `${radiosOf("EBAND").length} outgoing link(s)`,
            status: aggregateRawStatus(radiosOf("EBAND").map(link => link.status)),
        },
        {
            title: "RTN Radios",
            description: `${radiosOf("RTN").length} outgoing link(s)`,
            status: aggregateRawStatus(radiosOf("RTN").map(link => link.status)),
        },
        {
            title: "Intracom Radios",
            description: `${radiosOf("INTRACOM").length} outgoing link(s)`,
            status: aggregateRawStatus(radiosOf("INTRACOM").map(link => link.status)),
        },
        {
            title: "NRay Radios",
            description: `${radiosOf("NRAY").length} outgoing link(s)`,
            status: aggregateRawStatus(radiosOf("NRAY").map(link => link.status)),
        },
    ];

    $("componentStatusGrid").innerHTML = categories.map(item => `
        <article class="component-card ${statusClass(item.status)}">
            <div class="component-name">${escapeHtml(item.title)}</div>
            <div class="component-state">${statusPill(item.status)}</div>
            <div class="component-meta">${escapeHtml(item.description)}</div>
        </article>
    `).join("");

    const existingStatuses = categories
        .map(item => item.status)
        .filter(status => rawStatus(status) !== "NOT_EXISTS");
    const overall = aggregateRawStatus(existingStatuses);
    $("overallStatus").textContent = displayStatus(overall);
    $("overallStatus").className = `status-pill status-${statusClass(overall)}`;

    return { ciscoData, ericssonData, radioData, devices, basebands, links };
}

function formatTimestamp(value) {
    if (value === null || value === undefined || value === "") return "—";
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric > 1000000000 && numeric < 9999999999) {
        return new Date(numeric * 1000).toLocaleString();
    }
    return String(value);
}

function renderCells(cells) {
    if (!Array.isArray(cells) || !cells.length) {
        return '<div class="inline-empty">No cell records were returned.</div>';
    }
    const rows = cells.map(cell => `
        <tr>
            <td>${escapeHtml(cell.proxy)}</td>
            <td>${escapeHtml(cell.mo)}</td>
            <td>${escapeHtml(cell.admin_state)}</td>
            <td>${escapeHtml(cell.oper_state)}</td>
            <td>${statusPill(cell.status)}</td>
        </tr>
    `).join("");
    return `
        <div class="table-wrap">
            <table>
                <thead><tr><th>Proxy</th><th>Cell / MO</th><th>Admin</th><th>Operational</th><th>Status</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function renderAlarmTable(alarms) {
    if (!Array.isArray(alarms) || !alarms.length) {
        return '<div class="inline-empty">No matching active alarms.</div>';
    }
    return `
        <div class="table-wrap">
            <table>
                <thead><tr><th>Severity</th><th>Timestamp</th><th>Alarm</th><th>Additional Information</th></tr></thead>
                <tbody>
                    ${alarms.map(alarm => `
                        <tr>
                            <td>${escapeHtml(alarm.severity)}</td>
                            <td>${escapeHtml(alarm.timestamp)}</td>
                            <td>${escapeHtml(alarm.problem)}</td>
                            <td>${escapeHtml(alarm.additional_text)}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>
    `;
}

function renderBasebandPanel(device, role) {
    if (!device) {
        return `
            <article class="bb-card not-exists-card">
                <div class="bb-heading">
                    <div><p class="eyebrow">ERICSSON BASEBAND</p><h3>${role}</h3></div>
                    ${statusPill("NOT_EXISTS")}
                </div>
                <div class="not-exists-body">This POP does not have a discovered ${role}.</div>
            </article>
        `;
    }

    const checks = device.checks || {};
    const cells = checks.cells || {};
    const alarms = checks.alarms || {};
    const clock = checks.clock || {};
    const door = checks.door_alarm || { status: "UNKNOWN", count: 0, alarms: [] };
    const ac = checks.ac_alarm || { status: "UNKNOWN", count: 0, alarms: [] };

    return `
        <article class="bb-card">
            <div class="bb-heading">
                <div>
                    <p class="eyebrow">ERICSSON BASEBAND</p>
                    <h3>${escapeHtml(role)}</h3>
                    <div class="device-hostname">${escapeHtml(device.hostname)}</div>
                    <div class="muted small-text">${escapeHtml(device.ip || "IP unavailable")} · Host ID ${escapeHtml(device.zabbix_hostid || "—")}</div>
                </div>
                ${statusPill(device.status)}
            </div>

            <div class="metric-grid">
                ${metricCard("Cell Count", cells.count)}
                ${metricCard("Cells", cells.status, cells.status)}
                ${metricCard("Clock", clock.state || "—", clock.status)}
                ${metricCard("Clock Value", clock.value)}
                ${metricCard("Door Alarm", door.count ?? 0, door.status)}
                ${metricCard("AC Alarm", ac.count ?? 0, ac.status)}
                ${metricCard("Total Alarms", alarms.total ?? 0)}
                ${metricCard("Critical Alarms", alarms.critical ?? 0)}
            </div>

            <div class="subsection">
                <h4>Cell Status</h4>
                ${renderCells(cells.cells)}
            </div>

            <div class="alarm-grid">
                <div class="alarm-card">
                    <div class="subsection-heading"><h4>Door Alarm</h4>${statusPill(door.status)}</div>
                    ${renderAlarmTable(door.alarms)}
                </div>
                <div class="alarm-card">
                    <div class="subsection-heading"><h4>AC / Power Alarm</h4>${statusPill(ac.status)}</div>
                    ${renderAlarmTable(ac.alarms)}
                </div>
            </div>
        </article>
    `;
}

function renderBasebands(basebands) {
    const bb1 = basebands.find(bb => String(bb.role || "").toUpperCase() === "BB1") || basebands[0] || null;
    const bb2 = basebands.find(bb => String(bb.role || "").toUpperCase() === "BB2") || null;
    $("basebandGrid").innerHTML = [
        renderBasebandPanel(bb1, "BASEBAND 1"),
        renderBasebandPanel(bb2, "BASEBAND 2"),
    ].join("");
}

function renderInterfaceTable(interfaces) {
    if (!Array.isArray(interfaces) || !interfaces.length) {
        return '<div class="inline-empty">No interface rows were parsed. Verify command output and parser support.</div>';
    }

    return `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Interface</th><th>Description</th><th>Admin / Oper</th>
                        <th>Health</th><th>Speed</th><th>CRC</th><th>Input Errors</th><th>Output Errors</th>
                    </tr>
                </thead>
                <tbody>
                    ${interfaces.map(item => `
                        <tr>
                            <td class="mono">${escapeHtml(item.interface)}</td>
                            <td>${escapeHtml(item.description || item.name || "—")}</td>
                            <td>${escapeHtml([item.status_raw, item.protocol].filter(Boolean).join(" / ") || "—")}</td>
                            <td>${statusPill(item.health)}</td>
                            <td>${escapeHtml(item.speed || item.bandwidth_kbps || "—")}</td>
                            <td>${item.crc === null || item.crc === undefined ? "—" : escapeHtml(item.crc)}</td>
                            <td>${item.input_errors === null || item.input_errors === undefined ? "—" : escapeHtml(item.input_errors)}</td>
                            <td>${item.output_errors === null || item.output_errors === undefined ? "—" : escapeHtml(item.output_errors)}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>
    `;
}

function renderCrcProblems(interfaceCheck) {
    const explicit = interfaceCheck?.problems?.crc;
    const problems = Array.isArray(explicit)
        ? explicit
        : (interfaceCheck?.data || []).filter(item => item.crc !== null && item.crc !== undefined && Number(item.crc) > 0);

    if (!problems.length) return "";
    return `
        <div class="problems-box">
            <div class="subsection-heading">
                <h4>Problems · CRC Detected</h4>
                <span class="status-pill status-warning">${problems.length} interface(s)</span>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Interface</th><th>Description</th><th>CRC Counter</th></tr></thead>
                    <tbody>
                        ${problems.map(item => `
                            <tr>
                                <td class="mono">${escapeHtml(item.interface)}</td>
                                <td>${escapeHtml(item.description || "—")}</td>
                                <td class="numeric problem-number">${escapeHtml(item.crc)}</td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function renderLogs(logging) {
    const logs = logging?.latest || logging?.recent_10 || logging?.recent || [];
    if (!Array.isArray(logs) || !logs.length) {
        return '<div class="inline-empty">No log entries were returned by the device.</div>';
    }

    const rows = logs.map(log => {
        if (typeof log === "string") {
            return `<tr><td colspan="3" class="log-message">${escapeHtml(log)}</td></tr>`;
        }
        return `
            <tr>
                <td>${escapeHtml(log.timestamp || "—")}</td>
                <td>${escapeHtml(log.severity || "—")}</td>
                <td class="log-message">${escapeHtml(log.message || log.raw || "—")}</td>
            </tr>
        `;
    }).join("");

    return `
        <div class="table-wrap">
            <table>
                <thead><tr><th>Timestamp</th><th>Severity</th><th>Log Entry</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function renderNetworkDevice(device, isNcs) {
    const checks = device.checks || {};
    const interfaces = checks.interfaces || {};
    const logging = checks.logging || {};
    const title = isNcs ? "NCS 540" : "Cisco Switch";
    const commandName = isNcs ? "show logging last 10" : "show logging";

    return `
        <article class="device-card">
            <div class="device-card-heading">
                <div>
                    <p class="eyebrow">${escapeHtml(title)}</p>
                    <h3>${escapeHtml(device.hostname || "Unnamed device")}</h3>
                    <p class="muted small-text">${escapeHtml(device.ip || "IP unavailable")} · Host ID ${escapeHtml(device.zabbix_hostid || "—")}</p>
                </div>
                ${statusPill(device.status)}
            </div>

            <div class="metric-grid compact-grid">
                ${metricCard("SSH Connection", checks.connectivity?.status || (device.error ? "UNKNOWN" : "PASS"), checks.connectivity?.status || (device.error ? "UNKNOWN" : "PASS"))}
                ${metricCard("Interfaces", interfaces.count ?? (interfaces.data || []).length)}
                ${metricCard("Interface Health", interfaces.status || "UNKNOWN", interfaces.status || "UNKNOWN")}
                ${metricCard("CRC Problems", interfaces.problems?.crc_count ?? (interfaces.data || []).filter(row => Number(row.crc) > 0).length)}
                ${metricCard("Log Health", logging.status || "UNKNOWN", logging.status || "UNKNOWN")}
            </div>

            <div class="subsection">
                <h4>Interface Status</h4>
                ${renderInterfaceTable(interfaces.data || [])}
            </div>

            ${renderCrcProblems(interfaces)}

            <div class="subsection">
                <div class="subsection-heading">
                    <h4>Latest Ten Logs</h4>
                    <span class="command-label">${escapeHtml(commandName)}</span>
                </div>
                ${renderLogs(logging)}
            </div>

            ${device.error ? `<div class="error-box">${escapeHtml(device.error)}</div>` : ""}
        </article>
    `;
}

function renderNetworkDevices(devices, isNcs, containerId) {
    const selected = (devices || []).filter(device => {
        const type = String(device.device_type || "").toLowerCase();
        const role = String(device.role || "").toLowerCase();
        const isNcsDevice = ["ncs", "ncs540", "ncs_540"].includes(type) || role === "ncs_aggregation";
        return isNcs ? isNcsDevice : !isNcsDevice;
    });

    if (!selected.length) {
        $(containerId).innerHTML = `
            <div class="not-exists-card empty-card">
                <span class="status-pill status-not-exists">NOT EXISTS</span>
                <p>${isNcs ? "No NCS 540 was confidently associated with this POP." : "No site-specific Cisco switch was discovered."}</p>
            </div>
        `;
        return;
    }

    $(containerId).innerHTML = selected.map(device => renderNetworkDevice(device, isNcs)).join("");
}

function numericCell(value, units = "") {
    if (value === null || value === undefined || value === "") return "—";
    return `${escapeHtml(value)}${units ? ` <span class="units">${escapeHtml(units)}</span>` : ""}`;
}

function renderEband(links) {
    const selected = links.filter(link => getRadioType(link) === "EBAND");
    const statuses = selected.map(link => link.status);
    $("ebandStatus").textContent = displayStatus(aggregateRawStatus(statuses));
    $("ebandStatus").className = `status-pill status-${statusClass(aggregateRawStatus(statuses))}`;

    if (!selected.length) {
        $("ebandLinks").innerHTML = '<div class="empty-state">No outgoing EBand radios were discovered · NOT EXISTS</div>';
        return;
    }

    const rows = [];
    selected.forEach(link => {
        const analysis = link.analysis || {};
        const slots = analysis.checks?.difference?.slots || [];
        if (!slots.length) {
            rows.push(`
                <tr>
                    <td>${escapeHtml(link.name)}</td><td>—</td><td>—</td>
                    <td>${statusPill(link.status)}</td>
                </tr>
            `);
            return;
        }
        slots.forEach(slot => {
            const diff = slot.difference || {};
            const zabbix = slot.zabbix_difference || {};
            const value = diff.value ?? zabbix.value;
            const status = diff.status || zabbix.status || "UNKNOWN";
            rows.push(`
                <tr>
                    <td>${escapeHtml(link.name)}</td>
                    <td>${escapeHtml(slot.slot ?? "—")}</td>
                    <td class="numeric">${numericCell(value, "dB")}</td>
                    <td>${statusPill(status)}</td>
                </tr>
            `);
        });
    });

    $("ebandLinks").innerHTML = `
        <table class="radio-table">
            <thead><tr><th>Radio Host</th><th>Slot</th><th>RX/TX Difference</th><th>Status</th></tr></thead>
            <tbody>${rows.join("")}</tbody>
        </table>
    `;
}

function renderRtn(links) {
    const selected = links.filter(link => getRadioType(link) === "RTN");
    const statuses = selected.map(link => link.status);
    $("rtnStatus").textContent = displayStatus(aggregateRawStatus(statuses));
    $("rtnStatus").className = `status-pill status-${statusClass(aggregateRawStatus(statuses))}`;

    if (!selected.length) {
        $("rtnLinks").innerHTML = '<div class="empty-state">No outgoing Huawei RTN radios were discovered · NOT EXISTS</div>';
        return;
    }

    const rows = [];
    selected.forEach(link => {
        const analysis = link.analysis || {};
        const legs = Array.isArray(analysis.links) ? analysis.links : [];
        if (!legs.length) {
            rows.push(`
                <tr><td>${escapeHtml(link.name)}</td><td>—</td><td>—</td><td>—</td><td>—</td><td>${statusPill(link.status)}</td></tr>
            `);
            return;
        }

        legs.forEach(leg => {
            const mods = Array.isArray(leg.modulation) ? leg.modulation : [];
            if (!mods.length) {
                rows.push(`
                    <tr>
                        <td>${escapeHtml(link.name)}</td>
                        <td>${escapeHtml(leg.destination || "—")}</td>
                        <td>—</td><td>—</td><td>—</td>
                        <td>${statusPill(leg.status || link.status)}</td>
                    </tr>
                `);
                return;
            }

            mods.forEach(mod => {
                const history = mod.history_comparison || {};
                rows.push(`
                    <tr>
                        <td>${escapeHtml(link.name)}</td>
                        <td>${escapeHtml(leg.destination || mod.link || "—")}</td>
                        <td class="numeric">${numericCell(mod.value)}</td>
                        <td class="numeric">${numericCell(history.maximum)}</td>
                        <td>${escapeHtml(formatTimestamp(mod.clock || history.current_timestamp))}</td>
                        <td>${statusPill(mod.status || history.status || "UNKNOWN")}</td>
                    </tr>
                `);
            });
        });
    });

    $("rtnLinks").innerHTML = `
        <table class="radio-table">
            <thead>
                <tr><th>Radio Host</th><th>Destination / Leg</th><th>Current Modulation</th>
                <th>Maximum Modulation · 12h</th><th>Current Sample Time</th><th>Comparison</th></tr>
            </thead>
            <tbody>${rows.join("")}</tbody>
        </table>
    `;
}

function renderTrafficTechnology(links, technology, containerId, statusId) {
    const selected = links.filter(link => getRadioType(link) === technology);
    const statuses = selected.map(link => link.status);
    $(statusId).textContent = displayStatus(aggregateRawStatus(statuses));
    $(statusId).className = `status-pill status-${statusClass(aggregateRawStatus(statuses))}`;

    if (!selected.length) {
        $(containerId).innerHTML = `<div class="empty-state">No outgoing ${escapeHtml(technology)} radios were discovered · NOT EXISTS</div>`;
        return;
    }

    const rows = [];
    selected.forEach(link => {
        const analysis = link.analysis || {};
        const rx = Array.isArray(analysis.rx) ? analysis.rx : [];
        const tx = Array.isArray(analysis.tx) ? analysis.tx : [];
        const metrics = [...rx, ...tx];

        if (!metrics.length) {
            rows.push(`
                <tr><td>${escapeHtml(link.name)}</td><td>—</td><td>—</td><td>—</td><td>${statusPill(link.status)}</td></tr>
            `);
            return;
        }

        metrics.forEach(metric => {
            rows.push(`
                <tr>
                    <td>${escapeHtml(link.name)}</td>
                    <td>${escapeHtml(metric.direction || "—")}</td>
                    <td class="numeric">${numericCell(metric.value, metric.units || "")}</td>
                    <td>${escapeHtml(formatTimestamp(metric.timestamp))}</td>
                    <td>${statusPill(analysis.status || metric.status || link.status)}</td>
                </tr>
            `);
        });
    });

    $(containerId).innerHTML = `
        <table class="radio-table">
            <thead><tr><th>Radio Host</th><th>Direction</th><th>Traffic</th><th>Last Update</th><th>Status</th></tr></thead>
            <tbody>${rows.join("")}</tbody>
        </table>
    `;
}

function renderLinks(links) {
    renderEband(links);
    renderRtn(links);
    renderTrafficTechnology(links, "INTRACOM", "intracomLinks", "intracomStatus");
    renderTrafficTechnology(links, "NRAY", "nrayLinks", "nrayStatus");
}

function showResults(audit) {
    state.audit = audit;
    const results = audit.results || {};
    const overview = renderStatusOverview(audit);

    $("resultPanel").classList.remove("hidden");
    $("siteSummary").textContent = `Site ${audit.site_code || state.siteCode || "—"}`;
    $("auditTimestamp").textContent = audit.updated_at
        ? `Updated ${escapeHtml(formatTimestamp(audit.updated_at))}`
        : "Completed audit";

    renderBasebands(overview.basebands);
    renderNetworkDevices(overview.devices, false, "ciscoPanels");
    renderNetworkDevices(overview.devices, true, "ncsPanels");
    renderLinks(overview.links);

    if (audit.status === "COMPLETED") loadReport();
}

function setFormMessageWithDetails(message, error = false) {
    setFormMessage(message, error);
}

async function startAudit() {
    const input = $("siteCode");
    const button = $("startAuditBtn");
    const siteCode = input.value.trim();

    if (!/^\d{4}$/.test(siteCode)) {
        setFormMessage("Enter a valid four-digit Site Code.", true);
        input.focus();
        return;
    }

    button.disabled = true;
    resetResults();
    $("jobPanel").classList.remove("hidden");
    $("jobId").textContent = "Creating job...";
    $("jobStatusText").textContent = "Submitting audit...";
    $("progressBar").style.width = "5%";
    setFormMessage("Audit started.", false);

    try {
        const data = await apiJson("/audit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ site_code: siteCode }),
        });

        state.jobId = data.job_id;
        state.siteCode = data.site_code;
        $("jobId").textContent = state.jobId;
        updateJobBadge(data.status || "QUEUED");

        if (state.timer) clearInterval(state.timer);
        await pollAudit();
        if (state.audit?.status !== "COMPLETED" && state.audit?.status !== "FAILED") {
            state.timer = setInterval(pollAudit, 2500);
        }
    } catch (error) {
        setFormMessage(error.message, true);
        updateJobBadge("FAILED");
    } finally {
        button.disabled = false;
    }
}

async function pollAudit() {
    if (!state.jobId) return;

    try {
        const audit = await apiJson(`/audit/${encodeURIComponent(state.jobId)}`);
        state.audit = audit;
        updateJobBadge(audit.status);

        if (audit.status === "COMPLETED") {
            if (state.timer) {
                clearInterval(state.timer);
                state.timer = null;
            }
            showResults(audit);
            setFormMessage(`Audit completed for Site ${audit.site_code}.`, false);
            return;
        }

        if (audit.status === "FAILED") {
            if (state.timer) {
                clearInterval(state.timer);
                state.timer = null;
            }
            showResults(audit);
            setFormMessage(audit.error || "Audit failed.", true);
            return;
        }
    } catch (error) {
        $("jobStatusText").textContent = `Polling error: ${error.message}`;
    }
}

async function loadReport() {
    if (!state.jobId) return;
    try {
        const data = await apiJson(`/audit/${encodeURIComponent(state.jobId)}/report`);
        state.report = data.report || null;
        $("excelBtn").disabled = !state.report;
    } catch {
        $("excelBtn").disabled = false;
    }
}

function downloadExcel() {
    if (!state.jobId) return;
    window.location.href = `/audit/${encodeURIComponent(state.jobId)}/report/download`;
}

function handlePdf() {
    setFormMessage("PDF reporting is not implemented yet.", false);
}

$("startAuditBtn").addEventListener("click", startAudit);
$("siteCode").addEventListener("keydown", event => {
    if (event.key === "Enter") startAudit();
});
$("excelBtn").addEventListener("click", downloadExcel);
$("pdfBtn").addEventListener("click", handlePdf);

checkApiHealth();
setInterval(checkApiHealth, 15000);
