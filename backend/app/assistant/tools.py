"""Read-only tools the assistant may call. Each runs inside the user's own session (row-level security and the same
permission checks as the screens), so the assistant never sees more than the user can."""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg

from ..api import ApiError, Call
from ..defaults import effective_features
from ..netting import net_requirements
from ..perms import require_plan, require_site
from . import knowledge


class Ctx:
    def __init__(self, call: Call, site: dict | None, plan_id: str | None):
        self.call, self.site, self.plan_id = call, site, plan_id
        self.tz = ZoneInfo((site or {}).get("timezone") or "UTC")
        self.used: list[dict] = []          # what the answer was based on, shown to the user

    def t(self, v):
        """Datetimes in the site's time zone, dates as ISO, decimals as floats."""
        if isinstance(v, dt.datetime):
            return v.astimezone(self.tz).strftime("%Y-%m-%d %H:%M")
        if isinstance(v, dt.date):
            return v.isoformat()
        if isinstance(v, Decimal):
            f = float(v)
            return int(f) if f == int(f) else round(f, 3)
        if isinstance(v, float):
            return round(v, 3)
        return v

    def clean(self, row: dict, keys=None) -> dict:
        return {k: self.t(v) for k, v in row.items() if (keys is None or k in keys) and v is not None}

    def need_site(self) -> dict:
        if not self.site:
            raise ApiError(422, "no_site", "No site is selected.")
        return self.site


def _plan(ctx: Ctx, plan_id: str | None) -> dict:
    pid = plan_id or ctx.plan_id
    if not pid:
        raise ApiError(422, "no_plan", "No plan given. Call list_plans first and pass a plan_id.")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(pid)):
        raise ApiError(422, "invalid", "plan_id must be the plan's id from list_plans.")
    try:
        p = ctx.call.tx.one("SELECT id, site_id, name, status, objective, horizon_start, horizon_end, kpis, options, created_at, released_at"
                            " FROM plans WHERE id = %s::uuid", str(pid))
    except Exception:
        raise ApiError(404, "not_found", "Plan was not found.")
    if not p:
        raise ApiError(404, "not_found", "Plan was not found.")
    require_plan(ctx.call, p["site_id"])
    ctx.used.append({"kind": "plan", "id": str(p["id"]), "label": p["name"]})
    return p


# ------------------------------------------------------------------ tools
def search_help(ctx: Ctx, query: str) -> dict:
    hits = knowledge.search(query)
    ctx.used.append({"kind": "manual", "label": ", ".join(h["section"] for h in hits) or "manual"})
    return {"results": hits} if hits else {"results": [], "note": "Nothing in the user manual matches."}


def list_plans(ctx: Ctx, include_archived: bool = False) -> dict:
    site = ctx.need_site()
    require_plan(ctx.call, site["id"])
    rows = ctx.call.tx.q("SELECT id, name, status, objective, horizon_start, horizon_end, created_at, kpis FROM plans"
                         " WHERE site_id = %s AND (%s OR status <> 'archived') ORDER BY created_at DESC LIMIT 15",
                         site["id"], include_archived)
    out = []
    for r in rows:
        k = r.pop("kpis") or {}
        out.append({**ctx.clean(r), "id": str(r["id"]), "on_time": f"{k.get('on_time')} of {k.get('demand_lines')}",
                    "batches": k.get("batches"), "warnings": len(k.get("warnings") or [])})
    ctx.used.append({"kind": "plans", "label": site["code"]})
    return {"site": site["code"], "plans": out}


def _warning_text(w: dict) -> str:
    kind = w.get("kind")
    bits = {k: v for k, v in w.items() if k not in ("kind", "key", "batch_key")}
    return f"{kind}: " + ", ".join(f"{k}={v}" for k, v in bits.items())


def get_plan(ctx: Ctx, plan_id: str | None = None) -> dict:
    p = _plan(ctx, plan_id)
    k = p["kpis"] or {}
    late = ctx.call.tx.q(
        "SELECT i.code, m.code AS market, d.due_date, d.quantity, d.available_at, d.late_hours, d.on_time,"
        " array_to_string(d.batches, ', ') AS batches FROM plan_demand d JOIN items i ON i.id = d.item_id"
        " JOIN markets m ON m.id = d.market_id WHERE d.plan_id = %s AND NOT d.on_time ORDER BY d.due_date LIMIT 20", p["id"])
    util = sorted(k.get("utilization") or [], key=lambda u: -(u.get("utilization") or 0))[:6]
    return {
        "plan": {**ctx.clean(p, ("name", "status", "objective", "horizon_start", "horizon_end", "created_at", "released_at")),
                 "id": str(p["id"]), "options": p["options"]},
        "kpis": {key: k.get(key) for key in ("demand_lines", "on_time", "late", "unfilled", "batches", "scheduled", "unscheduled",
                                             "changeover_hours", "changeovers", "campaign_breaks", "finish", "value", "cost", "rounded")},
        "late_or_unfilled_deliveries": [ctx.clean(r) for r in late],
        "busiest_machines": [{"code": u["code"], "utilization_pct": round((u.get("utilization") or 0) * 100, 1),
                              "busy_hours": round(u["busy_hours"], 1), "changeover_hours": round(u["changeover_hours"], 1)} for u in util],
        "warnings": [_warning_text(w) for w in (k.get("warnings") or [])[:25]],
        "warnings_total": len(k.get("warnings") or []),
    }


def _batch_node(ctx: Ctx, plan_id, batch_id, depth: int, seen: set) -> dict:
    tx = ctx.call.tx
    b = tx.one("SELECT b.id, b.batch_no, i.code, i.type, u.code AS uom, b.quantity, b.need_by, b.start_at, b.end_at, b.available_at,"
               " b.ship_at, b.status, b.problem, b.locked, b.expires_on FROM plan_batches b JOIN items i ON i.id = b.item_id"
               " JOIN uoms u ON u.id = i.stock_uom_id WHERE b.id = %s", batch_id)
    seen.add(str(batch_id))
    node = ctx.clean(b, ("batch_no", "code", "type", "uom", "quantity", "need_by", "start_at", "end_at", "available_at", "ship_at",
                         "status", "problem", "locked", "expires_on"))
    node["steps"] = [ctx.clean(o) for o in tx.q(
        "SELECT o.seq, o.step_name, r.code AS machine, o.changeover_kind, o.changeover_minutes, o.wait_minutes, o.verification,"
        " o.reclean_minutes, o.start_at, o.end_at FROM plan_operations o JOIN resources r ON r.id = o.resource_id"
        " WHERE o.batch_id = %s ORDER BY o.seq", batch_id)]
    if depth > 0:
        node["made_from"] = []
        for l in tx.q("SELECT supplier_id, quantity FROM plan_links WHERE consumer_id = %s", batch_id):
            if str(l["supplier_id"]) not in seen:
                node["made_from"].append(_batch_node(ctx, plan_id, l["supplier_id"], depth - 1, seen))
    return node


def explain_delivery(ctx: Ctx, product_code: str, market: str | None = None, plan_id: str | None = None) -> dict:
    p = _plan(ctx, plan_id)
    tx = ctx.call.tx
    rows = tx.q("SELECT d.id, i.code, m.code AS market, d.month, d.due_date, d.requested, d.quantity, d.before_rounding, d.from_stock,"
                " array_to_string(d.batches, ',') AS batches, d.available_at, d.late_hours, d.on_time"
                " FROM plan_demand d JOIN items i ON i.id = d.item_id JOIN markets m ON m.id = d.market_id"
                " WHERE d.plan_id = %s AND upper(i.code) = upper(%s) AND (%s::text IS NULL OR upper(m.code) = upper(%s))"
                " ORDER BY d.due_date LIMIT 6", p["id"], product_code.strip(), market, market)
    if not rows:
        codes = [r["code"] for r in tx.q("SELECT DISTINCT i.code FROM plan_demand d JOIN items i ON i.id = d.item_id WHERE d.plan_id = %s", p["id"])]
        return {"found": False, "products_in_plan": codes}
    out, chain_codes = [], set()
    for r in rows:
        seen: set = set()
        batches = []
        for no in (r["batches"] or "").split(","):
            if not no:
                continue
            bid = tx.val("SELECT id FROM plan_batches WHERE plan_id = %s AND batch_no = %s", p["id"], no.strip())
            if bid:
                node = _batch_node(ctx, p["id"], bid, 3, seen)
                batches.append(node)
        def walk(n):
            chain_codes.add(n["code"])
            for c in n.get("made_from", []):
                walk(c)
        for n in batches:
            walk(n)
        out.append({**ctx.clean({k: v for k, v in r.items() if k not in ("id", "batches")}), "batches": batches})
    warnings = [_warning_text(w) for w in (p["kpis"] or {}).get("warnings", [])
                if w.get("code") in chain_codes or w.get("batch") in chain_codes or w.get("consumer") in chain_codes][:20]
    return {"plan": p["name"], "deliveries": out, "related_warnings": warnings,
            "note": "available_at is when the goods can ship; late_hours > 0 means after the due date (end of the due day)."}


def get_batch(ctx: Ctx, batch_no: str, plan_id: str | None = None) -> dict:
    p = _plan(ctx, plan_id)
    bid = ctx.call.tx.val("SELECT id FROM plan_batches WHERE plan_id = %s AND upper(batch_no) = upper(%s)", p["id"], batch_no.strip())
    if not bid:
        return {"found": False}
    node = _batch_node(ctx, p["id"], bid, 2, set())
    node["serves"] = [ctx.clean(r) for r in ctx.call.tx.q(
        "SELECT m.code AS market, d.due_date, d.quantity, d.on_time FROM plan_demand d JOIN markets m ON m.id = d.market_id"
        " WHERE d.plan_id = %s AND %s = ANY(d.batches)", p["id"], node["batch_no"])]
    node["feeds"] = [r["batch_no"] for r in ctx.call.tx.q(
        "SELECT b.batch_no FROM plan_links l JOIN plan_batches b ON b.id = l.consumer_id WHERE l.supplier_id = %s", bid)]
    return node


def get_requirements(ctx: Ctx, start: str | None = None, end: str | None = None, include_quarantine: bool = False) -> dict:
    site = ctx.need_site()
    require_plan(ctx.call, site["id"])
    today = ctx.call.tx.val("SELECT (now() AT TIME ZONE %s)::date", site.get("timezone") or "UTC")
    try:
        s = dt.date.fromisoformat(start) if start else today
        e = dt.date.fromisoformat(end) if end else s + dt.timedelta(days=29)
    except ValueError:
        raise ApiError(422, "invalid", "Dates must be YYYY-MM-DD.")
    if (e - s).days > 370 or e < s:
        raise ApiError(422, "invalid", "Choose a period of up to one year.")
    feats = effective_features(ctx.call.tx.val("SELECT features FROM tenants WHERE id = %s", ctx.call.tenant_id))
    r = net_requirements(ctx.call.tx, str(site["id"]), s, e, feats, include_quarantine, today)
    ctx.used.append({"kind": "requirements", "label": f"{s} – {e}"})
    produced = [ctx.clean(x, ("code", "type", "uom", "demand", "dependent", "usable", "net", "batches", "planned", "no_bom",
                              "short_dated", "expired")) for x in r["produced"]]
    mats = [ctx.clean(x, ("code", "type", "uom", "required", "released", "quarantine", "shortage", "order_qty", "moq",
                          "earliest_arrival", "late", "below_safety", "potency"))
            for x in r["materials"] if x["shortage"] > 0 or x["below_safety"]]
    return {"horizon": f"{s} to {e}", "batches_total": r["totals"]["batches"], "produced": produced,
            "materials_short_or_below_safety": mats[:40], "over_sales_limit": [ctx.clean(o) for o in r["over_limit"]][:10],
            "sales_plan_switched_on": r["options"].get("sales_plan", True)}


def find_items(ctx: Ctx, query: str) -> dict:
    tx = ctx.call.tx
    q = f"%{query.strip()}%"
    rows = tx.q("SELECT i.id, i.code, i.name_en, i.type, u.code AS uom, i.active, i.lead_time_days, i.qc_release_days, i.safety_stock,"
                " i.moq, i.shelf_life_months, i.cleaning_group, i.release_lead_days, i.hold_min_hours, i.hold_max_hours,"
                " i.units_per_shipper, i.standard_cost, i.assay_basis"
                " FROM items i JOIN uoms u ON u.id = i.stock_uom_id WHERE i.code ILIKE %s OR i.name_en ILIKE %s OR i.name_ar ILIKE %s"
                " ORDER BY i.active DESC, i.code LIMIT 8", q, q, q)
    out = []
    for r in rows:
        iid = r.pop("id")
        item = ctx.clean(r)
        bom = tx.one("SELECT b.version, b.batch_size, u.code AS uom, b.yield_pct, b.batch_mode, b.valid_from FROM boms b"
                     " JOIN uoms u ON u.id = b.batch_uom_id WHERE b.item_id = %s AND b.status = 'active'", iid)
        if r["type"] in ("wip", "semi_finished", "finished"):
            item["active_bom"] = ctx.clean(bom) if bom else None
            if ctx.site:
                item["routing_steps_here"] = [ctx.clean(s) for s in tx.q(
                    "SELECT s.seq, s.name, s.uninterrupted, string_agg(r.code, ', ' ORDER BY sr.preferred DESC, r.code) AS machines"
                    " FROM routings rt JOIN routing_steps s ON s.routing_id = rt.id"
                    " LEFT JOIN routing_step_resources sr ON sr.step_id = s.id LEFT JOIN resources r ON r.id = sr.resource_id"
                    " WHERE rt.item_id = %s AND rt.site_id = %s GROUP BY s.seq, s.name, s.uninterrupted ORDER BY s.seq", iid, ctx.site["id"])]
        if r["type"] == "finished":
            item["markets"] = [ctx.clean(m) for m in tx.q(
                "SELECT m.code, im.max_sellable_per_month, im.min_remaining_shelf_pct FROM item_markets im"
                " JOIN markets m ON m.id = im.market_id WHERE im.item_id = %s AND im.active", iid)]
        out.append(item)
    ctx.used.append({"kind": "items", "label": query})
    return {"items": out} if out else {"items": [], "note": "No item matches."}


def get_stock(ctx: Ctx, item_code: str) -> dict:
    site = ctx.need_site()
    require_plan(ctx.call, site["id"])
    rows = ctx.call.tx.q("SELECT s.lot_no, s.status, s.quantity, u.code AS uom, s.manufactured_on, s.expires_on, s.assay_pct, s.lod_pct"
                         " FROM stock_lots s JOIN items i ON i.id = s.item_id JOIN uoms u ON u.id = i.stock_uom_id"
                         " WHERE s.site_id = %s AND upper(i.code) = upper(%s) ORDER BY s.expires_on NULLS LAST", site["id"], item_code.strip())
    ctx.used.append({"kind": "stock", "label": item_code})
    as_of = ctx.call.tx.val("SELECT stock_as_of FROM sites WHERE id = %s", site["id"])
    return {"stock_counted_on": ctx.t(as_of), "lots": [ctx.clean(r) for r in rows]}


def check_setup(ctx: Ctx) -> dict:
    tx = ctx.call.tx
    from ..routers.guide import progress as setup_progress
    sid = str(ctx.site["id"]) if ctx.site else None
    progress = setup_progress(ctx.call, sid)
    issues = []
    for r in tx.q("SELECT i.code, b.version, b.yield_pct FROM boms b JOIN items i ON i.id = b.item_id"
                  " WHERE b.status = 'active' AND (b.yield_pct < 50 OR b.yield_pct > 100)"):
        issues.append(f"{r['code']} BOM v{r['version']}: expected yield {float(r['yield_pct'])} % looks unusual")
    for r in tx.q("SELECT code FROM items WHERE active AND type IN ('wip','semi_finished','finished') AND cleaning_group IS NULL LIMIT 10"):
        issues.append(f"{r['code']}: no cleaning group")
    for r in tx.q("SELECT code FROM items i WHERE active AND type IN ('wip','semi_finished','finished')"
                  " AND NOT EXISTS (SELECT 1 FROM boms b WHERE b.item_id = i.id AND b.status = 'active') LIMIT 10"):
        issues.append(f"{r['code']}: no active bill of materials")
    for r in tx.q("SELECT code FROM items WHERE active AND type IN ('raw_material','packaging') AND lead_time_days IS NULL"
                  " AND NOT not_stock_controlled LIMIT 10"):
        issues.append(f"{r['code']}: no purchase lead time (shortages cannot be dated)")
    for r in tx.q("SELECT i.code FROM items i WHERE i.active AND i.type = 'finished'"
                  " AND NOT EXISTS (SELECT 1 FROM prices p WHERE p.item_id = i.id) LIMIT 10"):
        issues.append(f"{r['code']}: no price in any market")
    if sid:
        for r in tx.q("SELECT i.code, s.name FROM routings rt JOIN routing_steps s ON s.routing_id = rt.id JOIN items i ON i.id = rt.item_id"
                      " WHERE rt.site_id = %s AND NOT EXISTS (SELECT 1 FROM routing_step_resources sr WHERE sr.step_id = s.id) LIMIT 10", sid):
            issues.append(f"{r['code']} step '{r['name']}': no machine qualified")
        for r in tx.q("SELECT code, efficiency_pct FROM resources WHERE site_id = %s AND active AND efficiency_pct < 50", sid):
            issues.append(f"machine {r['code']}: efficiency {float(r['efficiency_pct'])} % looks low")
        n = tx.val("SELECT count(*) FROM stock_lots WHERE site_id = %s AND status <> 'rejected' AND expires_on < current_date", sid)
        if n:
            issues.append(f"{n} stock lots are past their expiry date")
    ctx.used.append({"kind": "setup", "label": "setup check"})
    return {"checklist": [{"step": s["key"], "done": s["done"], "have": s["have"], "total": s["total"]} for s in progress["steps"]],
            "possible_issues": issues[:40]}


def _s(desc: str, props: dict | None = None, required: list | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or []}


TOOLS = {
    "search_help": (search_help, "Search the Complanning User Manual: how to do something in the app, what a field, switch or "
                                 "option means and how it affects plans.", _s("", {"query": {"type": "string"}}, ["query"])),
    "list_plans": (list_plans, "List recent production plans of the current site with their status and on-time figures.",
                   _s("", {"include_archived": {"type": "boolean"}})),
    "get_plan": (get_plan, "Summary of one plan: KPIs, late or unfilled deliveries, busiest machines and warnings. "
                           "Omit plan_id for the plan the user is looking at.", _s("", {"plan_id": {"type": "string"}})),
    "explain_delivery": (explain_delivery, "Why a delivery is on time, late or unfilled: its batches with every step, machine, "
                                           "changeover and time, the batches they are made from, and related warnings.",
                         _s("", {"product_code": {"type": "string"}, "market": {"type": "string"}, "plan_id": {"type": "string"}},
                            ["product_code"])),
    "get_batch": (get_batch, "Details of one planned batch by number (for example B014): steps, machines, times, what it is made "
                             "from, what it feeds and which deliveries it serves.",
                  _s("", {"batch_no": {"type": "string"}, "plan_id": {"type": "string"}}, ["batch_no"])),
    "get_requirements": (get_requirements, "Net requirements for the current site: batches needed per item after stock, and "
                                           "materials short or below safety stock with suggested orders and earliest arrival. "
                                           "Dates are YYYY-MM-DD; default the next 30 days.",
                         _s("", {"start": {"type": "string"}, "end": {"type": "string"}, "include_quarantine": {"type": "boolean"}})),
    "find_items": (find_items, "Find items by code or name and show their planning data: type, unit, lead times, shelf life, "
                               "active bill of materials, routing steps and machines at this site, markets and sales limits.",
                   _s("", {"query": {"type": "string"}}, ["query"])),
    "get_stock": (get_stock, "Stock lots of one item at the current site: lot, status, quantity, dates, assay and LOD.",
                  _s("", {"item_code": {"type": "string"}}, ["item_code"])),
    "check_setup": (check_setup, "Check the company's setup: which getting-started steps are done and possible data problems "
                                 "(missing BOMs, cleaning groups, lead times, prices, unqualified routing steps, unusual values).",
                    _s("")),
}


def specs() -> list[dict]:
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": p}} for n, (_f, d, p) in TOOLS.items()]


def run(ctx: Ctx, name: str, args: dict) -> dict:
    """Run one tool inside a savepoint, so a failing tool never spoils the rest of the request."""
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"Unknown tool {name}."}
    tx = ctx.call.tx
    tx.x("SAVEPOINT assistant_tool")
    try:
        out = fn[0](ctx, **{k: v for k, v in (args or {}).items() if v is not None})
        tx.x("RELEASE SAVEPOINT assistant_tool")
        return out
    except ApiError as e:
        tx.x("ROLLBACK TO SAVEPOINT assistant_tool")
        return {"error": e.message}
    except TypeError as e:
        tx.x("ROLLBACK TO SAVEPOINT assistant_tool")
        return {"error": f"Bad arguments for {name}: {e}"}
    except psycopg.Error:
        tx.x("ROLLBACK TO SAVEPOINT assistant_tool")
        return {"error": "That lookup failed. Check the codes or ids given."}
