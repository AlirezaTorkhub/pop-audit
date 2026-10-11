CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID REFERENCES sites(id),
    site_code VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID REFERENCES sites(id),
    hostname VARCHAR(255) NOT NULL,
    ip VARCHAR(64),
    vendor VARCHAR(64),
    device_type VARCHAR(128),
    role VARCHAR(128),
    zabbix_hostid VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(site_id, hostname)
);

CREATE TABLE IF NOT EXISTS radio_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID REFERENCES sites(id),
    name VARCHAR(255) NOT NULL,
    link_type VARCHAR(64),
    source_site VARCHAR(32),
    destination_site VARCHAR(32),
    zabbix_hostid VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(site_id, name)
);

CREATE TABLE IF NOT EXISTS audit_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_run_id UUID NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    service VARCHAR(64) NOT NULL,
    check_name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    entity_name VARCHAR(255),
    entity_ip VARCHAR(64),
    message TEXT,
    raw_output TEXT,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_runs_site
ON audit_runs(site_code);

CREATE INDEX IF NOT EXISTS idx_audit_results_run
ON audit_results(audit_run_id);

CREATE INDEX IF NOT EXISTS idx_devices_site
ON devices(site_id);

CREATE INDEX IF NOT EXISTS idx_radio_links_site
ON radio_links(site_id);



