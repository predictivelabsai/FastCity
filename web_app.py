from web.landing import landing_page
"""FastCity — an open-source smart-city IoT data platform built with FastHTML.

A server-side, HTMX-driven analytics & management layer for a city sensor
estate: a device registry (pasportization), telemetry ingestion + time-series
dashboards, threshold alarms, low-code integration flows, and an AI assistant
grounded in the live (synthetic) telemetry.

Run:
    python web_app.py            # http://localhost:5011

Login: admin@fastcity.example / FastCity2026$  (override via .env)
"""
from __future__ import annotations

import os
import json
import secrets
import uuid
import logging

from dotenv import load_dotenv
load_dotenv()

from fasthtml.common import (
    fast_app, serve, Div, H1, P, Form, Input, Button, NotStr,
    RedirectResponse, Script, Style, Link, Title,
)
from starlette.responses import StreamingResponse, Response, JSONResponse
from starlette.routing import Route

import db
from web.layout import page, LAYOUT_CSS
from web import views, ai

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("fastcity")

VALID_EMAIL = os.getenv("FASTCITY_ADMIN_EMAIL", "admin@fastcity.example")
VALID_PASSWORD = os.getenv("FASTCITY_ADMIN_PASSWORD", "FastCity2026$")
ENV_LABEL = os.getenv("FASTCITY_ENV_LABEL", "FastCity")
SECRET = os.getenv("FASTCITY_SECRET", secrets.token_hex(32))
PORT = int(os.getenv("FASTCITY_PORT", "5011"))

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, hdrs=[Style(LAYOUT_CSS)])


def _user(session):
    return session.get("user")


def _thread(session):
    if "thread" not in session:
        session["thread"] = uuid.uuid4().hex
    return session["thread"]


def _guard(session, active, builder):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    content = builder() if callable(builder) else builder
    if not isinstance(content, tuple):
        content = (content,)
    return page(active, ENV_LABEL, _user(session), _thread(session), *content)


def _login_card(error="", email=""):
    return Title("FastCity — Sign in"), Style(LAYOUT_CSS), Div(
        Form(H1("FastCity"), P("Smart-city IoT data platform"),
             Input(name="email", type="email", placeholder="Email", value=email, required=True),
             Input(name="password", type="password", placeholder="Password", required=True),
             P(error, cls="error") if error else None,
             Button("Sign in", cls="btn primary", type="submit"),
             P(NotStr("Demo: <code>admin@fastcity.example</code> / <code>FastCity2026$</code>"), cls="hint"),
             method="post", action="/login", cls="login-card"), cls="login-wrap")


@rt("/login")
def get(session):
    if _user(session):
        return RedirectResponse("/", status_code=303)
    return _login_card()


@rt("/login")
def post(session, email: str = "", password: str = ""):
    if email.strip().lower() == VALID_EMAIL.lower() and password == VALID_PASSWORD:
        session["user"] = email.strip().lower()
        return RedirectResponse("/", status_code=303)
    return _login_card("Invalid email or password.", email)


@rt("/logout")
def get(session):
    session.pop("user", None)
    return RedirectResponse("/login", status_code=303)


# --- pages ------------------------------------------------------------------

@rt("/")
def get(session):
    if not _user(session):
        return landing_page()
    return _guard(session, "dashboard", views.dashboard)



@rt("/devices")
def get(session, domain: str = "All", status: str = "All", q: str = ""):
    return _guard(session, "devices", lambda: views.devices_list(domain, status, q))


@rt("/devices/{did}")
def get(session, did: int):
    return _guard(session, "devices", lambda: views.device_detail(did))


@rt("/map")
def get(session):
    return _guard(session, "map", views.map_view)


@rt("/dashboards")
def get(session):
    return _guard(session, "dashboards", views.dashboards)


@rt("/alerts")
def get(session, status: str = "Active"):
    return _guard(session, "alerts", lambda: views.alerts_view(status))


@rt("/flows")
def get(session):
    return _guard(session, "flows", views.flows_view)


@rt("/flows/{fid}")
def get(session, fid: int):
    return _guard(session, "flows", lambda: views.flow_detail(fid))


@rt("/ingest")
def get(session):
    return _guard(session, "ingest", views.ingest_view)


@rt("/guide")
def get(session):
    return _guard(session, "guide", views.guide_view)


@rt("/ai")
def get(session):
    return _guard(session, "ai", views.ai_landing)


# --- rules & alerts actions -------------------------------------------------

@rt("/rules/new")
def post(session, name: str = "", domain: str = "any", operator: str = ">",
         threshold: str = "", severity: str = "Warning"):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.create_rule(name, domain, operator, threshold, severity)
    return RedirectResponse("/alerts", status_code=303)


@rt("/rules/{rid}/toggle")
def post(session, rid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.toggle_rule(rid)
    return RedirectResponse("/alerts", status_code=303)


@rt("/rules/{rid}/delete")
def post(session, rid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.delete_rule(rid)
    return RedirectResponse("/alerts", status_code=303)


@rt("/rules/evaluate")
def post(session):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.evaluate_rules()
    return RedirectResponse("/alerts", status_code=303)


@rt("/alerts/{aid}/ack")
def post(session, aid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.set_alert_status(aid, "Acknowledged")
    return RedirectResponse("/alerts", status_code=303)


@rt("/alerts/{aid}/resolve")
def post(session, aid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.set_alert_status(aid, "Resolved")
    return RedirectResponse("/alerts", status_code=303)


# --- flows actions ----------------------------------------------------------

@rt("/flows/new")
def post(session, name: str = "", connector: str = "MQTT", source: str = "",
         transform: str = "", sink: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.create_flow(name, connector, source, transform, sink)
    return RedirectResponse("/flows", status_code=303)


@rt("/flows/{fid}/toggle")
def post(session, fid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.toggle_flow(fid)
    return RedirectResponse("/flows", status_code=303)


@rt("/flows/{fid}/delete")
def post(session, fid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.delete_flow(fid)
    return RedirectResponse("/flows", status_code=303)


# --- telemetry ingestion API (open, no auth — the integration surface) ------
# Registered as a raw Starlette route (below) so we own body parsing and can
# return clean JSON errors instead of FastHTML's param-introspection 500s.

async def ingest_telemetry(request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid JSON body"}, status_code=400)
    try:
        device_id = int(payload.get("device_id"))
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "device_id (int) and value (number) are required"}, status_code=400)
    ts = payload.get("ts")
    if db.add_reading(device_id, value, ts):
        return JSONResponse({"ok": True, "device_id": device_id, "value": value, "stored": ts or db.fmt_ts(db.NOW)})
    return JSONResponse({"ok": False, "error": f"unknown device_id {device_id}"}, status_code=404)


app.routes.append(Route("/api/telemetry", ingest_telemetry, methods=["POST"]))


# --- AI chat ----------------------------------------------------------------

@rt("/chat/new")
def get(session):
    session["thread"] = uuid.uuid4().hex
    return P("Ask about sensors, telemetry, domains or alerts — or tap a question below.",
             cls="chat-empty-hint")


@rt("/chat/stream")
async def post(session, message: str = "", thread_id: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    message = (message or "").strip()
    if not message:
        return Response("No message", status_code=400)
    tid = thread_id or _thread(session)

    async def gen():
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "user", message))
        full = []
        async for chunk in ai.stream_chat(message):
            if chunk.startswith("data: "):
                try:
                    tok = json.loads(chunk[6:]).get("token")
                    if tok:
                        full.append(tok)
                except Exception:
                    pass
            yield chunk
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "assistant", "".join(full)))

    return StreamingResponse(gen(), media_type="text/event-stream")


def _ensure_db():
    if not db.db_exists():
        logger.info("No database found — seeding synthetic data…")
        import seed
        seed.build()
    else:
        db.init_schema()  # idempotent


_ensure_db()

if __name__ == "__main__":
    logger.info("FastCity on http://localhost:%s  (login %s)", PORT, VALID_EMAIL)
    serve(port=PORT, reload=os.getenv("FASTCITY_RELOAD", "0") == "1")
