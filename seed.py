"""Generate a fully synthetic FastCity database (deterministic, no PII).

Builds a small smart-city sensor estate: districts (zones), devices across six
IoT domains, ~3 days of hourly telemetry with realistic diurnal patterns, a set
of threshold alarm rules (already evaluated into alerts), and a few example
low-code integration flows.
"""
from __future__ import annotations

import math
import random
from datetime import timedelta

import db

RNG = random.Random(20260716)
NOW = db.NOW

# A fictional mid-size smart city. Coordinates are plausible (Central-Europe box)
# but the district names and everything else are synthetic.
CITY_LAT, CITY_LNG = 48.146, 17.107
ZONES = [
    ("Old Town",          48.144, 17.108),
    ("Riverside",         48.138, 17.116),
    ("Industrial Park",   48.158, 17.128),
    ("University Quarter", 48.151, 17.095),
    ("Harbour",           48.133, 17.130),
    ("Northgate",         48.163, 17.101),
]

# How many sensors of each domain to deploy.
DEVICE_PLAN = {
    "traffic": 8,
    "parking": 7,
    "environment": 6,
    "energy": 6,
    "waste": 5,
    "noise": 4,
}
DOMAIN_PREFIX = {"traffic": "TRF", "parking": "PRK", "environment": "ENV",
                 "energy": "ENR", "waste": "WST", "noise": "NOI"}
DOMAIN_NOUN = {"traffic": "Flow counter", "parking": "Bay sensor",
               "environment": "Air-quality probe", "energy": "Power meter",
               "waste": "Fill-level sensor", "noise": "Sound monitor"}
FIRMWARES = ["1.4.2", "2.0.1", "2.1.0", "3.0.0-rc2", "1.9.7"]

HOURS = 72          # 3 days of hourly telemetry


def _series(domain: str, device_seed: int) -> list[float]:
    """Deterministic diurnal series for one device over the last HOURS hours."""
    meta = db.DOMAINS[domain]
    base, amp = meta["base"], meta["amp"]
    r = random.Random(device_seed)
    phase = r.uniform(0, 1.2)               # per-device offset
    device_bias = r.uniform(-0.12, 0.18) * base
    vals = []
    for h in range(HOURS + 1):
        clock = (NOW - timedelta(hours=HOURS - h))
        hour = clock.hour
        # two rush peaks for traffic/noise/energy; midday dip for parking availability
        if domain in ("traffic", "noise", "energy"):
            daily = math.sin((hour - 7) / 24 * 2 * math.pi) + 0.6 * math.sin((hour - 17) / 12 * 2 * math.pi)
        elif domain == "parking":
            daily = math.sin((hour - 13) / 24 * 2 * math.pi)
        else:  # environment, waste — slow build
            daily = math.sin((hour - 15) / 24 * 2 * math.pi) * 0.6
        v = base + device_bias + amp * 0.5 * (daily + math.sin(phase + h / 9))
        v += r.uniform(-amp * 0.12, amp * 0.12)
        if domain in ("parking", "waste"):
            v = max(0, min(100, v))
        else:
            v = max(0, v)
        vals.append(round(v, 2))
    return vals


def build():
    db.init_schema()
    with db.cursor() as conn:
        for t in ("chat_messages", "alerts", "rules", "flows", "readings", "devices", "zones"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany("INSERT INTO zones(name,lat,lng) VALUES (?,?,?)", ZONES)
        zone_rows = conn.execute("SELECT id,lat,lng FROM zones").fetchall()
    zone_ids = [z["id"] for z in zone_rows]
    zone_by_id = {z["id"]: z for z in zone_rows}

    # devices
    devices = []
    counters = {d: 0 for d in DEVICE_PLAN}
    for domain, n in DEVICE_PLAN.items():
        meta = db.DOMAINS[domain]
        for _ in range(n):
            counters[domain] += 1
            code = f"{DOMAIN_PREFIX[domain]}-{counters[domain]:04d}"
            zid = RNG.choice(zone_ids)
            z = zone_by_id[zid]
            lat = round(z["lat"] + RNG.uniform(-0.006, 0.006), 6)
            lng = round(z["lng"] + RNG.uniform(-0.008, 0.008), 6)
            # ~80% online, some maintenance / offline / fault
            status = RNG.choices(db.DEVICE_STATUSES, weights=[78, 8, 8, 6])[0]
            installed = (NOW - timedelta(days=RNG.randint(60, 900))).strftime("%Y-%m-%d")
            name = f"{meta['label']} {DOMAIN_NOUN[domain].lower()} {counters[domain]}"
            devices.append((code, name, domain, zid, lat, lng, status,
                            meta["metric"], meta["unit"], RNG.choice(FIRMWARES), installed))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO devices(code,name,domain,zone_id,lat,lng,status,metric,unit,firmware,installed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""", devices)
        drows = conn.execute("SELECT id,domain,status FROM devices ORDER BY id").fetchall()

    # telemetry — online/maintenance devices report; offline/fault do not (or stop early)
    reading_rows, n_readings = [], 0
    last_seen_updates = []
    for d in drows:
        did, domain, status = d["id"], d["domain"], d["status"]
        vals = _series(domain, did * 101 + 7)
        if status == "Offline":
            cutoff = len(vals) - RNG.randint(20, 50)      # went dark a while ago
        elif status == "Fault":
            cutoff = len(vals) - RNG.randint(2, 8)        # very recent last reading, then spikes
        else:
            cutoff = len(vals)
        last_ts = None
        for h, v in enumerate(vals[:cutoff]):
            ts = db.fmt_ts(NOW - timedelta(hours=HOURS - h))
            # faulty sensors emit a wild last value that trips alarms
            if status == "Fault" and h == cutoff - 1:
                v = round(v + db.DOMAINS[domain]["amp"] * 2.2, 2)
            reading_rows.append((did, ts, v))
            last_ts = ts
            n_readings += 1
        if last_ts:
            last_seen_updates.append((last_ts, did))
    with db.cursor() as conn:
        conn.executemany("INSERT INTO readings(device_id,ts,value) VALUES (?,?,?)", reading_rows)
        conn.executemany("UPDATE devices SET last_seen=? WHERE id=?", last_seen_updates)

    # alarm rules — one "high" rule per domain (from DOMAINS[*]['high']) + a couple extra
    created = db.fmt_ts(NOW)
    rules = []
    for dom, meta in db.DOMAINS.items():
        sev = "Critical" if dom in ("traffic", "environment", "energy") else "Warning"
        rules.append((f"{meta['label']}: {meta['metric']} high", dom, ">", float(meta["high"]), sev, 1))
    rules.append(("Parking almost full", "parking", ">=", 95.0, "Info", 1))
    rules.append(("Air quality unhealthy", "environment", ">", 35.0, "Warning", 1))
    with db.cursor() as conn:
        conn.executemany(
            "INSERT INTO rules(name,domain,operator,threshold,severity,enabled,created) "
            "VALUES (?,?,?,?,?,?,?)", [(*r, created) for r in rules])

    # evaluate rules to seed the alerts list
    fired = db.evaluate_rules()

    # example low-code integration flows (stubs)
    flows = [
        ("Traffic MQTT → warehouse", "MQTT", "city/traffic/# (broker :1883)",
         "decode JSON · unit=veh/min · dedupe", "readings table + Grafana"),
        ("Parking bays MODBUS poll", "MODBUS/TCP", "bay-controllers 10.20.0.0/24 :502",
         "scale register/10 · map bay→device", "readings table"),
        ("Air-quality REST pull", "REST", "GET vendor-api/v2/aq (5 min)",
         "select PM2.5 · °C→normalise", "readings + alert engine"),
        ("Energy meters HTTP webhook", "HTTP", "POST /api/telemetry",
         "validate schema · derive kW", "readings table"),
    ]
    with db.cursor() as conn:
        for f in flows:
            db.create_flow(*f)

    print(f"FastCity seeded → {db.DB_PATH}")
    print(f"  {len(ZONES)} zones · {len(devices)} devices · {n_readings} readings · "
          f"{len(rules)} rules · {len(fired)} alerts · {len(flows)} flows")


if __name__ == "__main__":
    build()
