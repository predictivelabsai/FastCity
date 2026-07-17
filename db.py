"""FastCity data layer — SQLite for a smart-city IoT data platform.

Core entities: zones (city districts), devices (sensors — the device registry /
"pasportization"), readings (telemetry time-series), rules (threshold alarms),
alerts (rule firings), and flows (low-code integration-pipeline configs, stubbed).

This is the analytics / management layer. The integration bus (MQTT / MODBUS /
REST connectors that would feed `readings`) is represented as *flow* configs and
a single ingestion endpoint — it is deliberately not a full carrier-grade broker.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = os.getenv("FASTCITY_DB") or str(Path(__file__).parent / "fastcity.sqlite")

# "Now" is fixed so the synthetic demo is deterministic and the dashboards look live.
NOW = datetime(2026, 7, 16, 12, 0, 0)

# Sensor domains and their measurement metadata.
#   metric/unit — what the sensor reports
#   base/amp    — synthetic daily mean and swing (see seed.py)
#   high        — the "attention" threshold used to seed default alarm rules
DOMAINS: dict[str, dict] = {
    "traffic":     {"label": "Traffic",     "metric": "Vehicle flow", "unit": "veh/min", "base": 34, "amp": 30, "high": 80,  "icon": "🚦"},
    "parking":     {"label": "Parking",     "metric": "Occupancy",    "unit": "%",       "base": 55, "amp": 34, "high": 90,  "icon": "🅿️"},
    "environment": {"label": "Environment", "metric": "PM2.5",        "unit": "µg/m³",   "base": 21, "amp": 17, "high": 50,  "icon": "🌫️"},
    "energy":      {"label": "Energy",      "metric": "Power draw",   "unit": "kW",      "base": 68, "amp": 44, "high": 120, "icon": "⚡"},
    "waste":       {"label": "Waste",       "metric": "Bin fill",     "unit": "%",       "base": 44, "amp": 40, "high": 85,  "icon": "🗑️"},
    "noise":       {"label": "Noise",       "metric": "Sound level",  "unit": "dB",      "base": 52, "amp": 17, "high": 70,  "icon": "🔊"},
}
DOMAIN_KEYS = list(DOMAINS.keys())

DEVICE_STATUSES = ["Online", "Offline", "Maintenance", "Fault"]
LIVE_STATUSES = ["Online", "Maintenance"]           # reporting recently
SEVERITIES = ["Critical", "Warning", "Info"]
OPERATORS = [">", ">=", "<", "<="]
ALERT_STATUSES = ["Active", "Acknowledged", "Resolved"]
CONNECTORS = ["MQTT", "MODBUS/TCP", "REST", "HTTP", "CoAP"]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def db_exists() -> bool:
    p = Path(DB_PATH)
    return p.exists() and p.stat().st_size > 0


def rows(sql, params=()):
    with cursor() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None


SCHEMA = """
CREATE TABLE IF NOT EXISTS zones (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    lat     REAL,
    lng     REAL
);
CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY,
    code        TEXT UNIQUE,             -- asset tag, e.g. TRF-0007
    name        TEXT NOT NULL,
    domain      TEXT NOT NULL,           -- traffic | parking | environment | energy | waste | noise
    zone_id     INTEGER REFERENCES zones(id),
    lat         REAL,
    lng         REAL,
    status      TEXT NOT NULL DEFAULT 'Online',
    metric      TEXT,
    unit        TEXT,
    firmware    TEXT,
    installed   TEXT,
    last_seen   TEXT
);
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY,
    device_id   INTEGER NOT NULL REFERENCES devices(id),
    ts          TEXT NOT NULL,
    value       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    domain      TEXT NOT NULL,           -- a domain, or 'any'
    operator    TEXT NOT NULL,           -- > >= < <=
    threshold   REAL NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'Warning',
    enabled     INTEGER NOT NULL DEFAULT 1,
    created     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY,
    rule_id     INTEGER REFERENCES rules(id),
    device_id   INTEGER REFERENCES devices(id),
    value       REAL,
    ts          TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'Active',
    message     TEXT,
    created     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flows (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    connector   TEXT NOT NULL,           -- MQTT | MODBUS/TCP | REST | HTTP | CoAP
    source      TEXT,
    transform   TEXT,
    sink        TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    config      TEXT,                    -- JSON pipeline definition
    created     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_device ON readings(device_id, ts);
CREATE INDEX IF NOT EXISTS idx_devices_domain  ON devices(domain);
CREATE INDEX IF NOT EXISTS idx_alerts_status   ON alerts(status);
"""


def init_schema():
    with cursor() as conn:
        conn.executescript(SCHEMA)


# --- helpers ----------------------------------------------------------------

def _parse(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# --- aggregate reads --------------------------------------------------------

def kpis() -> dict:
    total = scalar("SELECT COUNT(*) FROM devices") or 0
    live_q = ",".join("?" * len(LIVE_STATUSES))
    online = scalar(f"SELECT COUNT(*) FROM devices WHERE status IN ({live_q})", tuple(LIVE_STATUSES)) or 0
    down = scalar("SELECT COUNT(*) FROM devices WHERE status IN ('Offline','Fault')") or 0
    day_ago = fmt_ts(NOW - timedelta(hours=24))
    return {
        "devices": total,
        "online": online,
        "down": down,
        "uptime": round(100 * online / total) if total else 0,
        "active_alerts": scalar("SELECT COUNT(*) FROM alerts WHERE status='Active'") or 0,
        "readings_24h": scalar("SELECT COUNT(*) FROM readings WHERE ts >= ?", (day_ago,)) or 0,
        "zones": scalar("SELECT COUNT(*) FROM zones") or 0,
    }


def counts_by(col: str, table: str = "devices") -> list[dict]:
    return rows(f"SELECT {col} k, COUNT(*) n FROM {table} GROUP BY {col} ORDER BY n DESC")


def domain_summary() -> list[dict]:
    """Per-domain device count, live count, latest average value and open alerts."""
    out = []
    for d in DOMAIN_KEYS:
        devs = scalar("SELECT COUNT(*) FROM devices WHERE domain=?", (d,)) or 0
        if not devs:
            continue
        live_q = ",".join("?" * len(LIVE_STATUSES))
        live = scalar(f"SELECT COUNT(*) FROM devices WHERE domain=? AND status IN ({live_q})",
                      (d, *LIVE_STATUSES)) or 0
        latest = scalar(
            """SELECT AVG(r.value) FROM readings r JOIN devices dv ON dv.id=r.device_id
               WHERE dv.domain=? AND r.ts >= ?""",
            (d, fmt_ts(NOW - timedelta(hours=2))))
        alerts_n = scalar(
            """SELECT COUNT(*) FROM alerts a JOIN devices dv ON dv.id=a.device_id
               WHERE dv.domain=? AND a.status='Active'""", (d,)) or 0
        meta = DOMAINS[d]
        out.append({
            "domain": d, "label": meta["label"], "icon": meta["icon"],
            "metric": meta["metric"], "unit": meta["unit"], "high": meta["high"],
            "devices": devs, "live": live,
            "avg": round(latest, 1) if latest is not None else None,
            "alerts": alerts_n,
        })
    return out


def domain_series(domain: str, hours: int = 72) -> list[dict]:
    """Hourly average across all devices in a domain — the dashboard time-series."""
    since = fmt_ts(NOW - timedelta(hours=hours))
    return rows(
        """SELECT substr(r.ts,1,13) || ':00' bucket, ROUND(AVG(r.value),2) v
           FROM readings r JOIN devices dv ON dv.id=r.device_id
           WHERE dv.domain=? AND r.ts >= ?
           GROUP BY bucket ORDER BY bucket""", (domain, since))


def devices_list(domain="All", status="All", q="") -> list[dict]:
    where, params = [], []
    if domain != "All":
        where.append("d.domain=?"); params.append(domain)
    if status != "All":
        where.append("d.status=?"); params.append(status)
    if q:
        where.append("(d.name LIKE ? OR d.code LIKE ? OR z.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    return rows(
        f"""SELECT d.*, z.name zone,
                   (SELECT value FROM readings r WHERE r.device_id=d.id ORDER BY r.ts DESC LIMIT 1) last_value
            FROM devices d LEFT JOIN zones z ON z.id=d.zone_id
            {clause} ORDER BY d.code LIMIT 500""", tuple(params))


def device(did: int):
    return one(
        """SELECT d.*, z.name zone,
                  (SELECT value FROM readings r WHERE r.device_id=d.id ORDER BY r.ts DESC LIMIT 1) last_value
           FROM devices d LEFT JOIN zones z ON z.id=d.zone_id WHERE d.id=?""", (did,))


def readings_for(did: int, hours: int = 72) -> list[dict]:
    since = fmt_ts(NOW - timedelta(hours=hours))
    return rows("SELECT ts, value FROM readings WHERE device_id=? AND ts >= ? ORDER BY ts", (did, since))


def alerts(status: str = "All", limit: int = 200) -> list[dict]:
    clause, params = ("WHERE a.status=?", (status,)) if status != "All" else ("", ())
    return rows(
        f"""SELECT a.*, d.name device, d.code, d.domain, r.name rule_name, r.severity
            FROM alerts a
            LEFT JOIN devices d ON d.id=a.device_id
            LEFT JOIN rules r ON r.id=a.rule_id
            {clause} ORDER BY a.ts DESC LIMIT ?""", (*params, limit))


def alert_counts() -> dict:
    return {r["k"]: r["n"] for r in counts_by("status", "alerts")}


# --- device map -------------------------------------------------------------

def map_devices() -> list[dict]:
    return rows("SELECT id, code, name, domain, status, lat, lng FROM devices WHERE lat IS NOT NULL")


# --- write: ingestion -------------------------------------------------------

def add_reading(device_id: int, value: float, ts: str | None = None) -> bool:
    """Telemetry ingestion — the single write path the integration bus would call."""
    if not scalar("SELECT 1 FROM devices WHERE id=?", (device_id,)):
        return False
    ts = ts or fmt_ts(NOW)
    with cursor() as conn:
        conn.execute("INSERT INTO readings(device_id, ts, value) VALUES (?,?,?)", (device_id, ts, value))
        conn.execute("UPDATE devices SET last_seen=? WHERE id=?", (ts, device_id))
    return True


# --- rules & alerts ---------------------------------------------------------

def rules_list() -> list[dict]:
    return rows("SELECT * FROM rules ORDER BY id")


def create_rule(name, domain, operator, threshold, severity) -> int | None:
    if operator not in OPERATORS or severity not in SEVERITIES:
        return None
    dom = domain if domain in DOMAIN_KEYS or domain == "any" else "any"
    try:
        thr = float(threshold)
    except (TypeError, ValueError):
        return None
    with cursor() as conn:
        conn.execute(
            "INSERT INTO rules(name,domain,operator,threshold,severity,enabled,created) "
            "VALUES (?,?,?,?,?,1,?)", ((name or "Rule").strip(), dom, operator, thr, severity, fmt_ts(NOW)))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def toggle_rule(rid: int):
    with cursor() as conn:
        conn.execute("UPDATE rules SET enabled = 1-enabled WHERE id=?", (rid,))


def delete_rule(rid: int):
    with cursor() as conn:
        conn.execute("DELETE FROM rules WHERE id=?", (rid,))


def _cmp(value, operator, threshold) -> bool:
    return {">": value > threshold, ">=": value >= threshold,
            "<": value < threshold, "<=": value <= threshold}.get(operator, False)


def evaluate_rules() -> list[dict]:
    """Evaluate enabled rules against each device's latest reading; raise new
    Active alerts (deduped against still-open alerts for the same rule+device)."""
    fired = []
    open_pairs = {(a["rule_id"], a["device_id"])
                  for a in rows("SELECT rule_id, device_id FROM alerts WHERE status IN ('Active','Acknowledged')")}
    latest = rows(
        """SELECT d.id device_id, d.name, d.code, d.domain, d.unit, r.value, r.ts
           FROM devices d
           JOIN readings r ON r.id = (SELECT id FROM readings r2 WHERE r2.device_id=d.id ORDER BY r2.ts DESC LIMIT 1)""")
    for rule in [r for r in rules_list() if r["enabled"]]:
        for lr in latest:
            if rule["domain"] != "any" and lr["domain"] != rule["domain"]:
                continue
            if not _cmp(lr["value"], rule["operator"], rule["threshold"]):
                continue
            if (rule["id"], lr["device_id"]) in open_pairs:
                continue
            msg = (f"{lr['name']} ({lr['code']}) = {lr['value']:g} {lr['unit'] or ''} "
                   f"{rule['operator']} {rule['threshold']:g}").strip()
            with cursor() as conn:
                conn.execute(
                    "INSERT INTO alerts(rule_id,device_id,value,ts,status,message,created) "
                    "VALUES (?,?,?,?,'Active',?,?)",
                    (rule["id"], lr["device_id"], lr["value"], lr["ts"], msg, fmt_ts(NOW)))
            open_pairs.add((rule["id"], lr["device_id"]))
            fired.append({"device": lr["name"], "code": lr["code"], "rule": rule["name"], "message": msg})
    return fired


def set_alert_status(aid: int, status: str):
    if status not in ALERT_STATUSES:
        return
    with cursor() as conn:
        conn.execute("UPDATE alerts SET status=? WHERE id=?", (status, aid))


# --- flows (low-code integration pipelines, stub) ---------------------------

def flows_list() -> list[dict]:
    return rows("SELECT * FROM flows ORDER BY id")


def flow(fid: int):
    return one("SELECT * FROM flows WHERE id=?", (fid,))


def create_flow(name, connector, source, transform, sink) -> int | None:
    if connector not in CONNECTORS:
        return None
    cfg = json.dumps({
        "connector": connector, "source": source, "transform": transform, "sink": sink,
        "note": "Stub pipeline — connector runtime not bundled. Compose with FIWARE / Node-RED / ThingsBoard.",
    }, indent=2)
    with cursor() as conn:
        conn.execute(
            "INSERT INTO flows(name,connector,source,transform,sink,enabled,config,created) "
            "VALUES (?,?,?,?,?,1,?,?)",
            ((name or "Flow").strip(), connector, source, transform, sink, cfg, fmt_ts(NOW)))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def toggle_flow(fid: int):
    with cursor() as conn:
        conn.execute("UPDATE flows SET enabled = 1-enabled WHERE id=?", (fid,))


def delete_flow(fid: int):
    with cursor() as conn:
        conn.execute("DELETE FROM flows WHERE id=?", (fid,))
