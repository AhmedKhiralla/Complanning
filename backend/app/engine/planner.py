"""Complanning planning engine.

1. Demand: sales plan lines due in the horizon, capped at each market's monthly sales limit.
2. Batches: netted against stock by due date and level by level through the active bills of materials
   (finished, semi-finished, work in process). Every batch knows which demand or batch it supplies (pegging).
3. Schedule: a finite-capacity list scheduler places operations on machines in time. It respects routings
   and alternative machines, working calendars and planned downtime, changeovers with cleaning
   verification, campaign limits, clean equipment hold times, material availability, product holding
   times and QC release (or release at risk). Among operations competing for the same machine it picks
   by the chosen objective: on-time delivery, sales value or utilisation.
4. Several schedules are built with different tie-breaking, and the best one for the objective is kept.

All times inside the engine are naive UTC datetimes.
"""
from __future__ import annotations

import datetime as dt
import itertools
import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..netting import add_months, line_needs, load_demand, lot_expiry, month_end, potency_factors, price_on, shelf_ok
from ..routers.rules import Resolver
from ..units import UnitBook
from .calendar import WorkCalendar, site_calendar, to_naive_utc

PRODUCED = ("wip", "semi_finished", "finished")
USE_STOCK = {"finished": "use_stock_fg", "semi_finished": "use_stock_semi", "wip": "use_stock_wip"}
EPS = 1e-6
H = dt.timedelta(hours=1)
ENGINE_VERSION = "complanning-1.3"

# Weights per objective: due date (per hour), changeover (per hour), value density.
WEIGHTS = {
    "on_time": dict(due=1.0, co=0.6, val=0.0),
    "sales_value": dict(due=0.15, co=0.4, val=1.0),
    "utilization": dict(due=0.12, co=4.0, val=0.0),
}


# ------------------------------------------------------------------ model
@dataclass
class Option:
    machine: "Machine"
    minutes: float               # setup + run, in working minutes, after machine efficiency


@dataclass
class Step:
    seq: int
    name: str
    options: list[Option]
    uninterrupted: bool = False
    partners: list["Step"] = field(default_factory=list)   # steps that run together with this one, on their own machines

    @property
    def members(self) -> list["Step"]:
        return [self] + self.partners

    @property
    def min_minutes(self) -> float:
        """Shortest time for the step (with the steps that run together with it, the slowest of them)."""
        return max(min(o.minutes for o in st.options) for st in self.members)


@dataclass
class Batch:
    key: int
    item_id: str
    code: str
    type: str
    level: int
    qty: float
    expected: float
    bom_version: int | None
    need_by: dt.datetime
    uom: str
    steps: list[Step] = field(default_factory=list)
    suppliers: list[tuple["Batch", float]] = field(default_factory=list)
    consumers: list[tuple[object, float]] = field(default_factory=list)
    materials: list[tuple[str, float]] = field(default_factory=list)
    stock_ready: dt.datetime | None = None     # stock of components used, when it becomes usable
    not_before: dt.datetime | None = None      # do not start earlier: the batch it feeds waits for materials
    value: float = 0.0
    currency: str | None = None
    problem: str | None = None                 # no_bom, no_routing, no_machine
    ordinal: int = 0                           # nth batch of this item in the plan; locks refer to it
    lock: dict | None = None                   # {"start": datetime, "machines": {seq: resource_id}}
    material_cost: float | None = None         # bought materials at standard cost (costs switched on)
    campaign_group: tuple | None = None        # batches that a minimum campaign keeps together


@dataclass
class DemandRow:
    line_id: str
    item_id: str
    code: str
    market_id: str
    market: str
    month: dt.date
    due_at: dt.datetime
    due_date: dt.date
    requested: float
    quantity: float              # after the sales limit
    price: float | None
    currency: str | None
    from_stock: float = 0.0
    stock_ready: dt.datetime | None = None
    min_shelf: float | None = None             # the market's minimum remaining shelf life, % of total
    before_rounding: float | None = None       # quantity before rounding to full shippers
    sources: list[tuple[Batch, float]] = field(default_factory=list)


@dataclass
class Machine:
    id: str
    code: str
    cal: WorkCalendar
    efficiency: float
    clean_hold_h: float | None


@dataclass
class Plan:
    """Everything the scheduler needs; built once per run."""
    start: dt.datetime
    horizon_end: dt.datetime
    objective: str
    batches: list[Batch]
    demand: list[DemandRow]
    machines: dict[str, Machine]
    resolver: Resolver
    items: dict[str, dict]
    campaigns: dict[tuple[str, str | None], dict]
    rules: dict
    pools: dict[str, dict]             # material stock: released, quarantine, quarantine_ready, arrival, unlimited
    warnings: list[dict]
    options: dict
    cost_currency: str | None = None           # set when costs are switched on


# ------------------------------------------------------------------ loading and batching
def _release_delay(item: dict, at_risk: bool, rules: dict) -> dt.timedelta:
    """Time after a batch ends before the next stage may use it."""
    hold_min = float(item["hold_min_hours"] or 0) if rules["holding_times"] else 0.0
    qc = float(item["release_lead_days"] or 0) if rules["qc_lead_times"] else 0.0
    if at_risk and item["release_at_risk_allowed"] and rules["release_at_risk"]:
        qc = 0.0
    return dt.timedelta(hours=hold_min) + dt.timedelta(days=qc)


def build_plan(tx, site: dict, horizon_start: dt.date, horizon_end: dt.date, objective: str, options: dict,
               features: dict, now: dt.datetime, plan_date: dt.date, locks: list[dict] | None = None) -> Plan:
    tz = ZoneInfo(site["timezone"] or "UTC")
    warnings: list[dict] = []
    rules = {
        "holding_times": features.get("holding_times", True), "qc_lead_times": features.get("qc_lead_times", True),
        "release_at_risk": features.get("release_at_risk", True) and options.get("release_at_risk", False),
        "campaign_limits": features.get("campaign_limits", True), "equipment_holds": features.get("equipment_hold_times", True),
        "verification": features.get("cleaning_verification", True),
        "costs": bool(features.get("costs", False)),
    }
    start_local = dt.datetime.combine(horizon_start, dt.time(0), tz)
    start = max(to_naive_utc(start_local), now.replace(second=0, microsecond=0))
    end_local = dt.datetime.combine(horizon_end + dt.timedelta(days=1), dt.time(0), tz)
    h_end = to_naive_utc(end_local)

    book = UnitBook(tx)
    items = {str(r["id"]): r for r in tx.q(
        "SELECT i.id, i.code, i.type, i.stock_uom_id, u.code AS uom, i.safety_stock, i.lead_time_days, i.qc_release_days,"
        " i.release_lead_days, i.not_stock_controlled, i.hold_min_hours, i.hold_max_hours, i.release_at_risk_allowed,"
        " i.test_before_sale, i.standard_cost, i.shelf_life_months, i.units_per_shipper, i.pack_size"
        " FROM items i JOIN uoms u ON u.id = i.stock_uom_id")}
    boms = {str(b["item_id"]): b for b in tx.q("SELECT * FROM boms WHERE status = 'active'")}
    lines = defaultdict(list)
    for l in tx.q("SELECT l.* FROM bom_lines l JOIN boms b ON b.id = l.bom_id WHERE b.status = 'active' ORDER BY l.line_no"):
        lines[str(l["bom_id"])].append(l)

    # Machines and their calendars (horizon plus room for late work).
    cal_last = horizon_end + dt.timedelta(days=150)
    base_cal, has_shifts = site_calendar(tx, site["id"], site["timezone"], horizon_start, cal_last)
    if not has_shifts:
        warnings.append({"kind": "no_shifts"})
    down = defaultdict(list)
    for e in tx.q("SELECT resource_id, starts_at, ends_at FROM resource_exceptions WHERE site_id = %s::uuid AND ends_at > %s",
                  site["id"], start):
        down[str(e["resource_id"])].append((to_naive_utc(e["starts_at"]), to_naive_utc(e["ends_at"])))
    machines: dict[str, Machine] = {}
    for r in tx.q("SELECT id, code, efficiency_pct, clean_hold_hours FROM resources WHERE site_id = %s::uuid AND active", site["id"]):
        rid = str(r["id"])
        machines[rid] = Machine(rid, r["code"], base_cal.minus(down.get(rid, [])), float(r["efficiency_pct"] or 100) / 100,
                                float(r["clean_hold_hours"]) if r["clean_hold_hours"] and rules["equipment_holds"] else None)

    longest = {mid: m.cal.longest() for mid, m in machines.items()}

    # Routings: steps with qualified machines.
    routing = defaultdict(list)
    for s in tx.q("SELECT rt.item_id, s.id, s.seq, s.name, s.time_model, s.fixed_minutes, s.rate_per_hour, s.setup_minutes, s.uninterrupted,"
                  " s.with_previous FROM routings rt JOIN routing_steps s ON s.routing_id = rt.id WHERE rt.site_id = %s::uuid ORDER BY s.seq", site["id"]):
        routing[str(s["item_id"])].append(s)
    step_res = defaultdict(list)
    for sr in tx.q("SELECT sr.step_id, sr.resource_id, sr.preferred, sr.fixed_minutes, sr.rate_per_hour FROM routing_step_resources sr"
                   " JOIN routing_steps s ON s.id = sr.step_id JOIN routings rt ON rt.id = s.routing_id WHERE rt.site_id = %s::uuid"
                   " ORDER BY sr.preferred DESC", site["id"]):
        step_res[str(sr["step_id"])].append(sr)

    def steps_for(item_id: str, qty: float) -> tuple[list[Step], str | None]:
        if item_id not in routing:
            return [], "no_routing"
        out = []
        for s in routing[item_id]:
            opts = []
            for sr in step_res[str(s["id"])]:
                m = machines.get(str(sr["resource_id"]))
                if not m:
                    continue
                if s["time_model"] == "fixed":
                    run = float(sr["fixed_minutes"] or s["fixed_minutes"])
                else:
                    rate = float(sr["rate_per_hour"] or s["rate_per_hour"])
                    run = qty / rate * 60
                opts.append(Option(m, float(s["setup_minutes"] or 0) + run / max(m.efficiency, 0.05)))
            if not opts:
                return [], "no_machine"
            if s["uninterrupted"]:
                # Only machines whose working blocks are long enough for the whole step.
                opts = [o for o in opts if o.minutes <= longest[o.machine.id]]
                if not opts:
                    return [], "no_window"
            step = Step(s["seq"], s["name"], opts, bool(s["uninterrupted"]))
            if s["with_previous"] and out:
                # Runs together with the previous step: one booking over both machines, without a pause if either needs it.
                lead = out[-1]
                lead.partners.append(step)
                flag = any(x.uninterrupted for x in lead.members)
                for x in lead.members:
                    x.uninterrupted = flag
            else:
                out.append(step)
        return out, None

    # Low-level codes.
    llc = {iid: 0 for iid in items}
    for _ in range(12):
        changed = False
        for parent, bom in boms.items():
            for l in lines[str(bom["id"])]:
                c = str(l["component_item_id"])
                if llc.get(c, 0) < llc.get(parent, 0) + 1:
                    llc[c] = llc[parent] + 1
                    changed = True
        if not changed:
            break

    # Stock. Materials are pooled; produced items are kept by lot, first expiry first out, so shelf life can be checked.
    stock = defaultdict(lambda: {"released": 0.0, "quarantine": 0.0})
    lots: dict[str, list[dict]] = defaultdict(list)
    for s in tx.q("SELECT item_id, status, quantity, manufactured_on, expires_on FROM stock_lots WHERE site_id = %s::uuid"
                  " AND status <> 'rejected' AND quantity > 0", site["id"]):
        iid = str(s["item_id"])
        it = items.get(iid)
        if not it:
            continue
        exp = lot_expiry(s, it["shelf_life_months"])
        if exp and exp < horizon_start:
            continue
        stock[iid][s["status"]] += float(s["quantity"])
        if it["type"] in PRODUCED:
            lots[iid].append({"status": s["status"], "qty": float(s["quantity"]), "exp": exp, "made": s["manufactured_on"]})
    for ls in lots.values():
        ls.sort(key=lambda x: (x["status"] != "released", x["exp"] or dt.date.max))
    use_q = bool(options.get("include_quarantine"))
    factors = potency_factors(tx, site["id"], use_q, horizon_start, bool(features.get("assay_compensation", True)))
    cost_currency = tx.val("SELECT cost_currency FROM tenants LIMIT 1") if rules["costs"] else None

    def q_ready(it: dict) -> dt.datetime:
        days = float((it["qc_release_days"] if it["type"] not in PRODUCED else it["release_lead_days"]) or 0)
        return start + dt.timedelta(days=days if rules["qc_lead_times"] else 0)

    # Demand due in the horizon (the sales plan, or the sales limits when the sales plan is switched off),
    # capped at the sales limit and rounded to full shippers.
    demand: list[DemandRow] = []
    shippers = options.get("full_shippers", True)
    for d in load_demand(tx, site["id"], horizon_start, horizon_end, features):
        it = items[str(d["item_id"])]
        due_date = d["due_date"] or month_end(d["month"])
        due_at = to_naive_utc(dt.datetime.combine(due_date + dt.timedelta(days=1), dt.time(0), tz))
        qty = float(d["quantity"])
        limit = float(d["max_qty"]) if d["max_qty"] is not None and options.get("cap_to_limit", True) else None
        capped = min(qty, limit) if limit is not None else qty
        before = None
        ups = float(it["units_per_shipper"] or 0)
        if shippers and ups > 0 and capped > EPS:
            r = math.ceil(capped / ups - 1e-9) * ups
            if limit is not None and r > limit + EPS:
                r = math.floor(limit / ups + 1e-9) * ups
            if abs(r - capped) > EPS:
                before, capped = capped, r
        p = price_on(tx, d["item_id"], d["market_id"], plan_date)
        demand.append(DemandRow(str(d["id"]) if d["id"] else None, str(d["item_id"]), it["code"], str(d["market_id"]), d["market"],
                                d["month"], due_at, due_date, qty, capped, float(p["price"]) if p else None, p["currency"] if p else None,
                                min_shelf=float(d["min_shelf"]) if d["min_shelf"] else None, before_rounding=before))

    # Requirements per item: (need_by, qty, consumer). Consumers are DemandRow or Batch.
    reqs: dict[str, list] = defaultdict(list)
    for d in demand:
        if d.quantity > EPS:
            reqs[d.item_id].append([d.due_at, d.quantity, d])

    batches: list[Batch] = []
    order = sorted(items, key=lambda i: (llc.get(i, 0), items[i]["code"]))
    for iid in order:
        it = items[iid]
        if it["type"] not in PRODUCED:
            continue
        rs = sorted(reqs.get(iid, []), key=lambda r: r[0])
        use = features.get(USE_STOCK[it["type"]], True)
        item_lots = [dict(x) for x in lots.get(iid, [])
                     if use and (x["status"] == "released" or use_q)]
        remaining = []
        short_dated = defaultdict(float)
        for need_by, q, consumer in rs:
            for lot in item_lots:
                if q <= EPS:
                    break
                if lot["qty"] <= EPS:
                    continue
                if isinstance(consumer, DemandRow):
                    if not shelf_ok(lot["exp"], lot["made"], it["shelf_life_months"], None, consumer.due_date):
                        continue
                    if not shelf_ok(lot["exp"], lot["made"], it["shelf_life_months"], consumer.min_shelf, consumer.due_date):
                        short_dated[consumer.market] += min(q, lot["qty"])
                        continue
                elif lot["exp"] and lot["exp"] < need_by.date():
                    continue
                take = min(q, lot["qty"])
                lot["qty"] -= take
                q -= take
                ready = start if lot["status"] == "released" else q_ready(it)
                if isinstance(consumer, DemandRow):
                    consumer.from_stock += take
                consumer.stock_ready = max(consumer.stock_ready or ready, ready)
            if q > EPS:
                remaining.append([need_by, q, consumer])
        for market, q in short_dated.items():
            warnings.append({"kind": "short_shelf_life", "code": it["code"], "market": market, "quantity": q, "uom": it["uom"]})
        free = sum(x["qty"] for x in item_lots)
        safety = float(it["safety_stock"] or 0)
        if use and safety > 0 and free < safety:
            remaining.append([h_end, safety - free, None])
        if not remaining:
            continue

        bom = boms.get(iid)
        if not bom:
            b = Batch(len(batches), iid, it["code"], it["type"], llc.get(iid, 0), sum(r[1] for r in remaining), 0.0, None,
                      remaining[0][0], it["uom"], problem="no_bom")
            for need_by, q, consumer in remaining:
                _peg(b, consumer, q)
            batches.append(b)
            continue
        nominal = float(book.to_stock(iid, Decimal(bom["batch_size"]), str(bom["batch_uom_id"])))
        expected = nominal * float(bom["yield_pct"]) / 100
        partial = bom["batch_mode"] == "partial"
        min_q = expected * float(bom["min_batch_pct"] or 0) / 100
        made: list[Batch] = []
        cur, room = None, 0.0
        hold = float(it["hold_max_hours"]) if it["hold_max_hours"] and rules["holding_times"] else None
        for need_by, q, consumer in remaining:
            # The rest of a batch only serves needs it can be held for; otherwise a new batch is made.
            if cur is not None and hold and need_by - cur.need_by > dt.timedelta(hours=hold):
                room = 0.0
            while q > EPS:
                if cur is None or room <= EPS:
                    cur = Batch(len(batches), iid, it["code"], it["type"], llc.get(iid, 0), expected, expected, bom["version"],
                                need_by, it["uom"])
                    batches.append(cur)
                    made.append(cur)
                    room = expected
                take = min(q, room)
                _peg(cur, consumer, take)
                room -= take
                q -= take
        if partial:
            for b in made:
                served = sum(q for _c, q in b.consumers)
                if served < expected - EPS:
                    b.qty = max(served, min_q)
        # Components for each batch; produced components become requirements one level down.
        for b in made:
            b.steps, b.problem = steps_for(iid, b.qty)
            lead = sum(s.min_minutes for s in b.steps) / (60 * 16) + 1
            needs, probs = line_needs(book, lines[str(bom["id"])], Decimal(str(b.qty / expected)), features, factors)
            for pr in probs:
                w = {**pr, "item": it["code"]}
                if w not in warnings:
                    warnings.append(w)
            for l, need in needs:
                cid = str(l["component_item_id"])
                need = float(need)
                citem = items[cid]
                if citem["type"] in PRODUCED:
                    need_by = b.need_by - dt.timedelta(days=lead) - _release_delay(citem, bool(options.get("release_at_risk")), rules)
                    reqs[cid].append([need_by, need, b])
                else:
                    b.materials.append((cid, need))
            if rules["costs"]:
                known = [(items[c]["standard_cost"], q) for c, q in b.materials]
                b.material_cost = sum(float(c) * q for c, q in known if c is not None)
    # Values: finished batches carry the value of the demand they serve; components share it.
    for b in batches:
        for consumer, q in b.consumers:
            if isinstance(consumer, DemandRow) and consumer.price:
                unit = consumer.price
                cost = items[b.item_id]["standard_cost"]
                if rules["costs"] and cost is not None and consumer.currency == cost_currency:
                    unit = max(0.0, consumer.price - float(cost))      # sales value objective works on margin
                b.value += unit * q
                b.currency = consumer.currency
    for b in sorted(batches, key=lambda x: x.level):
        for consumer, q in b.consumers:
            if isinstance(consumer, Batch) and consumer.qty > EPS:
                b.value += consumer.value * min(1.0, q / consumer.qty)
                b.currency = b.currency or consumer.currency

    # Material pools for the scheduler.
    pools = {}
    for iid, it in items.items():
        if it["type"] in PRODUCED:
            continue
        lead_days = float(it["lead_time_days"] or 0) + (float(it["qc_release_days"] or 0) if rules["qc_lead_times"] else 0)
        pools[iid] = {"released": stock[iid]["released"], "quarantine": stock[iid]["quarantine"] if use_q else 0.0,
                      "quarantine_ready": q_ready(it), "arrival": start + dt.timedelta(days=lead_days),
                      "has_lead": it["lead_time_days"] is not None, "unlimited": bool(it["not_stock_controlled"]), "code": it["code"]}

    if not options.get("material_constraints", True):
        for pool in pools.values():
            pool["unlimited"] = True

    campaigns = {}
    if rules["campaign_limits"]:
        for c in tx.q("SELECT item_id, resource_id, max_batches, max_days, min_batches FROM campaign_rules WHERE site_id = %s::uuid", site["id"]):
            campaigns[(str(c["item_id"]), str(c["resource_id"]) if c["resource_id"] else None)] = c
        # Minimum campaign: batches of the item are made together in groups of at least that size, so the group
        # starts as early as its first batch would and the engine keeps them on the machine back to back.
        mins: dict[str, int] = {}
        for (iid, _rid), c in campaigns.items():
            if c["min_batches"] and c["min_batches"] > 1:
                mins[iid] = max(mins.get(iid, 0), int(c["min_batches"]))
        for iid, n in mins.items():
            mine = sorted((b for b in batches if b.item_id == iid and b.steps and not b.lock), key=lambda b: b.need_by)
            for i in range(0, len(mine), n):
                group = mine[i:i + n]
                first = min(b.need_by for b in group)
                for b in group:
                    b.need_by = first
                    b.campaign_group = (iid, i // n)
    # Ordinals and locks. A lock fixes a batch's start and machines; what feeds it must be ready in time.
    seen: dict[str, int] = defaultdict(int)
    for b in batches:
        seen[b.item_id] += 1
        b.ordinal = seen[b.item_id]
    by_ord = {(b.item_id, b.ordinal): b for b in batches}
    for lk in locks or []:
        b = by_ord.get((str(lk["item_id"]), int(lk["ordinal"])))
        if not b or not b.steps:
            warnings.append({"kind": "lock_lost", "code": items.get(str(lk["item_id"]), {}).get("code", "?"), "ordinal": lk["ordinal"]})
            continue
        b.lock = {"start": _naive(lk["start"]), "machines": {int(k): str(v) for k, v in (lk.get("machines") or {}).items()}}
        b.need_by = min(b.need_by, b.lock["start"])
    # What feeds a locked batch (or a minimum campaign) gets an earlier deadline when needed, down the chain.
    pushed = {b.key for b in batches if b.lock or b.campaign_group}
    for b in sorted(batches, key=lambda x: x.level):
        if b.key not in pushed:
            continue
        eff = b.lock["start"] if b.lock else b.need_by
        for sup, _q in b.suppliers:
            lead = sum(st.min_minutes for st in sup.steps) / (60 * 16) + 1 if sup.steps else 1
            want = eff - _release_delay(items[sup.item_id], bool(options.get("release_at_risk")), rules) - dt.timedelta(days=lead)
            if want < sup.need_by:
                sup.need_by = want
                pushed.add(sup.key)

    # Just in time below material waits: when a batch must wait for a material delivery, the batches that
    # feed it start no earlier than needed, so intermediates are not made months ahead and held too long.
    sim = {k: dict(v) for k, v in pools.items()}
    gate: dict[int, dt.datetime] = {}
    for b in sorted(batches, key=lambda x: x.need_by):
        t = start
        for iid, need in b.materials:
            pool = sim.get(iid)
            if not pool or pool["unlimited"]:
                continue
            take = min(need, pool["released"])
            pool["released"] -= take
            left = need - take
            if left > EPS and pool["quarantine"] > EPS:
                tq = min(left, pool["quarantine"])
                pool["quarantine"] -= tq
                left -= tq
                t = max(t, pool["quarantine_ready"])
            if left > EPS:
                t = max(t, pool["arrival"])
        gate[b.key] = t
    limits: dict[int, list] = defaultdict(list)
    for b in sorted(batches, key=lambda x: x.level):
        own = gate.get(b.key, start)
        if b.lock:
            own = b.lock["start"]
        if limits.get(b.key):
            b.not_before = max(start, min(limits[b.key]))
            own = max(own, b.not_before)
        for sup, _q in b.suppliers:
            lead = sum(st.min_minutes for st in sup.steps) / (60 * 16) + 1
            nb = own - dt.timedelta(days=lead) - _release_delay(items[sup.item_id], bool(options.get("release_at_risk")), rules)
            limits[sup.key].append(nb)
    # Do not start a batch much earlier than it is needed (stock built months ahead ties up money and shelf life).
    early = options.get("max_early_days", 14)
    if early is not None:
        for b in batches:
            # Only where a chain starts: later stages follow as soon as their inputs are released.
            if not b.steps or b.suppliers or b.lock:
                continue
            lead = sum(st.min_minutes for st in b.steps) / (60 * 16) + 1
            release = b.need_by - dt.timedelta(days=lead + float(early))
            if release > start:
                b.not_before = max(b.not_before or start, release)
    for b in batches:
        if b.not_before is not None and b.not_before <= start:
            b.not_before = None

    for d in demand:
        if d.quantity < d.requested - EPS:
            warnings.append({"kind": "capped", "code": d.code, "market": d.market, "month": d.month.strftime("%Y-%m"),
                             "requested": d.requested, "quantity": d.quantity})
    return Plan(start, h_end, objective, batches, demand, machines, Resolver(tx, site["id"]), items, campaigns, rules, pools,
                warnings, options, cost_currency)


def _naive(v) -> dt.datetime:
    if isinstance(v, str):
        v = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    return to_naive_utc(v)


def _peg(b: Batch, consumer, q: float) -> None:
    b.consumers.append((consumer, q))
    if isinstance(consumer, DemandRow):
        consumer.sources.append((b, q))
    elif isinstance(consumer, Batch):
        consumer.suppliers.append((b, q))


# ------------------------------------------------------------------ scheduling
@dataclass
class OpResult:
    batch: Batch
    step: Step
    machine: Machine
    co_start: dt.datetime | None
    co_end: dt.datetime | None
    co_minutes: float
    co_wait: float
    co_kind: str | None
    co_verification: str | None
    reclean_minutes: float
    start: dt.datetime
    end: dt.datetime
    run_minutes: float
    prev: tuple | None = None          # (item_id, batch key) before this operation on the machine
    locked: bool = False
    partners: list = field(default_factory=list)   # operations on other machines that run together with this one

    @property
    def machine_ids(self) -> set[str]:
        return {self.machine.id} | {p.machine.id for p in self.partners}


class Scheduler:
    def __init__(self, plan: Plan, weights: dict, noise: float = 0.0, seed: int = 0):
        self.p = plan
        self.w = weights
        self.noise = noise
        self.rng = random.Random(seed)
        self.free = {m: plan.start for m in plan.machines}
        self.last = {m: None for m in plan.machines}       # (item_id, batch key)
        self.run_count = {m: 0 for m in plan.machines}
        self.campaign_start: dict[str, dt.datetime | None] = {m: None for m in plan.machines}
        self.ops: list[OpResult] = []
        self.next_step = {b.key: 0 for b in plan.batches}
        self.step_end: dict[int, dt.datetime] = {}
        self.done: dict[int, dict] = {}                     # key -> {start, end, available, ship}
        self.failed: dict[int, str] = {}
        self.pools = {k: dict(v) for k, v in plan.pools.items()}
        self.material_notes: dict[int, list] = defaultdict(list)
        self.hold_warnings: list[dict] = []
        self.campaign_breaks = 0
        self._cache: dict[tuple, tuple] = {}
        self._mver = {m: 0 for m in plan.machines}
        self.locked_blocks: dict[str, list[dict]] = {m: [] for m in plan.machines}
        self.lock_warnings: list[dict] = []
        self.max_value = max([b.value for b in plan.batches] + [1.0])

    # -- helpers
    def _release(self, b: Batch) -> dt.timedelta:
        return _release_delay(self.p.items[b.item_id], bool(self.p.options.get("release_at_risk")), self.p.rules)

    def _materials(self, b: Batch, commit: bool) -> tuple[dt.datetime, list]:
        ready, notes = self.p.start, []
        for iid, need in b.materials:
            pool = self.pools.get(iid)
            if not pool or pool["unlimited"]:
                continue
            left = need
            take = min(left, pool["released"])
            left -= take
            if commit:
                pool["released"] -= take
            if left > EPS and pool["quarantine"] > EPS:
                tq = min(left, pool["quarantine"])
                left -= tq
                ready = max(ready, pool["quarantine_ready"])
                if commit:
                    pool["quarantine"] -= tq
            if left > EPS:
                ready = max(ready, pool["arrival"])
                notes.append({"item_id": iid, "code": pool["code"], "short": left, "arrival": pool["arrival"],
                              "no_lead_time": not pool["has_lead"]})
        return ready, notes

    def _first_ready(self, b: Batch) -> dt.datetime | None:
        t = self.p.start
        for s, _q in b.suppliers:
            if s.key in self.failed:
                return None
            d = self.done.get(s.key)
            if not d:
                return None
            t = max(t, d["available"])
        if b.stock_ready:
            t = max(t, b.stock_ready)
        if b.not_before:
            t = max(t, b.not_before)
        mt, _ = self._materials(b, commit=False)
        return max(t, mt)

    def _changeover(self, m: Machine, b: Batch, at: dt.datetime, prev: tuple | None = None,
                    tracked: bool = True) -> tuple[float, float, str | None, str | None]:
        last = prev
        if last is None or last[1] == b.key:
            return 0.0, 0.0, None, None
        last_item = last[0]
        if last_item == b.item_id and tracked:
            camp = self.p.campaigns.get((b.item_id, m.id)) or self.p.campaigns.get((b.item_id, None))
            if camp:
                too_many = camp["max_batches"] and self.run_count[m.id] >= camp["max_batches"]
                cs = self.campaign_start[m.id]
                too_long = camp["max_days"] and cs and (at - cs).total_seconds() / 86400 >= float(camp["max_days"])
                if too_many or too_long:
                    r = self.p.resolver._pick(m.id, lambda r: r["kind"] == "default") or \
                        self.p.resolver._pick(m.id, lambda r: r["kind"] == "same_group")
                    if r:
                        return self._co_values(r, "campaign_end")
        res = self.p.resolver.resolve(m.id, last_item, b.item_id)
        if not res["rule"]:
            return 0.0, 0.0, None, None
        return self._co_values(res["rule"], res["source"])

    def _co_values(self, r: dict, kind: str) -> tuple[float, float, str, str]:
        work = float(r["cleaning_minutes"]) + float(r["format_minutes"])
        wait = float(r["verification_wait_minutes"]) if self.p.rules["verification"] else 0.0
        return work, wait, kind, r["verification"] if self.p.rules["verification"] else "none"

    def _evaluate_step(self, b: Batch, step: Step, ready: dt.datetime) -> OpResult | None:
        """Best placement of the batch's current step: the machine that finishes it first. A step with steps that run
        together with it is placed on one machine of each at the same time, for as long as the slowest of them needs."""
        if not step.partners:
            best = None
            for opt in step.options:
                r = self._evaluate(b, opt, ready, step)
                if r and (best is None or r.end < best.end):
                    best = r
            return best
        best = None
        for combo in itertools.islice(itertools.product(*(st.options for st in step.members)), 64):
            if len({o.machine.id for o in combo}) < len(combo):
                continue
            r = self._evaluate_group(b, step, combo, ready)
            if r and (best is None or r.end < best.end):
                best = r
        return best

    def _evaluate_group(self, b: Batch, step: Step, combo: tuple, ready: dt.datetime) -> OpResult | None:
        minutes = max(o.minutes for o in combo)
        t = ready
        rs: list[OpResult] = []
        for _ in range(24):
            rs = []
            for st, o in zip(step.members, combo):
                r = self._evaluate(b, Option(o.machine, minutes), t, st)
                if r is None:
                    return None
                rs.append(r)
            latest = max(r.start for r in rs)
            if all(r.start == latest for r in rs):
                break
            t = latest
        start, end = max(r.start for r in rs), max(r.end for r in rs)
        out = []
        for r in rs:
            out.append(OpResult(r.batch, r.step, r.machine, r.co_start, r.co_end, r.co_minutes, r.co_wait, r.co_kind,
                                r.co_verification, r.reclean_minutes, start, end, minutes, r.prev))
        lead = out[0]
        lead.partners = out[1:]
        return lead

    def _evaluate(self, b: Batch, opt: Option, ready: dt.datetime, step: Step) -> OpResult | None:
        """Earliest placement on the machine after its last planned operation, in a gap that also leaves
        room for the changeover into the next locked batch."""
        m = opt.machine
        key = (b.key, m.id, step.seq, round(opt.minutes, 4))
        cached = self._cache.get(key)
        if cached and cached[0] == self._mver[m.id] and cached[1] == ready:
            return cached[2]
        g_start, prev, tracked = self.free[m.id], self.last[m.id], True
        blocks = [x for x in self.locked_blocks[m.id] if x["end"] > g_start]
        i = 0
        res = None
        while True:
            while i < len(blocks) and blocks[i]["start"] <= g_start:
                if blocks[i]["end"] > g_start:
                    g_start, prev, tracked = blocks[i]["end"], (blocks[i]["item"], blocks[i]["key"]), False
                i += 1
            res = self._place(b, opt, ready, m, g_start, prev, tracked, step)
            if res is None:
                break
            nxt = blocks[i] if i < len(blocks) else None
            if nxt is None:
                break
            w2, wait2, _k, _v = self._changeover(m, nxt["batch"], res.end, (b.item_id, b.key), False)
            if res.end + dt.timedelta(minutes=w2 + wait2) <= nxt["start"]:
                break
            g_start, prev, tracked = nxt["end"], (nxt["item"], nxt["key"]), False
            i += 1
        self._cache[key] = (self._mver[m.id], ready, res)
        return res

    def _place(self, b: Batch, opt: Option, ready: dt.datetime, m: Machine, free: dt.datetime, prev: tuple | None,
               tracked: bool, step: Step) -> OpResult | None:
        work, wait, kind, ver = self._changeover(m, b, max(free, ready), prev, tracked)
        co_start = co_end = None
        clean_at = free
        if work > 0 or wait > 0:
            co_start = m.cal.next_work(free)
            if co_start is None:
                return None
            done_work = m.cal.add_work(co_start, work)
            if done_work is None:
                return None
            co_end = done_work + dt.timedelta(minutes=wait)
            clean_at = co_end
        start = m.cal.next_work(max(ready, clean_at))
        if start is None:
            return None
        reclean = 0.0
        if m.clean_hold_h and prev is not None and prev[1] != b.key and \
                (start - clean_at) > dt.timedelta(hours=m.clean_hold_h):
            sp = self.p.resolver._pick(m.id, lambda r: r["kind"] == "same_product")
            reclean = float(sp["cleaning_minutes"]) if sp else 30.0
            s2 = m.cal.add_work(start, reclean)
            if s2 is None:
                return None
            start = m.cal.next_work(s2) or s2
        if step.uninterrupted:
            start = m.cal.fit(start, opt.minutes)
            if start is None:
                return None
            end = start + dt.timedelta(minutes=opt.minutes)
        else:
            end = m.cal.add_work(start, opt.minutes)
        if end is None:
            return None
        return OpResult(b, step, m, co_start, co_end, work, wait, kind, ver, reclean, start, end, opt.minutes, prev)

    def _priority(self, r: OpResult) -> float:
        b = r.batch
        due = b.need_by
        if self.next_step[b.key] == 0 and self.p.rules["holding_times"]:
            # The holding time of what it consumes is a deadline too.
            for s, _q in b.suppliers:
                hmax = self.p.items[s.item_id]["hold_max_hours"]
                d = self.done.get(s.key)
                if hmax and d:
                    due = min(due, d["end"] + dt.timedelta(hours=float(hmax)) - dt.timedelta(minutes=r.run_minutes))
        due_h = (due - self.p.start).total_seconds() / 3600
        co_h = (r.co_minutes + r.co_wait + r.reclean_minutes) / 60
        val = b.value / self.max_value * 400                 # value density on a scale comparable to hours
        score = self.w["due"] * due_h + self.w["co"] * co_h - self.w["val"] * val
        # A minimum campaign that has started on this machine is continued first.
        last = self.last[r.machine.id]
        if last and last[0] == b.item_id and last[1] != b.key and r.co_kind != "campaign_end":
            camp = self.p.campaigns.get((b.item_id, r.machine.id)) or self.p.campaigns.get((b.item_id, None))
            if camp and camp["min_batches"] and self.run_count[r.machine.id] < camp["min_batches"]:
                score -= 100000
        if self.noise:
            score += self.rng.uniform(-self.noise, self.noise)
        return score

    def _commit(self, r: OpResult) -> None:
        b = r.batch
        if self.next_step[b.key] == 0:
            _ready, notes = self._materials(b, commit=True)
            self.material_notes[b.key] = notes
            hold_ok = self.p.rules["holding_times"]
            for s, q in b.suppliers:
                d = self.done[s.key]
                hmax = self.p.items[s.item_id]["hold_max_hours"]
                if hold_ok and hmax and r.start - d["end"] > dt.timedelta(hours=float(hmax)):
                    self.hold_warnings.append({"kind": "hold_exceeded", "code": s.code, "key": s.key, "consumer": b.code,
                                               "hours": (r.start - d["end"]).total_seconds() / 3600, "limit": float(hmax),
                                               "quantity": q, "uom": s.uom})
        for op in [r] + r.partners:
            self._book(op)
        self.next_step[b.key] += 1
        self.step_end[b.key] = r.end
        if self.next_step[b.key] >= len(b.steps):
            first = next(o.start for o in self.ops if o.batch.key == b.key)
            it = self.p.items[b.item_id]
            ship = r.end
            if b.type == "finished" and it["test_before_sale"] and self.p.rules["qc_lead_times"]:
                ship = r.end + dt.timedelta(days=float(it["release_lead_days"] or 0))
            self.done[b.key] = {"start": first, "end": r.end, "available": r.end + self._release(b), "ship": ship}

    def _book(self, r: OpResult) -> None:
        """The machine's side of an operation: campaign counters, when it is free, what ran last."""
        b, m = r.batch, r.machine
        last = r.prev
        if r.co_kind == "campaign_end":
            self.campaign_breaks += 1
        if last and last[0] == b.item_id and r.co_kind != "campaign_end":
            if last[1] != b.key:
                self.run_count[m.id] += 1
        else:
            self.run_count[m.id] = 1
            self.campaign_start[m.id] = r.start
        if r.co_kind == "campaign_end":
            self.campaign_start[m.id] = r.start
        self.free[m.id] = r.end
        self.last[m.id] = (b.item_id, b.key)
        self._mver[m.id] += 1
        self.ops.append(r)

    def _place_locked(self) -> None:
        """Put locked batches exactly where the planner wants them, before anything else."""
        for b in sorted((x for x in self.p.batches if x.lock and not x.problem), key=lambda x: x.lock["start"]):
            t = b.lock["start"]
            placed = []
            ok = True
            for step in b.steps:
                chosen, used = [], set()
                for st in step.members:
                    want = b.lock["machines"].get(st.seq)
                    free_opts = [o for o in st.options if o.machine.id not in used] or st.options
                    opt = next((o for o in free_opts if o.machine.id == want), free_opts[0])
                    used.add(opt.machine.id)
                    chosen.append((st, opt))
                minutes = max(o.minutes for _st, o in chosen)
                s0 = t
                for _ in range(24):
                    starts = []
                    for _st, o in chosen:
                        x = o.machine.cal.next_work(s0)
                        if x is not None and step.uninterrupted:
                            x = o.machine.cal.fit(x, minutes)
                        starts.append(x)
                    if any(x is None for x in starts):
                        s0 = None
                        break
                    if all(x == starts[0] for x in starts):
                        break
                    s0 = max(starts)
                if s0 is None:
                    ok = False
                    break
                ends = [s0 + dt.timedelta(minutes=minutes) if step.uninterrupted else o.machine.cal.add_work(s0, minutes)
                        for _st, o in chosen]
                if any(e is None for e in ends):
                    ok = False
                    break
                e = max(ends)
                for st, o in chosen:
                    placed.append(OpResult(b, st, o.machine, None, None, 0.0, 0.0, None, None, 0.0, s0, e, minutes, None, True))
                t = e
            if not ok:
                self.failed[b.key] = "no_capacity"
                continue
            _r, notes = self._materials(b, commit=True)
            self.material_notes[b.key] = notes
            for o in placed:
                self.ops.append(o)
                self.locked_blocks[o.machine.id].append({"start": o.start, "end": o.end, "item": b.item_id, "key": b.key,
                                                         "batch": b, "op": o})
            for blocks in self.locked_blocks.values():
                blocks.sort(key=lambda x: x["start"])
            self.next_step[b.key] = len(b.steps)
            self.step_end[b.key] = placed[-1].end
            it = self.p.items[b.item_id]
            ship = placed[-1].end
            if b.type == "finished" and it["test_before_sale"] and self.p.rules["qc_lead_times"]:
                ship = ship + dt.timedelta(days=float(it["release_lead_days"] or 0))
            self.done[b.key] = {"start": placed[0].start, "end": placed[-1].end, "available": placed[-1].end + self._release(b), "ship": ship}

    def _finish_locked(self) -> None:
        """Changeovers into locked batches, and checks that they fit and that their inputs are ready."""
        by_m = defaultdict(list)
        for o in self.ops:
            by_m[o.machine.id].append(o)
        for mid, ops in by_m.items():
            ops.sort(key=lambda o: o.start)
            for prev, o in zip([None] + ops[:-1], ops):
                if not o.locked:
                    continue
                if prev is not None:
                    if prev.end > o.start:
                        self.lock_warnings.append({"kind": "lock_overlap", "code": o.batch.code, "key": o.batch.key,
                                                   "machine": o.machine.code, "other": prev.batch.code})
                        continue
                    if prev.batch.key != o.batch.key:
                        w, wait, kind, ver = self._changeover(o.machine, o.batch, o.start, (prev.batch.item_id, prev.batch.key), False)
                        if w or wait:
                            o.co_minutes, o.co_wait, o.co_kind, o.co_verification = w, wait, kind, ver
                            o.co_end = o.start
                            o.co_start = o.start - dt.timedelta(minutes=w + wait)
                            if o.co_start < prev.end:
                                self.lock_warnings.append({"kind": "lock_no_changeover", "code": o.batch.code, "key": o.batch.key,
                                                           "machine": o.machine.code,
                                                           "minutes": (prev.end - o.co_start).total_seconds() / 60})
        for b in self.p.batches:
            if not b.lock or b.key not in self.done:
                continue
            for s, _q in b.suppliers:
                d = self.done.get(s.key)
                if d and d["available"] > self.done[b.key]["start"]:
                    self.lock_warnings.append({"kind": "lock_inputs_late", "code": b.code, "key": b.key, "input": s.code,
                                               "hours": (d["available"] - self.done[b.key]["start"]).total_seconds() / 3600})

    def run(self) -> "Scheduler":
        self._place_locked()
        pending = [b for b in self.p.batches if not (b.lock and b.key in self.done)]
        for b in pending:
            if b.problem:
                self.failed[b.key] = b.problem
        pending = [b for b in pending if b.key not in self.failed]
        while pending:
            cands: list[OpResult] = []
            readies: dict[int, dt.datetime] = {}
            progressed = False
            for b in pending:
                i = self.next_step[b.key]
                ready = self._first_ready(b) if i == 0 else self.step_end[b.key]
                if ready is not None:
                    readies[b.key] = ready
                if ready is None:
                    if any(s.key in self.failed for s, _ in b.suppliers):
                        self.failed[b.key] = "supplier_failed"
                        progressed = True
                    continue
                best = self._evaluate_step(b, b.steps[i], ready)
                if best is None:
                    self.failed[b.key] = "no_capacity"
                    progressed = True
                    continue
                cands.append(best)
            if progressed:
                pending = [b for b in pending if b.key not in self.failed]
            if not cands:
                if not progressed:
                    for b in pending:
                        self.failed[b.key] = "blocked"
                    break
                continue
            t_star = min(cands, key=lambda r: r.end)
            m_star = t_star.machine
            star_ids = t_star.machine_ids
            conflict = []
            for r in cands:
                if r.machine_ids & star_ids:
                    if r.start < t_star.end:
                        conflict.append(r)
                    continue
                st = r.batch.steps[self.next_step[r.batch.key]]
                if not st.partners and not t_star.partners and any(o.machine.id == m_star.id for o in st.options):
                    alt = self._evaluate(r.batch, next(o for o in st.options if o.machine.id == m_star.id),
                                         readies[r.batch.key], st)
                    if alt and alt.start < t_star.end and alt.end <= r.end + (r.end - r.start):
                        conflict.append(alt)
            chosen = min(conflict or [t_star], key=self._priority)
            self._commit(chosen)
            pending = [b for b in pending if self.next_step[b.key] < len(b.steps) and b.key not in self.failed]
        self._finish_locked()
        return self

    # -- results
    def evaluate_demand(self) -> list[dict]:
        out = []
        for d in self.p.demand:
            avail, ok = d.stock_ready if d.from_stock > EPS else None, True
            for b, _q in d.sources:
                dn = self.done.get(b.key)
                if not dn:
                    ok = False
                    continue
                avail = max(avail or dn["ship"], dn["ship"])
            if d.quantity <= EPS:
                avail = None
            if d.quantity > EPS and not d.sources:
                avail = avail or self.p.start
            late_h = ((avail - d.due_at).total_seconds() / 3600) if (ok and avail) else None
            # On time in full: what is ready to ship by the due date, against what the market asked for.
            on_time_qty = d.from_stock if d.from_stock > EPS and (d.stock_ready is None or d.stock_ready <= d.due_at) else 0.0
            for b, q in d.sources:
                dn = self.done.get(b.key)
                if dn and dn["ship"] <= d.due_at:
                    on_time_qty += q
            on_time_qty = min(on_time_qty, d.quantity) if d.quantity > EPS else 0.0
            in_full = d.requested > EPS and on_time_qty >= d.requested - max(EPS, d.requested * 1e-6)
            out.append({"row": d, "available": avail if ok else None, "fulfilled": ok and d.quantity > EPS,
                        "late_hours": max(0.0, late_h) if late_h is not None else None,
                        "on_time": ok and d.quantity > EPS and (late_h is None or late_h <= 0),
                        "on_time_qty": on_time_qty, "otif": in_full})
        return out

    def score(self) -> tuple:
        dem = self.evaluate_demand()
        unfilled = sum(1 for x in dem if not x["fulfilled"] and x["row"].quantity > EPS)
        late = sum(1 for x in dem if x["fulfilled"] and not x["on_time"])
        late_days = sum((x["late_hours"] or 0) / 24 for x in dem)
        value_on_time = sum((x["row"].price or 0) * x["row"].quantity for x in dem if x["on_time"])
        co_h = sum(o.co_minutes + o.co_wait + o.reclean_minutes for o in self.ops) / 60
        makespan = max([o.end for o in self.ops] + [self.p.start])
        span_h = (makespan - self.p.start).total_seconds() / 3600
        obj = self.p.objective
        if obj == "sales_value":
            return (len(self.failed), -round(value_on_time, 2), unfilled + late, late_days, co_h)
        if obj == "utilization":
            return (len(self.failed), round(co_h, 1), unfilled, span_h, late_days)
        return (len(self.failed), unfilled + late, round(late_days, 2), co_h, span_h)


def solve(plan: Plan, time_budget_s: float = 8.0, max_runs: int = 40) -> tuple[Scheduler, int]:
    """Build the base schedule, then randomised variants within the time budget; keep the best."""
    w = WEIGHTS.get(plan.objective, WEIGHTS["on_time"])
    t0 = time.monotonic()
    best = Scheduler(plan, w).run()
    best_score = best.score()
    runs = 1
    first = time.monotonic() - t0
    while runs < max_runs and time.monotonic() - t0 + first * 1.2 < time_budget_s:
        noise = [6.0, 24.0, 72.0][runs % 3]
        ww = {k: v * (0.6 + 0.8 * random.Random(runs * 7).random()) for k, v in w.items()}
        s = Scheduler(plan, ww, noise=noise, seed=runs).run()
        sc = s.score()
        if sc < best_score:
            best, best_score = s, sc
        runs += 1
    return best, runs


def as_utc(t: dt.datetime | None) -> dt.datetime | None:
    return t.replace(tzinfo=dt.timezone.utc) if t else None


def summarise(s: Scheduler, runtime_ms: int, runs: int) -> dict:
    """KPIs and warnings for the stored plan."""
    p = s.p
    dem = s.evaluate_demand()
    by_cur_req, by_cur_ok = defaultdict(float), defaultdict(float)
    for x in dem:
        d = x["row"]
        if d.price and d.currency:
            by_cur_req[d.currency] += d.price * d.quantity
            if x["on_time"]:
                by_cur_ok[d.currency] += d.price * d.quantity
    active = [x for x in dem if x["row"].quantity > EPS]
    on_time = sum(1 for x in active if x["on_time"])
    util = []
    for m in p.machines.values():
        avail = m.cal.work_minutes(p.start, p.horizon_end)
        busy = 0.0
        co = 0.0
        for o in s.ops:
            if o.machine.id != m.id:
                continue
            busy += m.cal.work_minutes(max(o.start, p.start), min(o.end, p.horizon_end))
            if o.co_start:
                co += m.cal.work_minutes(max(o.co_start, p.start), min(o.co_end, p.horizon_end))
        if busy or co:
            util.append({"machine_id": m.id, "code": m.code, "available_hours": avail / 60, "busy_hours": busy / 60,
                         "changeover_hours": co / 60, "utilization": (busy + co) / avail if avail else None})
    warnings = list(p.warnings) + s.lock_warnings + s.hold_warnings
    for b in p.batches:
        if b.key in s.failed:
            warnings.append({"kind": "unscheduled", "code": b.code, "key": b.key, "reason": s.failed[b.key]})
        for n in s.material_notes.get(b.key, []):
            warnings.append({"kind": "material_short", "code": n["code"], "batch": b.code, "key": b.key, "short": n["short"],
                             "arrival": as_utc(n["arrival"]), "no_lead_time": n["no_lead_time"]})
    warnings += _campaign_short(s) + _shelf_life_short(s, dem)
    after = [b for b in p.batches if b.key in s.done and s.done[b.key]["end"] > p.horizon_end]
    if after:
        warnings.append({"kind": "after_horizon", "count": len(after)})
    co_h = sum(o.co_minutes + o.co_wait + o.reclean_minutes for o in s.ops) / 60
    cost = None
    if p.cost_currency:
        cur = p.cost_currency
        fg_cost = lambda iid: p.items[iid]["standard_cost"]
        delivered = [x for x in active if x["fulfilled"]]
        cost = {
            "currency": cur,
            "materials": round(sum(b.material_cost or 0 for b in p.batches if b.key in s.done), 2),
            "deliveries": round(sum(float(fg_cost(x["row"].item_id)) * x["row"].quantity for x in delivered
                                    if fg_cost(x["row"].item_id) is not None), 2),
            "margin": round(sum((x["row"].price - float(fg_cost(x["row"].item_id))) * x["row"].quantity for x in delivered
                                if x["row"].price and x["row"].currency == cur and fg_cost(x["row"].item_id) is not None), 2),
            "missing": sorted({p.items[c]["code"] for b in p.batches for c, _q in b.materials if p.items[c]["standard_cost"] is None}
                              | {x["row"].code for x in active if fg_cost(x["row"].item_id) is None}),
        }
    return {
        "batches": len(p.batches), "scheduled": len(s.done), "unscheduled": len(s.failed),
        "demand_lines": len(active), "on_time": on_time, "late": sum(1 for x in active if x["fulfilled"] and not x["on_time"]),
        "unfilled": sum(1 for x in active if not x["fulfilled"]),
        "on_time_pct": round(on_time / len(active) * 100, 1) if active else None,
        "late_days": round(sum((x["late_hours"] or 0) for x in active) / 24, 1),
        "value": [{"currency": c, "requested": by_cur_req[c], "on_time": by_cur_ok[c]} for c in sorted(by_cur_req)],
        "changeover_hours": round(co_h, 1), "changeovers": sum(1 for o in s.ops if o.co_start),
        "campaign_breaks": s.campaign_breaks,
        "finish": as_utc(max([o.end for o in s.ops], default=None)),
        "utilization": sorted(util, key=lambda u: -(u["utilization"] or 0)),
        "warnings": warnings, "runtime_ms": runtime_ms, "runs": runs, "engine": ENGINE_VERSION, "cost": cost,
        "rounded": sum(1 for x in active if x["row"].before_rounding is not None),
        "otif": _otif(dem),
    }


def _otif(dem: list[dict]) -> dict:
    """On time in full: share of delivery lines shipped complete by their due date, and share of the quantity."""
    lines = [x for x in dem if x["row"].requested > EPS]
    requested = sum(x["row"].requested for x in lines)
    on_time = sum(min(x["on_time_qty"], x["row"].requested) for x in lines)
    otif = sum(1 for x in lines if x["otif"])
    return {"lines": len(lines), "otif": otif, "pct": round(otif / len(lines) * 100, 1) if lines else None,
            "requested": round(requested, 3), "on_time_qty": round(on_time, 3),
            "qty_pct": round(on_time / requested * 100, 1) if requested > EPS else None,
            "in_full": sum(1 for x in lines if x["row"].quantity >= x["row"].requested - EPS)}


def batch_expiry(s: Scheduler, b: Batch) -> dt.date | None:
    """End of production plus the item's shelf life, as a date at the site."""
    months = s.p.items[b.item_id]["shelf_life_months"]
    d = s.done.get(b.key)
    if not months or not d:
        return None
    return add_months(d["end"].date(), months)


def _campaign_short(s: Scheduler) -> list[dict]:
    """Runs of an item on a machine that are shorter than its minimum campaign (one warning per item: the shortest)."""
    p = s.p
    if not p.campaigns:
        return []
    by_m = defaultdict(list)
    for o in s.ops:
        by_m[o.machine.id].append(o)
    worst: dict[str, dict] = {}
    for mid, ops in by_m.items():
        ops.sort(key=lambda o: o.start)
        runs, cur = [], None
        for o in ops:
            if cur and cur["item"] == o.batch.item_id and o.co_kind != "campaign_end":
                cur["keys"].add(o.batch.key)
            else:
                cur = {"item": o.batch.item_id, "keys": {o.batch.key}}
                runs.append(cur)
        for r in runs:
            camp = p.campaigns.get((r["item"], mid)) or p.campaigns.get((r["item"], None))
            if not camp or not camp["min_batches"] or len(r["keys"]) >= camp["min_batches"]:
                continue
            have = sum(1 for b in p.batches if b.item_id == r["item"])
            w = {"kind": "campaign_short", "code": p.items[r["item"]]["code"], "machine": p.machines[mid].code,
                 "batches": len(r["keys"]), "min": camp["min_batches"], "planned": have}
            if r["item"] not in worst or w["batches"] < worst[r["item"]]["batches"]:
                worst[r["item"]] = w
    return list(worst.values())


def _shelf_life_short(s: Scheduler, dem: list[dict]) -> list[dict]:
    """Deliveries from new batches that would arrive with less shelf life left than the market requires."""
    out = []
    for x in dem:
        d = x["row"]
        if not d.min_shelf:
            continue
        months = s.p.items[d.item_id]["shelf_life_months"]
        for b, _q in d.sources:
            exp = batch_expiry(s, b)
            if exp and not shelf_ok(exp, s.done[b.key]["end"].date(), months, d.min_shelf, d.due_date):
                out.append({"kind": "shelf_life_short", "code": d.code, "market": d.market, "batch_key": b.key,
                            "expires": exp, "min": d.min_shelf})
                break
    return out
