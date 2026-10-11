"use strict";

const state = {
    jobId: null,
    siteCode: null,
    timer: null,
    audit: null,
    report: null,
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
    renderEricsson(results.ericsson);
    renderRadio(results.radio);
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
        ].includes(direct.toUpperCase())
    ) {
        return normalizeStatus(direct);
    }

    if (result?.status === "FAILED") {
        return "CRITICAL";
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
        container.innerHTML =
            '<div class="empty-state">Cisco result unavailable</div>';
        return;
    }

    const data = normalizeData(wrapper);

    $("ciscoDetailStatus").textContent =
        normalizeStatus(data.status);

    $("ciscoDetailStatus").className =
        `small-status badge-${statusClass(data.status)}`;

    const devices =
        Array.isArray(data.results)
            ? data.results
            : [];

    if (!devices.length) {
        container.innerHTML =
            '<div class="empty-state">No Cisco device data</div>';
        return;
    }

    let html = "";

    for (const device of devices) {
        const checks = device.checks || {};

        const interfaces =
            checks.interfaces?.data || [];

        html += `
            <div class="metric-grid">
                <div class="metric">
                    <div class="metric-label">Hostname</div>
                    <div class="metric-value">
                        ${escapeHtml(device.hostname)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">IP</div>
                    <div class="metric-value">
                        ${escapeHtml(device.ip)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">Overall</div>
                    <div class="metric-value">
                        ${statusSpan(device.status)}
                    </div>
                </div>

                <div class="metric">
                    <div class="metric-label">Interfaces</div>
                    <div class="metric-value">
                        ${interfaces.length}
                    </div>
                </div>
            </div>
        `;

        if (interfaces.length) {
            html += `
                <div class="table-wrap" style="margin-top:12px">
                    <table>
                        <thead>
                            <tr>
                                <th>Interface</th>
                                <th>Description</th>
                                <th>Health</th>
                                <th>Admin / Oper</th>
                                <th>Speed</th>
                                <th>CRC</th>
                                <th>Input Errors</th>
                                <th>Output Errors</th>
                            </tr>
                        </thead>

                        <tbody>
            `;

            for (const item of interfaces) {
                html += `
                    <tr>
                        <td>${escapeHtml(item.interface)}</td>
                        <td>${escapeHtml(item.description)}</td>
                        <td>${statusSpan(item.health)}</td>
                        <td>${escapeHtml(
                            `${item.status_raw || ""} / ${item.protocol || ""}`
                        )}</td>
                        <td>${escapeHtml(item.speed)}</td>
                        <td>${escapeHtml(item.crc)}</td>
                        <td>${escapeHtml(item.input_errors)}</td>
                        <td>${escapeHtml(item.output_errors)}</td>
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
        container.innerHTML =
            '<div class="empty-state">Radio result unavailable</div>';
        return;
    }

    const data = normalizeData(wrapper);

    $("radioDetailStatus").textContent =
        normalizeStatus(data.status);

    $("radioDetailStatus").className =
        `small-status badge-${statusClass(data.status)}`;

    const links =
        Array.isArray(data.links)
            ? data.links
            : [];

    if (!links.length) {
        container.innerHTML =
            '<div class="empty-state">No radio links</div>';
        return;
    }

    let html = `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Type</th>
                        <th>Name</th>
                        <th>Destination</th>
                        <th>Status</th>
                        <th>Analysis</th>
                    </tr>
                </thead>
                <tbody>
    `;

    for (const link of links) {
        html += `
            <tr>
                <td>${escapeHtml(link.link_type)}</td>
                <td>${escapeHtml(link.name)}</td>
                <td>${escapeHtml(
                    link.destination_name ||
                    link.destination_site ||
                    "-"
                )}</td>
                <td>${statusSpan(link.status)}</td>
                <td>${renderRadioAnalysisSummary(link)}</td>
            </tr>
        `;
    }

    html += `
                </tbody>
            </table>
        </div>
    `;

    container.innerHTML = html;
}

function renderRadioAnalysisSummary(link) {
    const analysis = link.analysis || {};

    if (
        String(link.link_type || "").toUpperCase() ===
        "EBAND"
    ) {
        const checks = analysis.checks || {};

        return `
            Difference:
            ${escapeHtml(
                checks.difference?.status || "-"
            )}
            <br>
            Interface:
            ${escapeHtml(
                checks.interfaces?.status || "-"
            )}
        `;
    }

    if (
        String(link.link_type || "").toUpperCase() ===
        "RTN"
    ) {
        const nestedLinks =
            Array.isArray(analysis.links)
                ? analysis.links
                : [];

        if (!nestedLinks.length) {
            return "RTN analysis";
        }

        const statuses = nestedLinks
            .map(item => item.status)
            .filter(Boolean);

        return `
            Legs:
            ${nestedLinks.length}
            <br>
            Status:
            ${escapeHtml(
                statuses.join(", ") || "-"
            )}
        `;
    }

    return "-";
}

function renderSummary(audit) {
    const summary =
        audit.summary || {};

    const services =
        summary.services || {};

    $("auditSummary").innerHTML = `
        <div class="table-wrap">
            <table class="summary-table">
                <tbody>
                    <tr>
                        <td>Service Count</td>
                        <td>${escapeHtml(summary.service_count)}</td>
                    </tr>

                    <tr>
                        <td>Critical</td>
                        <td>${escapeHtml(summary.critical)}</td>
                    </tr>

                    <tr>
                        <td>Warning</td>
                        <td>${escapeHtml(summary.warning)}</td>
                    </tr>

                    <tr>
                        <td>Unknown</td>
                        <td>${escapeHtml(summary.unknown)}</td>
                    </tr>

                    <tr>
                        <td>Not Available</td>
                        <td>${escapeHtml(summary.not_available)}</td>
                    </tr>

                    <tr>
                        <td>Pass</td>
                        <td>${escapeHtml(summary.pass)}</td>
                    </tr>

                    <tr>
                        <td>Cisco</td>
                        <td>${statusSpan(services.cisco)}</td>
                    </tr>

                    <tr>
                        <td>Ericsson</td>
                        <td>${statusSpan(services.ericsson)}</td>
                    </tr>

                    <tr>
                        <td>Radio</td>
                        <td>${statusSpan(services.radio)}</td>
                    </tr>
                </tbody>
            </table>
        </div>
    `;
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

        state.timer = setInterval(
            pollAudit,
            2500
        );

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
