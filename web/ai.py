"""FastCity AI assistant — slash-commands + grounded multi-provider chat.

Slash-commands resolve locally against SQLite (no API key). Free-form chat is
streamed from a configurable provider and grounded with a live snapshot of the
sensor estate so answers reflect the actual devices, telemetry and alerts.
"""
from __future__ import annotations

import json
import os

import db

PROVIDER = os.getenv("MODEL_PROVIDER", "xai")
MODEL = os.getenv("MODEL_NAME", "grok-4-1-fast-reasoning")


def snapshot() -> str:
    k = db.kpis()
    by_status = {r["k"]: r["n"] for r in db.counts_by("status")}
    ac = db.alert_counts()
    lines = [
        "CURRENT SMART-CITY SNAPSHOT (synthetic demo data):",
        f"- Devices: {k['devices']} across {k['zones']} zones. "
        f"Live (Online/Maintenance): {k['online']}. Down (Offline/Fault): {k['down']}. Uptime {k['uptime']}%.",
        f"- Active alerts: {k['active_alerts']} (acknowledged {ac.get('Acknowledged',0)}, resolved {ac.get('Resolved',0)}). "
        f"Readings last 24h: {k['readings_24h']}.",
        "Devices by status: " + ", ".join(f"{s} {by_status.get(s,0)}" for s in db.DEVICE_STATUSES),
    ]
    for d in db.domain_summary():
        avg = f"{d['avg']} {d['unit']}" if d["avg"] is not None else "no recent data"
        lines.append(f"- {d['label']}: {d['devices']} sensors ({d['live']} live), "
                     f"latest avg {avg}, {d['alerts']} active alerts (threshold {d['high']} {d['unit']}).")
    active = db.alerts("Active", limit=6)
    if active:
        lines.append("Active alerts: " + "; ".join(f"{a['code']} {a['message']}" for a in active))
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the FastCity assistant, embedded in an open-source smart-city IoT data platform.
Help city operators monitor sensors, read telemetry trends across domains (traffic, parking, environment,
energy, waste, noise), triage alarms and check device health. Be concise and practical; use Markdown
(short tables, bold figures) when it helps. All data is synthetic demo data — never claim it is real.
Base answers on the SMART-CITY SNAPSHOT below; if something isn't in it, say so plainly rather than inventing."""


def _table(headers, rows_):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows_:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def handle_command(text: str):
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:])

    if cmd in ("help", "?"):
        return ("**FastCity shortcuts**\n\n"
                "- `/kpi` — headline city numbers\n"
                "- `/devices [status]` — device registry (e.g. `/devices Fault`)\n"
                "- `/domain <traffic|parking|environment|energy|waste|noise>` — a domain's sensors & latest values\n"
                "- `/alerts` — active alarms\n"
                "- `/rules` — configured alarm rules\n\nOr ask a question in plain English.")

    if cmd == "kpi":
        k = db.kpis()
        return _table(["Metric", "Value"], [
            ["Devices", k["devices"]], ["Live", k["online"]], ["Down", k["down"]],
            ["Uptime", f"{k['uptime']}%"], ["Active alerts", k["active_alerts"]],
            ["Readings 24h", f"{k['readings_24h']:,}"], ["Zones", k["zones"]]])

    if cmd == "devices":
        st = arg.title() if arg else "All"
        st = st if st in db.DEVICE_STATUSES else "All"
        devs = db.devices_list(status=st)
        if not devs:
            return f"No devices with status {st}."
        return f"**Devices{'' if st=='All' else ' — '+st}** ({len(devs)})\n\n" + _table(
            ["Code", "Name", "Domain", "Status", "Zone", "Last value"],
            [[d["code"], d["name"][:26], d["domain"], d["status"], d["zone"] or "—",
              f"{d['last_value']:g}" if d["last_value"] is not None else "—"] for d in devs[:15]])

    if cmd == "domain":
        dom = arg.lower().strip()
        if dom not in db.DOMAIN_KEYS:
            return f"Unknown domain `{dom}`. Try one of: {', '.join(db.DOMAIN_KEYS)}."
        devs = db.devices_list(domain=dom)
        meta = db.DOMAINS[dom]
        head = f"**{meta['label']}** — {meta['metric']} ({meta['unit']}), threshold {meta['high']}\n\n"
        return head + _table(
            ["Code", "Name", "Status", "Latest"],
            [[d["code"], d["name"][:28], d["status"],
              f"{d['last_value']:g} {meta['unit']}" if d["last_value"] is not None else "—"] for d in devs])

    if cmd == "alerts":
        al = db.alerts("Active")
        if not al:
            return "No active alerts. City is nominal. ✅"
        return "**Active alerts**\n\n" + _table(
            ["Sensor", "Severity", "Detail"],
            [[a["code"], a["severity"] or "—", (a["message"] or "")[:60]] for a in al[:15]])

    if cmd == "rules":
        rl = db.rules_list()
        return "**Alarm rules**\n\n" + _table(
            ["Rule", "Domain", "Condition", "Severity", "On"],
            [[r["name"][:30], r["domain"], f"{r['operator']} {r['threshold']:g}",
              r["severity"], "yes" if r["enabled"] else "no"] for r in rl])

    return f"Unknown command `/{cmd}`. Try `/help`."


async def stream_chat(message: str):
    cmd = handle_command(message)
    if cmd is not None:
        yield f"data: {json.dumps({'token': cmd})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
        return
    system = SYSTEM_PROMPT + "\n\n" + snapshot()
    try:
        async for tok in _provider_stream(system, message):
            yield f"data: {json.dumps({'token': tok})}\n\n"
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    yield f"data: {json.dumps({'done': True})}\n\n"


async def _provider_stream(system, message):
    import httpx
    provider, model = PROVIDER, MODEL
    if provider in ("xai", "openai"):
        url = "https://api.x.ai/v1/chat/completions" if provider == "xai" else "https://api.openai.com/v1/chat/completions"
        key = os.getenv("XAI_API_KEY" if provider == "xai" else "OPENAI_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, headers={"Authorization": f"Bearer {key}"},
                                     json={"model": model, "stream": True,
                                           "messages": [{"role": "system", "content": system},
                                                        {"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            tok = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", "https://api.anthropic.com/v1/messages",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                                     json={"model": model, "max_tokens": 1500, "stream": True,
                                           "system": system, "messages": [{"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            ev = json.loads(line[6:])
                            if ev.get("type") == "content_block_delta":
                                tok = ev.get("delta", {}).get("text", "")
                                if tok: yield tok
                        except json.JSONDecodeError:
                            pass
    elif provider == "google":
        key = os.getenv("GOOGLE_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={key}"
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            tok = json.loads(line[6:])["candidates"][0]["content"]["parts"][0].get("text", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    else:
        yield (f"No LLM provider configured (MODEL_PROVIDER='{provider}'). Set it to xai/openai/anthropic/google "
               "in `.env`. Slash-commands like `/alerts` work without a key.")


def _no_key(provider):
    env = {"xai": "XAI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}[provider]
    return (f"⚠ No **{env}** set, so free-form chat is disabled. Add it to `.env` and restart. "
            "Slash-commands (`/kpi`, `/devices`, `/domain`, `/alerts`, `/rules`) work without any key.")
