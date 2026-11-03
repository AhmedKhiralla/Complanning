"""Phase 5: production plans. Running the engine stores a plan; plans can be viewed, renamed, archived,
deleted and exported."""
from __future__ import annotations

import datetime as dt
import json
import time
from typing import Literal

from pydantic import BaseModel, Field

from ..api import ApiError, Call, endpoint, not_found
from ..engine.planner import ENGINE_VERSION, as_utc, build_plan, solve, summarise
from ..perms import require_plan
from .demand import _features, _today
from .excel import _autosize, _style_header, _wb, _xlsx

PLAN_SQL = """
SELECT p.id, p.site_id, p.name, p.status, p.objective, p.horizon_start, p.horizon_end, p.plan_date, p.starts_at,
       p.options, p.kpis, p.notes, p.created_at, p.updated_at, u.full_name AS created_by_name
  FROM plans p LEFT JOIN users u ON u.id = p.created_by
"""


class PlanIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    objective: Literal["on_time", "sales_value", "utilization"] = "on_time"
    horizon_start: dt.date | None = None
    horizon_end: dt.date | None = None
    include_quarantine: bool = False
    release_at_risk: bool = False
    cap_to_limit: bool = True
    material_constraints: bool = True
    max_early_days: int | None = Field(default=14, ge=0, le=180)
    notes: str | None = Field(default=None, max_length=500)


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=500)
    status: Literal["draft", "archived"] | None = None


def _plan(call: Call, plan_id: str) -> dict:
    p = call.tx.one(PLAN_SQL + " WHERE p.id = %s::uuid", plan_id)
    if not p:
        raise not_found("Plan")
    return p


@endpoint(auth="tenant_user")
def list_plans(call: Call):
    sid = call.path["site_id"]
    require_plan(call, sid)
    return {"items": call.tx.q(PLAN_SQL + " WHERE p.site_id = %s::uuid ORDER BY p.created_at DESC LIMIT 200", sid)}


@endpoint(auth="tenant_user", body=PlanIn)
def create_plan(call: Call):
    sid = call.path["site_id"]
    site = require_plan(call, sid, edit=True)
    b: PlanIn = call.body
    today = _today(call)
    start = b.horizon_start or today
    end = b.horizon_end or start + dt.timedelta(days=29)
    if end < start:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"horizon_end": "Must be on or after the start."})
    if (end - start).days > 186:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"horizon_end": "Choose a horizon of six months or less."})
    if end < today:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"horizon_end": "The horizon has already passed."})
    now = call.tx.val("SELECT now()").astimezone(dt.timezone.utc).replace(tzinfo=None)
    options = {"include_quarantine": b.include_quarantine, "release_at_risk": b.release_at_risk, "cap_to_limit": b.cap_to_limit,
               "material_constraints": b.material_constraints,
               "max_early_days": b.max_early_days}
    t0 = time.monotonic()
    model = build_plan(call.tx, {**site, "id": str(site["id"])}, start, end, b.objective, options, _features(call), now, today)
    sched, runs = solve(model)
    runtime = int((time.monotonic() - t0) * 1000)
    kpis = summarise(sched, runtime, runs)
    labels = {"on_time": "On-time delivery", "sales_value": "Sales value", "utilization": "Utilisation"}
    name = (b.name or "").strip() or f"{labels[b.objective]} · {start:%d %b} – {end:%d %b %Y}"
    plan = call.tx.one(
        "INSERT INTO plans (tenant_id, site_id, name, objective, horizon_start, horizon_end, plan_date, starts_at, options, kpis, notes)"
        " VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) RETURNING id",
        call.tenant_id, sid, name, b.objective, start, end, today, as_utc(model.start), json.dumps(options),
        json.dumps(kpis, default=_json), (b.notes or "").strip() or None)
    pid = plan["id"]

    # Batch numbers follow the start of production.
    order = sorted(model.batches, key=lambda x: (sched.done[x.key]["start"] if x.key in sched.done else dt.datetime.max, x.level, x.code))
    ids, numbers = {}, {}
    for n, bt in enumerate(order, start=1):
        dn = sched.done.get(bt.key)
        numbers[bt.key] = f"B{n:03d}"
        row = call.tx.one(
            "INSERT INTO plan_batches (tenant_id, plan_id, batch_no, item_id, level, quantity, bom_version, need_by, start_at, end_at,"
            " available_at, ship_at, status, problem, value, currency) VALUES (%s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING id",
            call.tenant_id, pid, numbers[bt.key], bt.item_id, bt.level, round(bt.qty, 3), bt.bom_version, as_utc(bt.need_by),
            as_utc(dn["start"]) if dn else None, as_utc(dn["end"]) if dn else None, as_utc(dn["available"]) if dn else None,
            as_utc(dn["ship"]) if dn else None, "scheduled" if dn else "unscheduled", sched.failed.get(bt.key),
            round(bt.value, 2) if bt.value else None, bt.currency)
        ids[bt.key] = row["id"]
    seqs: dict[int, int] = {}
    for o in sorted(sched.ops, key=lambda o: o.start):
        seqs[o.batch.key] = seqs.get(o.batch.key, 0) + 1
        call.tx.x(
            "INSERT INTO plan_operations (tenant_id, plan_id, batch_id, seq, step_name, resource_id, changeover_start, changeover_end,"
            " changeover_minutes, wait_minutes, changeover_kind, verification, reclean_minutes, start_at, end_at, work_minutes)"
            " VALUES (%s, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            call.tenant_id, pid, ids[o.batch.key], o.step.seq, o.step.name, o.machine.id, as_utc(o.co_start), as_utc(o.co_end),
            round(o.co_minutes, 2), round(o.co_wait, 2), o.co_kind, o.co_verification, round(o.reclean_minutes, 2),
            as_utc(o.start), as_utc(o.end), round(o.run_minutes, 2))
    for bt in model.batches:
        for sup, q in bt.suppliers:
            call.tx.x("INSERT INTO plan_links (tenant_id, plan_id, supplier_id, consumer_id, quantity) VALUES (%s, %s, %s, %s, %s)",
                      call.tenant_id, pid, ids[sup.key], ids[bt.key], round(q, 3))
    for x in sched.evaluate_demand():
        d = x["row"]
        call.tx.x(
            "INSERT INTO plan_demand (tenant_id, plan_id, demand_line_id, item_id, market_id, month, due_date, requested, quantity,"
            " from_stock, batches, available_at, late_hours, on_time, price, currency)"
            " VALUES (%s, %s, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, string_to_array(%s, ','), %s, %s, %s, %s, %s)",
            call.tenant_id, pid, d.line_id, d.item_id, d.market_id, d.month, d.due_date, round(d.requested, 3), round(d.quantity, 3),
            round(d.from_stock, 3), ",".join(numbers[b.key] for b, _ in d.sources) or None, as_utc(x["available"]),
            round(x["late_hours"], 1) if x["late_hours"] is not None else None, bool(x["on_time"]), d.price, d.currency)
    return _plan(call, str(pid))


def _json(o):
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat().replace("+00:00", "Z")
    raise TypeError(type(o).__name__)


@endpoint(auth="tenant_user")
def get_plan(call: Call):
    p = _plan(call, call.path["plan_id"])
    require_plan(call, p["site_id"])
    pid = p["id"]
    p["batches"] = call.tx.q(
        "SELECT b.id, b.batch_no, b.item_id, i.code, i.name_en, i.name_ar, i.type, i.cleaning_group, u.code AS uom, b.level, b.quantity,"
        " b.bom_version, b.need_by, b.start_at, b.end_at, b.available_at, b.ship_at, b.status, b.problem, b.value, b.currency"
        "  FROM plan_batches b JOIN items i ON i.id = b.item_id JOIN uoms u ON u.id = i.stock_uom_id"
        " WHERE b.plan_id = %s ORDER BY b.batch_no", pid)
    p["operations"] = call.tx.q(
        "SELECT o.id, o.batch_id, o.seq, o.step_name, o.resource_id, o.changeover_start, o.changeover_end, o.changeover_minutes,"
        " o.wait_minutes, o.changeover_kind, o.verification, o.reclean_minutes, o.start_at, o.end_at, o.work_minutes"
        "  FROM plan_operations o WHERE o.plan_id = %s ORDER BY o.start_at", pid)
    p["links"] = call.tx.q("SELECT supplier_id, consumer_id, quantity FROM plan_links WHERE plan_id = %s", pid)
    p["demand"] = call.tx.q(
        "SELECT d.id, d.item_id, i.code, i.name_en, i.name_ar, u.code AS uom, d.market_id, m.code AS market, d.month, d.due_date,"
        " d.requested, d.quantity, d.from_stock, array_to_string(d.batches, ', ') AS batches, d.available_at, d.late_hours, d.on_time, d.price, d.currency"
        "  FROM plan_demand d JOIN items i ON i.id = d.item_id JOIN uoms u ON u.id = i.stock_uom_id JOIN markets m ON m.id = d.market_id"
        " WHERE d.plan_id = %s ORDER BY d.due_date, i.code, m.code", pid)
    used = {str(o["resource_id"]) for o in p["operations"]}
    p["machines"] = [r for r in call.tx.q(
        "SELECT id, code, name_en, name_ar, area, type FROM resources WHERE site_id = %s ORDER BY area NULLS LAST, code", p["site_id"])
        if str(r["id"]) in used]
    p["downtime"] = call.tx.q(
        "SELECT resource_id, starts_at, ends_at, reason FROM resource_exceptions WHERE site_id = %s AND ends_at > %s AND starts_at < %s",
        p["site_id"], p["starts_at"], p["starts_at"] + dt.timedelta(days=200))
    return p


@endpoint(auth="tenant_user", body=PlanPatch)
def update_plan(call: Call):
    p = _plan(call, call.path["plan_id"])
    require_plan(call, p["site_id"], edit=True)
    b: PlanPatch = call.body
    sent = [f for f in ("name", "notes", "status") if f in b.model_fields_set]
    if sent:
        call.tx.x(f"UPDATE plans SET {', '.join(f + ' = %s' for f in sent)} WHERE id = %s",
                  *[getattr(b, f) for f in sent], p["id"])
    return _plan(call, str(p["id"]))


@endpoint(auth="tenant_user")
def delete_plan(call: Call):
    p = _plan(call, call.path["plan_id"])
    require_plan(call, p["site_id"], edit=True)
    call.tx.x("DELETE FROM plans WHERE id = %s", p["id"])
    return {"ok": True}


@endpoint(auth="tenant_user")
def export_plan(call: Call):
    p = _plan(call, call.path["plan_id"])
    site = require_plan(call, p["site_id"])
    tz = site["timezone"] or "UTC"
    local = lambda t: call.tx.val("SELECT to_char(%s AT TIME ZONE %s, 'YYYY-MM-DD HH24:MI')", t, tz) if t else None
    wb = _wb()
    ws = wb.active
    ws.title = "Plan"
    k = p["kpis"] or {}
    for row in (("Plan", p["name"]), ("Site", f"{site['code']} · {site['name']}"), ("Objective", p["objective"]),
                ("Horizon", f"{p['horizon_start']} to {p['horizon_end']}"), ("Prices valid on", str(p["plan_date"])),
                ("Times shown in", tz), ("Batches", k.get("batches")), ("On-time deliveries", f"{k.get('on_time')} of {k.get('demand_lines')}"),
                ("Changeover hours", k.get("changeover_hours")), ("Created by", p["created_by_name"]), ("Engine", k.get("engine"))):
        ws.append(list(row))
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60

    ws = wb.create_sheet("Batches")
    ws.append(["Batch", "Item", "Name", "Quantity", "Unit", "Start", "End", "Available", "Ship from", "Status", "Problem"])
    for b in call.tx.q("SELECT b.*, i.code, i.name_en, u.code AS uom FROM plan_batches b JOIN items i ON i.id = b.item_id"
                       " JOIN uoms u ON u.id = i.stock_uom_id WHERE b.plan_id = %s ORDER BY b.batch_no", p["id"]):
        ws.append([b["batch_no"], b["code"], b["name_en"], float(b["quantity"]), b["uom"], local(b["start_at"]), local(b["end_at"]),
                   local(b["available_at"]), local(b["ship_at"]), b["status"], b["problem"]])
    _style_header(ws); _autosize(ws)

    ws = wb.create_sheet("Machine schedule")
    ws.append(["Machine", "Batch", "Item", "Step", "Changeover from", "Changeover to", "Changeover", "Verification",
               "Start", "End", "Work (min)"])
    for o in call.tx.q("SELECT o.*, r.code AS machine, b.batch_no, i.code FROM plan_operations o JOIN resources r ON r.id = o.resource_id"
                       " JOIN plan_batches b ON b.id = o.batch_id JOIN items i ON i.id = b.item_id WHERE o.plan_id = %s"
                       " ORDER BY r.code, o.start_at", p["id"]):
        ws.append([o["machine"], o["batch_no"], o["code"], o["step_name"], local(o["changeover_start"]), local(o["changeover_end"]),
                   o["changeover_kind"], o["verification"], local(o["start_at"]), local(o["end_at"]), float(o["work_minutes"])])
    _style_header(ws); _autosize(ws)

    ws = wb.create_sheet("Deliveries")
    ws.append(["Product", "Market", "Due", "Requested", "Planned", "From stock", "Batches", "Available", "On time", "Late (h)"])
    for d in call.tx.q("SELECT d.*, array_to_string(d.batches, ', ') AS batch_list, i.code, m.code AS market FROM plan_demand d JOIN items i ON i.id = d.item_id"
                       " JOIN markets m ON m.id = d.market_id WHERE d.plan_id = %s ORDER BY d.due_date, i.code", p["id"]):
        ws.append([d["code"], d["market"], d["due_date"], float(d["requested"]), float(d["quantity"]), float(d["from_stock"]),
                   d["batch_list"], local(d["available_at"]), "yes" if d["on_time"] else "no",
                   float(d["late_hours"]) if d["late_hours"] is not None else None])
    _style_header(ws); _autosize(ws)
    stamp = call.tx.val("SELECT to_char(now(), 'YYYYMMDD-HH24MI')")
    return _xlsx(wb, f"complanning-plan-{site['code']}-{stamp}.xlsx", call, "plans")


__all__ = ["ENGINE_VERSION"]
