"""Getting-started checklist: which setup and planning steps are done, judged from the data itself."""
from __future__ import annotations

from ..api import Call, endpoint
from ..defaults import effective_features
from ..perms import require_site


def _step(key: str, done: bool, to: str, have: int | None = None, total: int | None = None) -> dict:
    return {"key": key, "done": bool(done), "to": to, "have": have, "total": total}


@endpoint(auth="tenant_user")
def setup_progress(call: Call):
    """Twelve steps, in the order of the Getting Started Tutorial. Company-wide steps are checked for the whole
    company; site steps for the site in ?site_id= (or reported as not done when there is no site yet)."""
    tx = call.tx
    sid = call.query.get("site_id") or None
    if sid:
        require_site(call, sid)
    feats = effective_features(tx.val("SELECT features FROM tenants WHERE id = %s", call.tenant_id))
    sites = tx.val("SELECT count(*) FROM sites WHERE active")
    markets = tx.val("SELECT count(*) FROM markets WHERE active")
    sold = tx.val("SELECT count(DISTINCT im.item_id) FROM item_markets im JOIN items i ON i.id = im.item_id"
                  " WHERE im.active AND i.active AND i.type = 'finished'")
    produced = tx.val("SELECT count(*) FROM items WHERE active AND type IN ('wip', 'semi_finished', 'finished')")
    with_bom = tx.val("SELECT count(*) FROM items i WHERE i.active AND i.type IN ('wip', 'semi_finished', 'finished')"
                      " AND EXISTS (SELECT 1 FROM boms b WHERE b.item_id = i.id AND b.status = 'active')")
    steps = [
        _step("company", sites > 0, "/settings", sites),
        _step("markets", markets > 0, "/master/units", markets),
        _step("items", sold > 0, "/master/items", sold),
        _step("boms", produced > 0 and with_bom == produced, "/master/boms", with_bom, produced),
    ]
    if sid:
        machines = tx.val("SELECT count(*) FROM resources WHERE site_id = %s::uuid AND active", sid)
        routed = tx.val(
            "SELECT count(*) FROM items i WHERE i.active AND i.type IN ('wip', 'semi_finished', 'finished')"
            " AND EXISTS (SELECT 1 FROM routings r JOIN routing_steps s ON s.routing_id = r.id"
            "             WHERE r.item_id = i.id AND r.site_id = %s::uuid)"
            " AND NOT EXISTS (SELECT 1 FROM routings r JOIN routing_steps s ON s.routing_id = r.id"
            "                 WHERE r.item_id = i.id AND r.site_id = %s::uuid"
            "                   AND NOT EXISTS (SELECT 1 FROM routing_step_resources sr WHERE sr.step_id = s.id))", sid, sid)
        shifts = tx.val("SELECT count(*) FROM shifts WHERE site_id = %s::uuid AND period_id IS NULL", sid)
        co_rules = tx.val("SELECT count(*) FROM changeover_rules WHERE site_id = %s::uuid", sid)
        no_group = tx.val("SELECT count(*) FROM items WHERE active AND type IN ('wip', 'semi_finished', 'finished')"
                          " AND cleaning_group IS NULL")
        demand = tx.val("SELECT count(*) FROM demand_lines WHERE site_id = %s::uuid AND quantity > 0"
                        " AND month >= date_trunc('month', current_date)", sid)
        stock_date = tx.val("SELECT stock_as_of FROM sites WHERE id = %s::uuid", sid)
        missing_bom = tx.val(
            "SELECT count(DISTINCT d.item_id) FROM demand_lines d WHERE d.site_id = %s::uuid AND d.quantity > 0"
            " AND d.month >= date_trunc('month', current_date)"
            " AND NOT EXISTS (SELECT 1 FROM boms b WHERE b.item_id = d.item_id AND b.status = 'active')", sid)
        plans = tx.val("SELECT count(*) FROM plans WHERE site_id = %s::uuid", sid)
        released = tx.val("SELECT count(*) FROM plans WHERE site_id = %s::uuid AND status = 'released'", sid)
        has_demand = demand > 0 or not feats.get("sales_plan", True)
        steps += [
            _step("routings", machines > 0 and produced > 0 and routed == produced, "/master/routings", routed, produced),
            _step("calendar", shifts > 0, "/master/calendar", shifts),
            _step("rules", co_rules > 0 and no_group == 0, "/rules/changeovers", co_rules),
            _step("sales", has_demand, "/planning/sales", demand),
            _step("stock", stock_date is not None, "/planning/stock"),
            _step("requirements", has_demand and missing_bom == 0 and with_bom == produced and produced > 0,
                  "/planning/requirements", None),
            _step("plan", plans > 0, "/plans", plans),
            _step("release", released > 0, "/plans", released),
        ]
    else:
        for key, to in (("routings", "/master/routings"), ("calendar", "/master/calendar"), ("rules", "/rules/changeovers"),
                        ("sales", "/planning/sales"), ("stock", "/planning/stock"), ("requirements", "/planning/requirements"),
                        ("plan", "/plans"), ("release", "/plans")):
            steps.append(_step(key, False, to))
    done = sum(1 for s in steps if s["done"])
    return {"steps": steps, "done": done, "total": len(steps), "complete": done == len(steps), "site_id": sid}
