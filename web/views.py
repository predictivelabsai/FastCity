"""Center-pane page renderers for FastCity."""
from __future__ import annotations

import json

from fasthtml.common import (
    Div, H1, H3, H4, P, Span, A, Table, Thead, Tbody, Tr, Th, Td, Ul, Li,
    Strong, NotStr, Form, Input, Button, Select, Option, Script, Pre,
)

import db
from web.layout import kpi_card


def _pill(text, kind=""):
    return Span(text, cls="pill " + (kind or str(text)).lower().replace(" ", "").replace("/", ""))


def _title(title, sub="", *actions):
    return Div(Div(H1(title), P(sub, cls="sub") if sub else None),
               Div(*actions) if actions else None, cls="page-title")


def _ago(ts):
    return (ts or "")[:16]


def _status_dot(status):
    color = {"Online": "var(--ok)", "Maintenance": "var(--info)",
             "Offline": "var(--text-mute)", "Fault": "var(--breach)"}.get(status, "var(--text-mute)")
    return Span(Span(cls="dot", style=f"background:{color};"), status)


# ---------- inline SVG line chart (no external JS needed) -------------------

def svg_line(values, width=300, height=70, color="#0891b2", fill=True):
    """A compact sparkline from a list of numeric values."""
    if not values:
        return NotStr(f"<svg width='{width}' height='{height}'></svg>")
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    pad = 4
    def x(i): return pad + i * (width - 2 * pad) / max(1, n - 1)
    def y(v): return height - pad - (v - lo) / span * (height - 2 * pad)
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    area = ""
    if fill:
        area = (f"<polygon points='{x(0):.1f},{height-pad} {pts} {x(n-1):.1f},{height-pad}' "
                f"fill='{color}' opacity='0.12'/>")
    return NotStr(
        f"<svg width='100%' height='{height}' viewBox='0 0 {width} {height}' preserveAspectRatio='none'>"
        f"{area}<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='2' "
        f"stroke-linejoin='round' stroke-linecap='round'/></svg>")


# ---------- dashboard -------------------------------------------------------

def dashboard():
    k = db.kpis()
    summary = db.domain_summary()
    by_status = {r["k"]: r["n"] for r in db.counts_by("status")}

    # domain cards with sparkline of last 24h city-average
    dom_cards = []
    for d in summary:
        series = [r["v"] for r in db.domain_series(d["domain"], hours=24)]
        tone = "breach" if d["alerts"] else "ok"
        dom_cards.append(Div(
            Div(Span(d["icon"] + " "), Strong(d["label"]),
                Span(f"{d['live']}/{d['devices']} live", style="float:right;color:var(--text-mute);font-size:12px;"),
                style="margin-bottom:4px;"),
            Div(Span(f"{d['avg']:g}" if d["avg"] is not None else "—", cls="metric-big"),
                Span(f" {d['unit']}", cls="metric-unit")),
            svg_line(series or [0], color="#e11d48" if d["alerts"] else "#0891b2"),
            Div(_pill(f"{d['alerts']} alert" + ("s" if d["alerts"] != 1 else ""), "critical" if d["alerts"] else "ok2"),
                style="margin-top:6px;"),
            cls="card", style="margin-bottom:0;"))

    status_funnel = [Div(Div(_status_dot(s), style="color:var(--text-dim);"),
                         Div(Div(cls="funnel-bar",
                                 style=f"width:{max(2, 100*by_status.get(s,0)/max(1,k['devices'])):.0f}%;"
                                       f"background:{'var(--breach)' if s=='Fault' else 'var(--accent)'};")),
                         Div(str(by_status.get(s, 0)), cls="v"), cls="funnel-row")
                     for s in db.DEVICE_STATUSES]

    recent = db.alerts("Active", limit=8)
    alert_tbl = Table(
        Thead(Tr(Th("Sensor"), Th("Domain"), Th("Severity"), Th("Detail"), Th("When"))),
        Tbody(*[Tr(Td(A(a["code"], href=f"/devices/{a['device_id']}")),
                   Td(_pill(a["domain"] or "—")), Td(_pill(a["severity"] or "Info")),
                   Td((a["message"] or "")[:52]), Td(_ago(a["ts"]), style="color:var(--text-mute);"))
                for a in recent] or [Tr(Td("No active alerts 🎉", colspan="5"))]), cls="tbl")

    return (
        _title("City Operations Dashboard", "Live sensor estate & telemetry — fully synthetic demo data."),
        Div(kpi_card("Devices", k["devices"], f"{k['zones']} zones"),
            kpi_card("Live sensors", k["online"], f"{k['uptime']}% uptime", tone="ok"),
            kpi_card("Down", k["down"], "offline / fault", tone="breach" if k["down"] else "ok"),
            kpi_card("Active alerts", k["active_alerts"], "across all domains",
                     tone="breach" if k["active_alerts"] else "ok"),
            cls="kpi-grid"),
        Div(Div(H3("Domains — live city average (24h)"), cls="card-header"),
            Div(*dom_cards, cls="grid-3"), cls="card"),
        Div(Div(Div(H3("Devices by status"), cls="card-header"), *status_funnel, cls="card"),
            Div(Div(H3("Active alerts"), A("All alerts →", href="/alerts"), cls="card-header"), alert_tbl,
                cls="card"), cls="grid-2"),
    )


# ---------- device registry -------------------------------------------------

def devices_list(domain="All", status="All", q=""):
    dom_seg = Div(Span("Domain: ", style="color:var(--text-mute);font-size:12px;align-self:center;"),
                  *[A(("All" if d == "All" else db.DOMAINS[d]["label"]),
                      href=f"/devices?domain={d}&status={status}",
                      cls="" + ("active" if domain == d else "")) for d in ["All", *db.DOMAIN_KEYS]], cls="seg")
    st_seg = Div(Span("Status: ", style="color:var(--text-mute);font-size:12px;align-self:center;"),
                 *[A(s, href=f"/devices?domain={domain}&status={s}",
                     cls="" + ("active" if status == s else "")) for s in ["All", *db.DEVICE_STATUSES]], cls="seg")

    devs = db.devices_list(domain, status, q)
    tbl = Table(
        Thead(Tr(Th("Code"), Th("Name"), Th("Domain"), Th("Zone"), Th("Status"),
                 Th("Latest"), Th("Firmware"), Th("Last seen"))),
        Tbody(*[Tr(
            Td(A(d["code"], href=f"/devices/{d['id']}", cls="mono")),
            Td(A(d["name"][:34], href=f"/devices/{d['id']}")),
            Td(_pill(d["domain"])), Td(d["zone"] or "—"), Td(_status_dot(d["status"])),
            Td(f"{d['last_value']:g} {d['unit']}" if d["last_value"] is not None else "—"),
            Td(d["firmware"] or "—", cls="mono"),
            Td(_ago(d["last_seen"]) or "—", style="color:var(--text-mute);"),
        ) for d in devs] or [Tr(Td("No devices match.", colspan="8"))]), cls="tbl")

    search = Form(Input(type="search", name="q", value=q, placeholder="Search code, name, zone…"),
                  Input(type="hidden", name="domain", value=domain),
                  Input(type="hidden", name="status", value=status),
                  cls="toolbar", method="get", action="/devices")
    return (_title("Device Registry", f"{len(devs)} sensors — pasportization / asset registry",
                   A("🗺️ Map view", href="/map", cls="btn")),
            dom_seg, st_seg, search, Div(tbl, cls="card"))


def device_detail(did):
    d = db.device(did)
    if not d:
        return _title("Device not found"), P("No such device.")
    meta = db.DOMAINS.get(d["domain"], {})
    readings = db.readings_for(did, hours=72)
    values = [r["value"] for r in readings]

    chart = Div(svg_line(values or [0], width=640, height=180,
                         color="#e11d48" if d["status"] == "Fault" else "#0891b2"),
                style="width:100%;")
    stats = None
    if values:
        stats = Div(Span(f"latest {values[-1]:g} {d['unit']}", cls="pill neutral"),
                    Span(f"min {min(values):g}", cls="pill neutral"),
                    Span(f"max {max(values):g}", cls="pill neutral"),
                    Span(f"avg {sum(values)/len(values):.1f}", cls="pill neutral"),
                    style="display:flex;gap:8px;margin-top:8px;")

    recent = readings[-12:][::-1]
    read_tbl = Table(Thead(Tr(Th("Timestamp"), Th(f"Value ({d['unit']})"))),
                     Tbody(*[Tr(Td(_ago(r["ts"]), cls="mono"), Td(f"{r['value']:g}"))
                             for r in recent] or [Tr(Td("No telemetry.", colspan="2"))]), cls="tbl")

    info = Div(Div(H3("Device"), _status_dot(d["status"]), cls="card-header"),
               Div(Span("Asset code", cls="k"), Span(d["code"], cls="mono"),
                   Span("Domain", cls="k"), _pill(d["domain"]),
                   Span("Metric", cls="k"), Span(f"{d['metric']} ({d['unit']})"),
                   Span("Zone", cls="k"), Span(d["zone"] or "—"),
                   Span("Location", cls="k"), Span(f"{d['lat']}, {d['lng']}", cls="mono"),
                   Span("Firmware", cls="k"), Span(d["firmware"] or "—", cls="mono"),
                   Span("Installed", cls="k"), Span(d["installed"] or "—"),
                   Span("Last seen", cls="k"), Span(_ago(d["last_seen"]) or "—"),
                   cls="kv"), cls="card")

    ingest_hint = Div(Div(H3("Push a reading"), cls="card-header"),
                      P(NotStr(f"Feed telemetry for this sensor via the ingestion API:"), cls="sub"),
                      Pre(NotStr(f"curl -X POST localhost:5011/api/telemetry \\\n"
                                 f"  -H 'Content-Type: application/json' \\\n"
                                 f"  -d '{{\"device_id\": {did}, \"value\": 42.0}}'"), cls="code"),
                      cls="card")

    return (_title(d["name"], f"{d['code']} · {meta.get('label','')}",
                   A("← Registry", href="/devices", cls="btn")),
            Div(Div(Div(Div(H3(f"Telemetry — last 72h ({d['unit']})"), cls="card-header"), chart, stats, cls="card"),
                    Div(Div(H3("Recent readings"), cls="card-header"), read_tbl, cls="card")),
                Div(info, ingest_hint), cls="detail-grid"))


# ---------- city map (self-contained SVG) -----------------------------------

DOMAIN_COLOR = {"traffic": "#4f46e5", "parking": "#0891b2", "environment": "#16a34a",
                "energy": "#d97706", "waste": "#9333ea", "noise": "#e11d48"}


def map_view():
    devs = db.map_devices()
    W, H = 900, 520
    if devs:
        lats = [d["lat"] for d in devs]; lngs = [d["lng"] for d in devs]
        minlat, maxlat = min(lats), max(lats); minlng, maxlng = min(lngs), max(lngs)
        dlat = (maxlat - minlat) or 0.01; dlng = (maxlng - minlng) or 0.01
    else:
        minlat = maxlat = minlng = maxlng = dlat = dlng = 1
    pad = 40

    def px(lng): return pad + (lng - minlng) / dlng * (W - 2 * pad)
    def py(lat): return H - pad - (lat - minlat) / dlat * (H - 2 * pad)

    # subtle grid
    grid = "".join(
        f"<line x1='{pad + i*(W-2*pad)/8:.0f}' y1='{pad}' x2='{pad + i*(W-2*pad)/8:.0f}' y2='{H-pad}' "
        f"stroke='#c7d8e2' stroke-width='1'/>" for i in range(9))
    grid += "".join(
        f"<line x1='{pad}' y1='{pad + i*(H-2*pad)/6:.0f}' x2='{W-pad}' y2='{pad + i*(H-2*pad)/6:.0f}' "
        f"stroke='#c7d8e2' stroke-width='1'/>" for i in range(7))

    dots = ""
    for d in devs:
        c = DOMAIN_COLOR.get(d["domain"], "#0891b2")
        stroke = "#e11d48" if d["status"] in ("Fault",) else ("#94a3b8" if d["status"] == "Offline" else "#ffffff")
        op = 0.45 if d["status"] == "Offline" else 1.0
        cx, cy = px(d["lng"]), py(d["lat"])
        dots += (f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='7' fill='{c}' opacity='{op}' "
                 f"stroke='{stroke}' stroke-width='2'><title>{d['code']} · {d['name']} · {d['status']}</title></circle>")

    svg = NotStr(
        f"<svg width='100%' viewBox='0 0 {W} {H}' style='display:block;background:#dbeaf0;'>"
        f"<rect x='0' y='0' width='{W}' height='{H}' fill='#e8f1f6'/>{grid}{dots}</svg>")

    legend_items = [Span(Span(cls="dot", style=f"background:{DOMAIN_COLOR[d]};"), db.DOMAINS[d]["label"])
                    for d in db.DOMAIN_KEYS]
    legend = Div(*legend_items, Span(Span(cls="dot", style="background:#fff;border:2px solid #e11d48;"), "Fault"),
                 Span(Span(cls="dot", style="background:#94a3b8;opacity:.5;"), "Offline"), cls="map-legend")

    return (_title("City Map", f"{len(devs)} geolocated sensors — plotted by lat/lng",
                   A("Registry →", href="/devices", cls="btn")),
            Div(P(NotStr("Self-contained schematic map (no tile server needed). Each sensor carries "
                         "<code>lat</code>/<code>lng</code>, so this is drop-in ready for Leaflet/MapLibre in production."),
                  cls="callout"),
                Div(svg, cls="map-wrap"), legend, cls="card"))


# ---------- domain dashboards (Plotly) --------------------------------------

def dashboards():
    summary = {d["domain"]: d for d in db.domain_summary()}
    blocks = [_title("Domain Dashboards", "Telemetry time-series (72h city average) per IoT domain.")]

    traces, scripts = [], []
    for i, dom in enumerate(db.DOMAIN_KEYS):
        if dom not in summary:
            continue
        meta = db.DOMAINS[dom]
        series = db.domain_series(dom, hours=72)
        xs = [r["bucket"][:16] for r in series]
        ys = [r["v"] for r in series]
        s = summary[dom]
        div_id = f"chart-{dom}"
        color = DOMAIN_COLOR.get(dom, "#0891b2")
        # Plotly renders client-side; embed data + threshold line.
        fig = {
            "data": [{"x": xs, "y": ys, "type": "scatter", "mode": "lines",
                      "line": {"color": color, "width": 2}, "fill": "tozeroy",
                      "fillcolor": color + "22", "name": meta["metric"]}],
            "layout": {
                "margin": {"l": 40, "r": 12, "t": 8, "b": 30},
                "height": 240, "showlegend": False,
                "xaxis": {"showgrid": False, "tickfont": {"size": 10}},
                "yaxis": {"title": meta["unit"], "gridcolor": "#e6eef4", "tickfont": {"size": 10}},
                "shapes": [{"type": "line", "x0": 0, "x1": 1, "xref": "paper",
                            "y0": meta["high"], "y1": meta["high"],
                            "line": {"color": "#e11d48", "width": 1, "dash": "dash"}}],
                "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
            },
        }
        header = Div(Span(meta["icon"] + " "), H3(meta["label"], style="display:inline;"),
                     Span(f"avg {s['avg']:g} {meta['unit']}" if s["avg"] is not None else "no data",
                          style="float:right;color:var(--text-mute);font-size:13px;"),
                     cls="card-header")
        sub = Div(_pill(f"{s['live']}/{s['devices']} live", "ok2"),
                  _pill(f"threshold {meta['high']} {meta['unit']}", "neutral"),
                  _pill(f"{s['alerts']} active alert" + ("s" if s["alerts"] != 1 else ""),
                        "critical" if s["alerts"] else "ok2"),
                  style="display:flex;gap:8px;margin-bottom:10px;")
        blocks.append(Div(header, sub, Div(id=div_id, cls="chart-box"),
                          Div(svg_line(ys or [0], width=640, height=60, color=color),
                              style="margin-top:6px;"),
                          Script(NotStr(
                              f"(function(){{var el=document.getElementById('{div_id}');"
                              f"if(window.Plotly&&el){{Plotly.newPlot('{div_id}',{json.dumps(fig['data'])},"
                              f"{json.dumps(fig['layout'])},{{displayModeBar:false,responsive:true}});}}}})();")),
                          cls="card"))
    if len(blocks) == 1:
        blocks.append(Div(P("No telemetry yet — run seed.py."), cls="card"))
    return tuple(blocks)


# ---------- alarms & alerts -------------------------------------------------

def alerts_view(status="Active"):
    counts = db.alert_counts()
    seg = Div(*[A(f"{s} ({counts.get(s,0) if s!='All' else sum(counts.values())})",
                  href=f"/alerts?status={s}",
                  cls="" + ("active" if status == s else ""))
                for s in ["Active", "Acknowledged", "Resolved", "All"]], cls="seg")

    al = db.alerts(status)
    rows_ = []
    for a in al:
        actions = []
        if a["status"] == "Active":
            actions.append(Form(Button("Ack", cls="btn sm", type="submit"),
                                method="post", action=f"/alerts/{a['id']}/ack", style="display:inline;"))
        if a["status"] != "Resolved":
            actions.append(Form(Button("Resolve", cls="btn sm primary", type="submit"),
                                method="post", action=f"/alerts/{a['id']}/resolve", style="display:inline;"))
        rows_.append(Tr(
            Td(A(a["code"] or "—", href=f"/devices/{a['device_id']}", cls="mono")),
            Td(_pill(a["domain"] or "—")), Td(_pill(a["severity"] or "Info")),
            Td((a["message"] or "")[:60]), Td(_pill(a["status"])),
            Td(_ago(a["ts"]), style="color:var(--text-mute);"),
            Td(Div(*actions, style="display:flex;gap:6px;"))))
    tbl = Table(Thead(Tr(Th("Sensor"), Th("Domain"), Th("Severity"), Th("Detail"),
                        Th("Status"), Th("When"), Th(""))),
                Tbody(*rows_ or [Tr(Td("No alerts in this view.", colspan="7"))]), cls="tbl")

    # rules panel
    rules = db.rules_list()
    rule_rows = []
    for r in rules:
        rule_rows.append(Tr(
            Td(Strong(r["name"])), Td(_pill(r["domain"]) if r["domain"] != "any" else Span("any")),
            Td(Span(f"{r['operator']} {r['threshold']:g}", cls="mono")),
            Td(_pill(r["severity"])),
            Td(_pill("On", "ok2") if r["enabled"] else _pill("Off", "neutral")),
            Td(Div(Form(Button("Disable" if r["enabled"] else "Enable", cls="btn sm", type="submit"),
                        method="post", action=f"/rules/{r['id']}/toggle", style="display:inline;"),
                   Form(Button("🗑", cls="btn sm danger", type="submit"),
                        method="post", action=f"/rules/{r['id']}/delete", style="display:inline;"),
                   style="display:flex;gap:6px;"))))
    rules_tbl = Table(Thead(Tr(Th("Rule"), Th("Domain"), Th("Condition"), Th("Severity"), Th("On"), Th(""))),
                      Tbody(*rule_rows or [Tr(Td("No rules.", colspan="6"))]), cls="tbl")

    add = Form(
        Div(Input(name="name", placeholder="Rule name", required=True),
            Select(Option("any", value="any"), *[Option(db.DOMAINS[d]["label"], value=d) for d in db.DOMAIN_KEYS],
                   name="domain"),
            Select(*[Option(o, value=o) for o in db.OPERATORS], name="operator"),
            Input(name="threshold", type="number", step="any", placeholder="Threshold", required=True,
                  style="width:120px;"),
            Select(*[Option(s, value=s) for s in db.SEVERITIES], name="severity"),
            Button("Add rule", cls="btn primary", type="submit"),
            cls="form-row"),
        method="post", action="/rules/new")

    return (_title("Alarms & Alerts",
                   "Threshold rules evaluate the latest reading per sensor and raise alerts.",
                   Form(Button("⚙ Evaluate rules now", cls="btn primary", type="submit"),
                        method="post", action="/rules/evaluate", style="display:inline;")),
            seg, Div(Div(H3("Alerts"), cls="card-header"), tbl, cls="card"),
            Div(Div(H3("Alarm rules"), cls="card-header"), rules_tbl, cls="card"),
            Div(Div(H3("New rule"), cls="card-header"), add, cls="card"))


# ---------- data flows (low-code integration, stub) -------------------------

def flows_view():
    flows = db.flows_list()
    rows_ = []
    for f in flows:
        rows_.append(Tr(
            Td(Strong(f["name"])), Td(_pill(f["connector"], "neutral")),
            Td(f["source"] or "—", cls="mono"), Td(f["sink"] or "—", cls="mono"),
            Td(_pill("On", "ok2") if f["enabled"] else _pill("Off", "neutral")),
            Td(Div(A("View", href=f"/flows/{f['id']}", cls="btn sm"),
                   Form(Button("Disable" if f["enabled"] else "Enable", cls="btn sm", type="submit"),
                        method="post", action=f"/flows/{f['id']}/toggle", style="display:inline;"),
                   Form(Button("🗑", cls="btn sm danger", type="submit"),
                        method="post", action=f"/flows/{f['id']}/delete", style="display:inline;"),
                   style="display:flex;gap:6px;"))))
    tbl = Table(Thead(Tr(Th("Flow"), Th("Connector"), Th("Source"), Th("Sink"), Th("On"), Th(""))),
                Tbody(*rows_ or [Tr(Td("No flows yet.", colspan="6"))]), cls="tbl")

    add = Form(
        Div(Input(name="name", placeholder="Flow name", required=True),
            Select(*[Option(c, value=c) for c in db.CONNECTORS], name="connector"),
            Input(name="source", placeholder="Source (topic / endpoint / register)", style="flex:1;min-width:200px;"),
            cls="form-row"),
        Div(Input(name="transform", placeholder="Transform (decode / scale / map)", style="flex:1;min-width:200px;"),
            Input(name="sink", placeholder="Sink (readings table / warehouse)", style="flex:1;min-width:180px;"),
            Button("Add flow", cls="btn primary", type="submit"),
            cls="form-row"),
        method="post", action="/flows/new")

    return (_title("Data Flows", f"{len(flows)} low-code integration pipelines (config-defined)"),
            Div(P(NotStr("Flows are <strong>declarative connector configs</strong> — the integration surface of the "
                         "platform. FastCity ships the registry, telemetry store, dashboards and alarms; the connector "
                         "<em>runtime</em> (MQTT / MODBUS / REST) is stubbed here and composes with FIWARE, "
                         "Node-RED or ThingsBoard for the full bus. No vendor lock-in."), cls="callout"),
                Div(H3("Pipelines"), cls="card-header"), tbl, cls="card"),
            Div(Div(H3("New flow"), cls="card-header"), add, cls="card"))


def flow_detail(fid):
    f = db.flow(fid)
    if not f:
        return _title("Flow not found"), P("No such flow.")
    return (_title(f["name"], f"{f['connector']} connector · config-defined pipeline",
                   A("← Flows", href="/flows", cls="btn")),
            Div(Div(H3("Pipeline"), _pill("On", "ok2") if f["enabled"] else _pill("Off", "neutral"), cls="card-header"),
                Div(Span("Connector", cls="k"), _pill(f["connector"], "neutral"),
                    Span("Source", cls="k"), Span(f["source"] or "—", cls="mono"),
                    Span("Transform", cls="k"), Span(f["transform"] or "—", cls="mono"),
                    Span("Sink", cls="k"), Span(f["sink"] or "—", cls="mono"), cls="kv"), cls="card"),
            Div(Div(H3("config.json"), cls="card-header"), Pre(f["config"] or "{}", cls="code"), cls="card"))


# ---------- ingestion API doc -----------------------------------------------

def ingest_view():
    k = db.kpis()
    sample = db.devices_list()[:1]
    did = sample[0]["id"] if sample else 1
    return (_title("Telemetry Ingestion API", "The single write path sensors / connectors call to push readings."),
            Div(P(NotStr("This is the platform's open ingestion endpoint. Any connector (MQTT bridge, MODBUS poller, "
                         "REST puller) normalises readings and POSTs them here. Open API, JSON, no vendor lock-in."),
                  cls="callout"),
                Div(H3("POST /api/telemetry"), cls="card-header"),
                P("Body: ", Span("{ \"device_id\": int, \"value\": number, \"ts\"?: \"YYYY-MM-DD HH:MM:SS\" }", cls="mono")),
                Pre(NotStr(f"curl -X POST localhost:5011/api/telemetry \\\n"
                           f"  -H 'Content-Type: application/json' \\\n"
                           f"  -d '{{\"device_id\": {did}, \"value\": 42.0}}'\n\n"
                           f"# → {{\"ok\": true, \"device_id\": {did}, \"value\": 42.0, \"stored\": \"...\"}}"), cls="code"),
                cls="card"),
            Div(Div(H3("Status"), cls="card-header"),
                Div(Span("Readings (24h)", cls="k"), Span(f"{k['readings_24h']:,}"),
                    Span("Live sensors", cls="k"), Span(f"{k['online']} / {k['devices']}"),
                    cls="kv"), cls="card"))


# ---------- user guide ------------------------------------------------------

def guide_view():
    return (_title("User Guide", "How to drive FastCity"), Div(NotStr("""
<div class='card'><h3>Dashboard</h3><p>City-wide KPIs (devices, live sensors, down, active alerts), a per-domain
live average with sparklines, device-status breakdown and the active-alert worklist.</p></div>
<div class='card'><h3>Device Registry & Map</h3><p>The sensor "pasportization": every device with its asset code,
domain, zone, geolocation, firmware and last-seen. Open a device for its 72h telemetry chart and recent readings.
The <strong>City Map</strong> plots all sensors by lat/lng (self-contained SVG, Leaflet-ready).</p></div>
<div class='card'><h3>Domain Dashboards</h3><p>Plotly time-series of the 72h city average per domain (traffic, parking,
environment, energy, waste, noise), with the alarm threshold drawn in.</p></div>
<div class='card'><h3>Alarms & Alerts</h3><p>Threshold rules (<code>domain · operator · value · severity</code>)
evaluate each sensor's latest reading. Add rules, run evaluation, then acknowledge/resolve the alerts raised.</p></div>
<div class='card'><h3>Data Flows</h3><p>Low-code, config-defined integration pipelines (MQTT / MODBUS / REST / HTTP /
CoAP). The connector runtime is stubbed — this is the integration <em>surface</em>; compose with FIWARE / Node-RED /
ThingsBoard for the full bus.</p></div>
<div class='card'><h3>Ingestion API</h3><p><code>POST /api/telemetry</code> — the open write path connectors call to
push readings. Try the curl example on the Ingestion page or a device page.</p></div>
<div class='card'><h3>AI Assistant</h3><p>The right rail chats over a live snapshot of the estate. Set
<code>MODEL_PROVIDER</code> + an API key in <code>.env</code> for free-form chat; slash-commands
(<code>/kpi</code> <code>/devices</code> <code>/domain</code> <code>/alerts</code> <code>/rules</code>) always work.</p></div>
""")))


def ai_landing():
    return (_title("AI Assistant", "Chat lives in the right rail. Ask in plain English or use slash-commands."),
            Div(NotStr(
                "<div class='card'><h3>What you can ask</h3><ul style='line-height:1.8;'>"
                "<li>“Which sensors are offline or faulty?”</li>"
                "<li>“What's the air quality across the city right now?”</li>"
                "<li>“Summarise active alerts by severity.”</li>"
                "<li>“Which domain has the most alerts?”</li></ul>"
                "<p style='color:var(--text-mute)'>Slash-commands resolve instantly with no API key: "
                "<code>/kpi</code> <code>/devices</code> <code>/domain</code> <code>/alerts</code> "
                "<code>/rules</code> <code>/help</code></p></div>")))
