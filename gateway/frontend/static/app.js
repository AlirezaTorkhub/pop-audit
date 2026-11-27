"use strict";

const state = {
    jobId: null,
    siteCode: null,
    timer: null,
    audit: null,
    report: null,
    jobStatus: null,
};

const $ = (id) => document.getElementById(id);

function normalizeStatus(value) {
    const s = String(value || "UNKNOWN").toUpperCase();

    if (
        [
            "PASS",
            "WARNING",
            "CRITICAL",
            "UNKNOWN",
            "NOT_AVAILABLE",
            "NOT_EXISTS",
        ].includes(s)
    ) {
        return s;
    }

    return "UNKNOWN";
}

function statusClass(status) {
    return normalizeStatus(status)
        .toLowerCase()
        .replace("-", "_");
}

function escapeHtml(value) {
    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function statusText(value) {
    return normalizeStatus(value);
}

function statusSpan(value) {
    const status = normalizeStatus(value);

    return `
        <span class="status-cell status-${statusClass(status)}">
            ${escapeHtml(status)}
        </span>
    `;
}

function badge(value) {
    const status = normalizeStatus(value);

    return `
        <span class="small-status badge-${statusClass(status)}">
            ${escapeHtml(status)}
        </span>
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

    if (error) {
        el.style.background = "rgba(239,68,68,.11)";
        el.style.borderColor = "rgba(239,68,68,.34)";
        el.style.color = "#fecaca";
    } else {
        el.style.background = "rgba(59,130,246,.11)";
        el.style.borderColor = "rgba(59,130,246,.34)";
        el.style.color = "#bfdbfe";
    }
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
        const detail =
            data?.detail ||
            text ||
            `HTTP ${response.status}`;

        throw new Error(
            typeof detail === "string"
                ? detail
                : JSON.stringify(detail)
        );
    }

    return data;
}

async function checkApiHealth() {
    const dot = $("apiStatusDot");
    const text = $("apiStatusText");

    try {
        const data = await apiJson("/health");

        if (data?.status === "ok") {
            dot.classList.add("up");
            dot.classList.remove("down");
            text.textContent = "API ONLINE";
        } else {
            dot.classList.add("down");
            dot.classList.remove("up");
            text.textContent = "API DEGRADED";
        }
    } catch (error) {
        dot.classList.add("down");
        dot.classList.remove("up");
        text.textContent = "API OFFLINE";
    }
}

function setProgress(status) {
    const normalized = String(status || "").toUpperCase();

    let width = 5;

    if (normalized === "QUEUED") {
        width = 5;
    } else if (normalized === "DISCOVERY") {
        width = 30;
    } else if (normalized === "RUNNING") {
        width = 65;
    } else if (normalized === "COMPLETED") {
        width = 100;
    } else if (normalized === "FAILED") {
        width = 100;
    }

    $("progressBar").style.width = `${width}%`;

    $("phaseDiscovery").style.color =
        width >= 30 ? "#dce6f7" : "#8fa0bb";

    $("phaseRunning").style.color =
        width >= 65 ? "#dce6f7" : "#8fa0bb";

    $("phaseCompleted").style.color =
        width >= 100 ? "#dce6f7" : "#8fa0bb";
}

function updateJobBadge(status) {
    const normalized = String(status || "UNKNOWN").toUpperCase();
    state.jobStatus = normalized;
    const className = statusClass(normalized);

    const badgeElement = $("jobStatusBadge");

    badgeElement.textContent = normalized;
    badgeElement.className =
        `status-badge badge-${className}`;

    setProgress(normalized);

    $("jobStatusText").textContent =
        normalized === "QUEUED"
            ? "Job queued..."
            : normalized === "DISCOVERY"
                ? "Discovering site infrastructure..."
                : normalized === "RUNNING"
                    ? "Running Cisco, Ericsson and Radio checks..."
                    : normalized === "COMPLETED"
                        ? "Audit completed successfully."
                        : normalized === "FAILED"
                            ? "Audit failed."
                            : normalized;
}

function resetResults() {
    $("resultPanel").classList.add("hidden");

    $("overallStatus").textContent = "UNKNOWN";
    $("overallStatus").className =
        "overall-status status-unknown";

    for (const service of ["Cisco", "Ericsson", "Radio"]) {
        $(`status${service}`).textContent = "UNKNOWN";
        $(`meta${service}`).textContent =
            "Waiting for audit";
        $(`card${service}`).className =
            "service-card unknown";
    }

    $("ciscoDetails").innerHTML =
        '<div class="empty-state">No data</div>';

    $("ericssonDetails").innerHTML =
        '<div class="empty-state">No data</div>';

    $("radioDetails").innerHTML =
        '<div class="empty-state">No data</div>';
    $("basebandDetails").innerHTML =
        '<div class="empty-state">No Baseband data</div>';
    $("ncsDetails").innerHTML =
        '<div class="empty-state">No NCS 540 data</div>';
    $("categoryGrid").innerHTML = "";
    $("auditSummary").innerHTML = "";

    $("excelBtn").disabled = true;
    $("pdfBtn").disabled = true;
}

function showResults(audit) {
    state.audit = audit;

    const overall = normalizeStatus(
        audit.audit_status
    );

    $("resultPanel").classList.remove("hidden");

    $("overallStatus").textContent =
        overall;

    $("overallStatus").className =
        `overall-status status-${statusClass(overall)}`;

    $("siteSummary").textContent =
        `Site ${audit.site_code}`;

    const results = audit.results || {};

    const serviceMap = {
        Cisco: "cisco",
        Ericsson: "ericsson",
        Radio: "radio",
    };

    for (const [label, key] of Object.entries(serviceMap)) {
        const result = results[key] || {};

        const serviceStatus =
            extractServiceStatus(result);

        $(`status${label}`).textContent =
            serviceStatus;

        $(`card${label}`).className =
            `service-card ${statusClass(serviceStatus)}`;

        $(`meta${label}`).textContent =
            result?.data?.status
                ? `Audit result: ${result.data.status}`
                : "No detailed result";
    }

    renderCisco(results.cisco);
    renderNcs(results.cisco, audit.discovery?.ncs_status, audit.discovery?.ncs_reason);
    renderEricsson(results.ericsson);
    renderBasebands(audit);
    renderRadio(results.radio);
    renderCategories(audit);
    renderSummary(audit);

    if (audit.status === "COMPLETED") {
        loadReport();
    }
}

function extractServiceStatus(result) {
    const direct = result?.data?.status;

    if (
        typeof direct === "string" &&
        [
            "PASS",
            "WARNING",
            "CRITICAL",
            "UNKNOWN",
            "NOT_AVAILABLE",
            "NOT_EXISTS",
        ].includes(direct.toUpperCase())
    ) {
        return normalizeStatus(direct);
    }

    if (result?.status === "FAILED") {
        return "UNKNOWN";
    }

    return "UNKNOWN";
}

function normalizeData(result) {
    if (
        result &&
        result.data &&
        typeof result.data === "object"
    ) {
        return result.data;
    }

    return result || {};
}

function renderCisco(wrapper) {
    const container = $("ciscoDetails");
    if (!wrapper) {
        container.innerHTML = '<div class="empty-state">Cisco result unavailable</div>';
        return;
    }
    const data = normalizeData(wrapper);
    $("ciscoDetailStatus").textContent = normalizeStatus(data.status);
    $("ciscoDetailStatus").className = `small-status badge-${statusClass(data.status)}`;
    let devices = Array.isArray(data.switches) ? data.switches : (
        Array.isArray(data.results)
            ? data.results.filter(item => String(item.device_type || "").toLowerCase() !== "ncs540")
            : []
    );
    if (!devices.length) {
        container.innerHTML = '<div class="empty-state">No Cisco switch devices were discovered for this POP.</div>';
        return;
    }
    let html = "";
    for (const device of devices) {
        const checks = device.checks || {};
        const interfaces = checks.interfaces?.data || [];
        const logs = checks.logging?.recent_10 || [];
        const crcProblems = (checks.crc_problems || []).filter(item => Number(item.crc) > 0);
        html += `
            <div class="device-heading">
                <strong>${escapeHtml(device.hostname)}</strong>
                <span>${escapeHtml(device.ip || "-")} · ${statusSpan(device.status)}</span>
            </div>
            <div class="metric-grid">
                <div class="metric"><div class="metric-label">Interfaces</div><div class="metric-value">${interfaces.length}</div></div>
                <div class="metric"><div class="metric-label">CRC Problems</div><div class="metric-value">${crcProblems.length}</div></div>
                <div class="metric"><div class="metric-label">Log Status</div><div class="metric-value">${statusSpan(checks.logging?.status)}</div></div>
                <div class="metric"><div class="metric-label">Environment</div><div class="metric-value">${statusSpan(checks.environment?.status)}</div></div>
            </div>`;
        if (interfaces.length) {
            html += `
                <div class="table-wrap" style="margin-top:12px"><table>
                    <thead><tr><th>Interface</th><th>Description</th><th>Health</th><th>Admin / Oper</th><th>Speed</th><th>CRC</th><th>Input Errors</th><th>Output Errors</th></tr></thead><tbody>`;
            for (const item of interfaces) {
                html += `<tr>
                    <td>${escapeHtml(item.interface)}</td>
                    <td>${escapeHtml(item.description)}</td>
                    <td>${statusSpan(item.health)}</td>
                    <td>${escapeHtml(`${item.status_raw || ""} / ${item.protocol || ""}`)}</td>
                    <td>${escapeHtml(item.speed)}</td>
                    <td>${escapeHtml(item.crc)}</td>
                    <td>${escapeHtml(item.input_errors)}</td>
                    <td>${escapeHtml(item.output_errors)}</td>
                </tr>`;
            }
            html += '</tbody></table></div>';
        }
        if (crcProblems.length) {
            html += '<div class="problem-list"><strong>Measured CRC problems</strong><ul>';
            for (const item of crcProblems) {
                html += `<li>${escapeHtml(item.interface)}: ${escapeHtml(item.crc)} CRC errors</li>`;
            }
            html += '</ul></div>';
        }
        if (logs.length) {
            html += '<div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Recent log event</th></tr></thead><tbody>';
            for (const line of logs.slice(-10)) {
                html += `<tr><td>${escapeHtml(line)}</td></tr>`;
            }
            html += '</tbody></table></div>';
        }
    }
    container.innerHTML = html;
}


function renderEricsson(wrapper) {
    const container = $("ericssonDetails");

    if (!wrapper) {
        container.innerHTML =
            '<div class="empty-state">Ericsson result unavailable</div>';
        return;
    }

    const data = normalizeData(wrapper);

    $("ericssonDetailStatus").textContent =
        normalizeStatus(data.status);

    $("ericssonDetailStatus").className =
        `small-status badge-${statusClass(data.status)}`;

    const devices =
        Array.isArray(data.results)
            ? data.results
            : [];

    if (!devices.length) {
        container.innerHTML =
            '<div class="empty-state">No Ericsson data</div>';
        return;
    }

    let html = "";

    for (const device of devices) {
        const checks = device.checks || {};

        const ltAll =
            checks.lt_all || {};

        const cells =
            checks.cells || {};

        const alarms =
            checks.alarms || {};

        const clock =
            checks.clock || {};

        html += `
            <div class="metric-grid">

                <div class="metric">
                    <div class="metric-label">Hostname</div>
                    <div class="metric-value">
                        ${escapeHtml(device.hostname)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">Cells</div>
                    <div class="metric-value">
                        ${escapeHtml(cells.count)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">LT ALL</div>
                    <div class="metric-value">
                        ${statusSpan(ltAll.status)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">Clock</div>
                    <div class="metric-value">
                        ${statusSpan(clock.status)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">Alarms</div>
                    <div class="metric-value">
                        ${escapeHtml(alarms.total)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">Critical</div>
                    <div class="metric-value">
                        ${escapeHtml(alarms.critical)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">Major</div>
                    <div class="metric-value">
                        ${escapeHtml(alarms.major)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">Clock State</div>
                    <div class="metric-value">
                        ${escapeHtml(clock.state)}
                    </div>
                </div>

            </div>
        `;

        const alarmRows =
            Array.isArray(alarms.alarms)
                ? alarms.alarms
                : [];

        if (alarmRows.length) {

            html += `
                <div class="table-wrap" style="margin-top:12px">
                    <table>
                        <thead>
                            <tr>
                                <th>Severity</th>
                                <th>Timestamp</th>
                                <th>Problem</th>
                                <th>Additional Text</th>
                            </tr>
                        </thead>

                        <tbody>
            `;

            for (const alarm of alarmRows) {
                html += `
                    <tr>
                        <td>${escapeHtml(alarm.severity)}</td>
                        <td>${escapeHtml(alarm.timestamp)}</td>
                        <td>${escapeHtml(alarm.problem)}</td>
                        <td>${escapeHtml(alarm.additional_text)}</td>
                    </tr>
                `;
            }

            html += `
                        </tbody>
                    </table>
                </div>
            `;
        }
    }

    container.innerHTML = html;
}

function renderRadio(wrapper) {
    const container = $("radioDetails");
    if (!wrapper) {
        container.innerHTML = '<div class="empty-state">Radio result unavailable</div>';
        return;
    }
    const data = normalizeData(wrapper);
    $("radioDetailStatus").textContent = normalizeStatus(data.status);
    $("radioDetailStatus").className = `small-status badge-${statusClass(data.status)}`;
    const links = Array.isArray(data.links) ? data.links : [];
    if (!links.length) {
        container.innerHTML = '<div class="empty-state">No outgoing radio links were discovered for this POP.</div>';
        return;
    }
    let html = '<div class="table-wrap"><table><thead><tr><th>Type</th><th>Link</th><th>Destination</th><th>Status</th><th>Analysis</th></tr></thead><tbody>';
    for (const link of links) {
        html += `<tr>
            <td>${escapeHtml(link.link_type || link.type)}</td>
            <td>${escapeHtml(link.name)}</td>
            <td>${escapeHtml(link.destination_name || link.destination_site || "-")}</td>
            <td>${statusSpan(link.status)}</td>
            <td>${renderRadioAnalysisSummary(link)}</td>
        </tr>`;
    }
    html += '</tbody></table></div>';

    for (const link of links) {
        const analysis = link.analysis || {};
        const type = String(link.link_type || link.type || "").toUpperCase();
        let metrics = [];
        if (type === "RTN") {
            metrics = [
                ...(analysis.modulation || []),
                ...(analysis.difference || []),
                ...(analysis.traffic || []),
            ];
        } else if (type === "EBAND") {
            const slots = analysis.checks?.difference?.slots || [];
            for (const slot of slots) {
                for (const field of ["rx", "tx", "rx_calloff", "tx_calloff", "zabbix_difference"]) {
                    const metric = slot[field];
                    if (metric) metrics.push({...metric, display_name: `Slot ${slot.slot} ${field.toUpperCase()}`});
                }
                const difference = slot.difference || {};
                metrics.push({
                    display_name: `Slot ${slot.slot} calculated difference`,
                    value: difference.value,
                    units: "dB",
                    status: difference.status,
                    reason: difference.reason,
                });
                const rx = slot.rx || {};
                const rxHealth = slot.rx_health || {};
                metrics.push({
                    display_name: `Slot ${slot.slot} RX health`,
                    value: rx.value,
                    units: rx.units,
                    status: rxHealth.status,
                    reason: rxHealth.reason,
                });
                const modulation = slot.rx_modulation || {};
                metrics.push({
                    ...(modulation.metric || {}),
                    display_name: `Slot ${slot.slot} RX modulation`,
                    status: modulation.health?.status,
                    reason: modulation.health?.reason,
                });
            }
        } else {
            metrics = analysis.metrics || [];
        }
        if (!metrics.length) continue;
        html += `<div class="metric-section"><strong>${escapeHtml(link.name)} · ${escapeHtml(type)} metrics</strong>
            <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Key</th><th>Value</th><th>Units</th><th>Timestamp</th><th>Status</th><th>12h Maximum</th><th>Samples</th></tr></thead><tbody>`;
        for (const metric of metrics) {
            const history = metric.history || {};
            html += `<tr>
                <td>${escapeHtml(metric.display_name || metric.name || metric.direction || metric.link || metric.key)}</td>
                <td>${escapeHtml(metric.key)}</td>
                <td>${escapeHtml(metric.value ?? metric.raw_value)}</td>
                <td>${escapeHtml(metric.units)}</td>
                <td>${escapeHtml(metric.clock || metric.lastclock)}</td>
                <td>${statusSpan(metric.status)}</td>
                <td>${escapeHtml(history.max)}</td>
                <td>${escapeHtml(history.history_count)}</td>
            </tr>`;
        }
        html += '</tbody></table></div></div>';
    }
    container.innerHTML = html;
}
function renderRadioAnalysisSummary(link) {
    const analysis = link.analysis || {};
    const type = String(link.link_type || link.type || "").toUpperCase();
    if (type === "EBAND") {
        const checks = analysis.checks || {};
        const slots = checks.difference?.slots || [];
        return `Difference: ${escapeHtml(checks.difference?.status || "-")} · RX: ${escapeHtml(slots.map(s => s.rx_health?.status || "-").join("/"))}`;
    }
    if (type === "RTN") {
        return `Modulation: ${escapeHtml((analysis.modulation || []).length)} · Traffic: ${escapeHtml((analysis.traffic || []).length)} · History: ${escapeHtml(analysis.history_window_hours || 12)}h`;
    }
    return `Metrics: ${escapeHtml((analysis.metrics || []).length)}`;
}


function renderSummary(audit) {
    const summary = audit.summary || {};
    const services = summary.services || {};
    const categories = summary.categories || {};
    const ordered = ["Cisco Switch","BB1","BB2","NCS 540","EBand","Huawei RTN","Intracom","NRay"];
    let rows = "";
    for (const name of ordered) {
        rows += `<tr><td>${escapeHtml(name)}</td><td>${statusSpan(categories[name] || "UNKNOWN")}</td></tr>`;
    }
    $("auditSummary").innerHTML = `
        <div class="table-wrap"><table class="summary-table"><thead><tr><th>POP Component</th><th>Status</th></tr></thead><tbody>
            ${rows}
        </tbody></table></div>
        <div class="summary-meta">
            Services: ${escapeHtml(summary.service_count ?? 0)} ·
            Critical categories: ${escapeHtml(summary.critical ?? 0)} ·
            Warning categories: ${escapeHtml(summary.warning ?? 0)} ·
            Unknown categories: ${escapeHtml(summary.unknown ?? 0)} ·
            Not available: ${escapeHtml(summary.not_available ?? 0)} ·
            Not exists: ${escapeHtml(summary.not_exists ?? 0)}
        </div>
        <div class="summary-service-meta">
            Cisco service: ${statusSpan(services.cisco)} ·
            Ericsson service: ${statusSpan(services.ericsson)} ·
            Radio service: ${statusSpan(services.radio)}
        </div>
    `;
}




function renderCategories(audit) {
    const categories = audit.summary?.categories || {};
    const names = ["Cisco Switch","BB1","BB2","NCS 540","EBand","Huawei RTN","Intracom","NRay"];
    $("categoryGrid").innerHTML = names.map(name => {
        const status = normalizeStatus(categories[name] || "UNKNOWN");
        return `<div class="category-card status-${statusClass(status)}">
            <div class="category-name">${escapeHtml(name)}</div>
            <div class="category-status">${statusSpan(status)}</div>
        </div>`;
    }).join("");
}


function renderBasebands(audit) {
    const container = $("basebandDetails");
    const discovery = audit.discovery || {};
    const ericsson = normalizeData(audit.results?.ericsson || {});
    const checksByHost = new Map(
        (ericsson.results || []).map(device => [String(device.zabbix_hostid || ""), device])
    );
    const basebands = Array.isArray(discovery.basebands) ? discovery.basebands : [];
    const expected = ["BB1", "BB2"];
    let html = "";
    for (let index = 0; index < 2; index++) {
        const slot = expected[index];
        const bb = basebands.find(item => item.name === slot) || basebands[index] || {name:slot,exists:false,status:"NOT_EXISTS"};
        const device = checksByHost.get(String(bb.zabbix_hostid || "")) || {};
        const checks = device.checks || {};
        const cells = checks.cells || {};
        const alarms = checks.alarms || {};
        const clock = checks.clock || {};
        const status = device.status || bb.status || (bb.exists ? "UNKNOWN" : "NOT_EXISTS");
        html += `
            <article class="baseband-card status-${statusClass(status)}">
                <div class="baseband-card-header">
                    <strong>${escapeHtml(slot)}</strong>
                    ${statusSpan(status)}
                </div>
                <div class="baseband-host">${escapeHtml(bb.hostname || "Not discovered")}</div>
                <div class="baseband-grid-values">
                    <div><span>IP</span><strong>${escapeHtml(bb.ip || "-")}</strong></div>
                    <div><span>Zabbix Host ID</span><strong>${escapeHtml(bb.zabbix_hostid || "-")}</strong></div>
                    <div><span>LT ALL</span><strong>${statusSpan(checks.lt_all?.status || "NOT_AVAILABLE")}</strong></div>
                    <div><span>Cells</span><strong>${escapeHtml(cells.count ?? "-")} · ${statusSpan(cells.status || "NOT_AVAILABLE")}</strong></div>
                    <div><span>Alarms</span><strong>${escapeHtml(alarms.relevant_count ?? alarms.total ?? "-")} · ${statusSpan(alarms.status || "NOT_AVAILABLE")}</strong></div>
                    <div><span>Radio Clock</span><strong>${escapeHtml(clock.state || "-")} · ${statusSpan(clock.status || "NOT_AVAILABLE")}</strong></div>
                    <div><span>Clock Value</span><strong>${escapeHtml(clock.value ?? "-")}</strong></div>
                    <div><span>Discovery</span><strong>${escapeHtml((bb.groups || []).join(", ") || bb.reason || "-")}</strong></div>
                </div>
            </article>`;
        const cellRows = Array.isArray(cells.cells) ? cells.cells : [];
        if (cellRows.length) {
            html += '<div class="table-wrap baseband-cell-table"><table><thead><tr><th>Cell / MO</th><th>Admin</th><th>Operational</th><th>Status</th></tr></thead><tbody>';
            for (const cell of cellRows) {
                html += `<tr>
                    <td>${escapeHtml(cell.mo || cell.proxy)}</td>
                    <td>${escapeHtml(cell.admin_state)}</td>
                    <td>${escapeHtml(cell.oper_state)}</td>
                    <td>${statusSpan(cell.status)}</td>
                </tr>`;
            }
            html += '</tbody></table></div>';
        }
    }
    container.innerHTML = html;
}


function renderNcs(wrapper, discoveryStatus = null, discoveryReason = null) {
    const container = $("ncsDetails");
    if (!wrapper) {
        $("ncsDetailStatus").textContent = "NOT_AVAILABLE";
        container.innerHTML = '<div class="empty-state">Cisco result unavailable</div>';
        return;
    }
    const data = normalizeData(wrapper);
    const devices = Array.isArray(data.ncs_devices) ? data.ncs_devices : (
        Array.isArray(data.results) ? data.results.filter(item => String(item.device_type || "").toLowerCase() === "ncs540") : []
    );
    const statusOrder = {CRITICAL:5, WARNING:4, UNKNOWN:3, NOT_AVAILABLE:2, PASS:1, NOT_EXISTS:0};
    const status = devices.length
        ? devices.map(item => normalizeStatus(item.status)).reduce(
            (worst, value) => statusOrder[value] > statusOrder[worst] ? value : worst,
            "PASS"
        )
        : normalizeStatus(discoveryStatus || "NOT_EXISTS");
    $("ncsDetailStatus").textContent = status;
    $("ncsDetailStatus").className = `small-status badge-${statusClass(status)}`;
    if (!devices.length) {
        container.innerHTML = `<div class="empty-state">${escapeHtml(discoveryReason || (status === "NOT_EXISTS" ? "No NCS 540 associated with this POP." : "NCS 540 discovery is inconclusive."))}</div>`;
        return;
    }
    let html = "";
    for (const device of devices) {
        const checks = device.checks || {};
        const interfaces = checks.interfaces?.data || [];
        const logs = checks.logging?.recent_10 || [];
        html += `<div class="device-heading"><strong>${escapeHtml(device.hostname)}</strong><span>${escapeHtml(device.ip || "-")} · ${statusSpan(device.status)}</span></div>`;
        if (interfaces.length) {
            html += '<div class="table-wrap"><table><thead><tr><th>Interface</th><th>Description</th><th>State</th><th>CRC</th><th>Input Errors</th><th>Output Errors</th><th>Health</th></tr></thead><tbody>';
            for (const item of interfaces) {
                html += `<tr><td>${escapeHtml(item.interface)}</td><td>${escapeHtml(item.description)}</td><td>${escapeHtml(item.line_state)} / ${escapeHtml(item.protocol)}</td><td>${escapeHtml(item.crc)}</td><td>${escapeHtml(item.input_errors)}</td><td>${escapeHtml(item.output_errors)}</td><td>${statusSpan(item.health)}</td></tr>`;
            }
            html += '</tbody></table></div>';
        } else {
            html += '<div class="empty-state">No parsed IOS XR interface data</div>';
        }
        if (logs.length) {
            html += '<div class="problem-list"><strong>Latest logs</strong><ul>';
            for (const line of logs.slice(-10)) html += `<li>${escapeHtml(line)}</li>`;
            html += '</ul></div>';
        }
    }
    container.innerHTML = html;
}

async function startAudit() {
    const input = $("siteCode");
    const button = $("startAuditBtn");

    const siteCode = input.value.trim();

    if (!siteCode) {
        setFormMessage(
            "Enter a Site Code.",
            true
        );
        input.focus();
        return;
    }

    button.disabled = true;

    resetResults();

    $("jobPanel").classList.remove("hidden");
    $("jobId").textContent = "Creating job...";
    $("jobStatusText").textContent = "Submitting audit...";
    $("progressBar").style.width = "5%";

    setFormMessage(
        "Audit started.",
        false
    );

    try {
        const data = await apiJson(
            "/audit",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    site_code: siteCode,
                }),
            }
        );

        state.jobId = data.job_id;
        state.siteCode = data.site_code;

        $("jobId").textContent =
            state.jobId;

        updateJobBadge(
            data.status || "QUEUED"
        );

        if (state.timer) {
            clearInterval(state.timer);
        }

        await pollAudit();

        if (!["COMPLETED", "FAILED"].includes(state.jobStatus)) {
            state.timer = setInterval(
                pollAudit,
                2500
            );
        }

    } catch (error) {
        setFormMessage(
            error.message,
            true
        );

        updateJobBadge("FAILED");

    } finally {
        button.disabled = false;
    }
}

async function pollAudit() {
    if (!state.jobId) {
        return;
    }

    try {
        const audit = await apiJson(
            `/audit/${encodeURIComponent(state.jobId)}`
        );

        updateJobBadge(
            audit.status
        );

        if (audit.status === "COMPLETED") {

            if (state.timer) {
                clearInterval(state.timer);
                state.timer = null;
            }

            showResults(audit);

            setFormMessage(
                `Audit completed for Site ${audit.site_code}.`,
                false
            );

            return;
        }

        if (audit.status === "FAILED") {

            if (state.timer) {
                clearInterval(state.timer);
                state.timer = null;
            }

            showResults(audit);

            const message =
                audit.error ||
                "Audit failed.";

            setFormMessage(
                message,
                true
            );
        }

    } catch (error) {

        $("jobStatusText").textContent =
            `Polling error: ${error.message}`;
    }
}

async function loadReport() {
    if (!state.jobId) {
        return;
    }

    try {
        const data = await apiJson(
            `/audit/${encodeURIComponent(state.jobId)}/report`
        );

        state.report = data.report || null;

        if (state.report) {
            $("excelBtn").disabled = false;
        }

    } catch (error) {

        $("excelBtn").disabled = false;

    }
}

function downloadExcel() {
    if (!state.jobId) {
        return;
    }

    window.location.href =
        `/audit/${encodeURIComponent(
            state.jobId
        )}/report/download`;
}

function handlePdf() {
    setFormMessage(
        "PDF reporting is not implemented yet.",
        false
    );
}

$("startAuditBtn")
    .addEventListener(
        "click",
        startAudit
    );

$("siteCode")
    .addEventListener(
        "keydown",
        (event) => {
            if (event.key === "Enter") {
                startAudit();
            }
        }
    );

$("excelBtn")
    .addEventListener(
        "click",
        downloadExcel
    );

$("pdfBtn")
    .addEventListener(
        "click",
        handlePdf
    );

checkApiHealth();

setInterval(
    checkApiHealth,
    15000
);
