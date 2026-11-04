"""Net requirements: what has to be made and bought to meet the sales plan in a horizon.

Works level by level through the active bills of materials (low-level codes), so an item used in
several products is netted once against its stock:

  finished goods   demand + safety stock - usable stock  -> batches (fixed or partial)
  semi-finished    needs of the batches above + safety - usable stock -> batches
  work in process  same again
  materials        needs of all batches vs released (and optionally quarantine) stock -> shortages

The Phase 5 planning engine schedules the batches found here on machines and in time.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from decimal import Decimal

from .units import UnitBook

PRODUCED = ("wip", "semi_finished", "finished")
USE_STOCK_FEATURE = {"finished": "use_stock_fg", "semi_finished": "use_stock_semi", "wip": "use_stock_wip"}
ZERO = Decimal(0)
HUNDRED = Decimal(100)


def month_end(d: dt.date) -> dt.date:
    nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def price_on(tx, item_id, market_id, day: dt.date):
    return tx.one("SELECT price, currency FROM prices WHERE item_id = %s AND market_id = %s AND valid_from <= %s"
                  " AND (valid_to IS NULL OR valid_to >= %s) ORDER BY valid_from DESC LIMIT 1", item_id, market_id, day, day)


def add_months(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.month - 1 + int(months), 12)
    first = dt.date(d.year + y, m + 1, 1)
    return first.replace(day=min(d.day, month_end(first).day))


def lot_expiry(lot: dict, shelf_life_months) -> dt.date | None:
    """A lot's expiry date, or its manufacturing date plus the item's shelf life when no expiry was entered."""
    if lot.get("expires_on"):
        return lot["expires_on"]
    if lot.get("manufactured_on") and shelf_life_months:
        return add_months(lot["manufactured_on"], shelf_life_months)
    return None


def potency_factors(tx, site_id: str, include_quarantine: bool, on: dt.date, enabled: bool) -> dict[str, Decimal]:
    """Assay compensation: how much more of a material is needed than the formula states, per material.

    Each lot needs standard x 100 / assay (x 100 / (100 - LOD) when the assay is reported on the dried substance).
    The factor is the average over the usable lots of the material, weighted by quantity; lots without an assay
    count as 100 %. Deliveries not received yet are assumed to be 100 %."""
    if not enabled:
        return {}
    statuses = ("released", "quarantine") if include_quarantine else ("released",)
    acc: dict[str, list] = defaultdict(lambda: [ZERO, ZERO])
    for r in tx.q("SELECT s.item_id, s.quantity, s.assay_pct, s.lod_pct, i.assay_basis FROM stock_lots s JOIN items i ON i.id = s.item_id"
                  " WHERE s.site_id = %s::uuid AND s.status = ANY(string_to_array(%s, ',')) AND s.quantity > 0"
                  " AND (s.expires_on IS NULL OR s.expires_on >= %s)", site_id, ",".join(statuses), on):
        q = Decimal(r["quantity"])
        f = Decimal(1)
        if r["assay_pct"]:
            f = HUNDRED / Decimal(r["assay_pct"])
            if r["assay_basis"] == "dried" and r["lod_pct"] is not None:
                f *= HUNDRED / (HUNDRED - Decimal(r["lod_pct"]))
        a = acc[str(r["item_id"])]
        a[0] += q * f
        a[1] += q
    return {iid: (s / q) for iid, (s, q) in acc.items() if q > 0 and s / q != 1}


def line_needs(book: UnitBook, lines: list[dict], scale: Decimal, features: dict, factors: dict[str, Decimal]) -> tuple[list, list]:
    """Quantity of each bill-of-materials line for one batch, in the component's stock unit.

    Overage (when switched on) adds the registered excess. Assay compensation (when on) raises assay-compensated lines
    by the potency of the stock; the compensating material (when on) is reduced by the same amount so the batch weight
    or volume stays the same. Returns [(line, quantity)], [problems]."""
    over_on = features.get("overage", True)
    assay_on = features.get("assay_compensation", True)
    comp_on = features.get("compensating_material", True)
    rows, extra, problems = [], [], []
    for l in lines:
        base = Decimal(l["quantity"]) * scale
        over = (1 + Decimal(l["overage_pct"]) / HUNDRED) if over_on else Decimal(1)
        need = base * over
        f = factors.get(str(l["component_item_id"])) if assay_on and l["assay_compensated"] else None
        if f:
            extra.append((l, need * f - need))
            need = need * f
        rows.append([l, need])
    if comp_on and extra:
        comp_row = next((r for r in rows if r[0]["is_compensating"]), None)
        if comp_row:
            citem = book.item(str(comp_row[0]["component_item_id"]))
            for l, delta in extra:
                try:
                    comp_row[1] -= book.convert(citem, delta, str(l["uom_id"]), str(comp_row[0]["uom_id"]))
                except Exception:
                    problems.append({"kind": "compensation_unit", "code": citem["code"]})
            if comp_row[1] < 0:
                problems.append({"kind": "compensation_negative", "code": citem["code"]})
                comp_row[1] = ZERO
    out = []
    for l, need in rows:
        comp = book.item(str(l["component_item_id"]))
        out.append((l, book.convert(comp, need, str(l["uom_id"]), str(comp["stock_uom_id"]))))
    return out, problems


DEMAND_SQL = """
SELECT d.id, d.item_id, d.market_id, d.month, d.quantity, d.due_date, m.code AS market,
       im.max_sellable_per_month AS max_qty, im.min_remaining_shelf_pct AS min_shelf
  FROM demand_lines d JOIN markets m ON m.id = d.market_id
  LEFT JOIN item_markets im ON im.item_id = d.item_id AND im.market_id = d.market_id
 WHERE d.site_id = %s::uuid AND coalesce(d.due_date, (d.month + interval '1 month - 1 day')::date) BETWEEN %s AND %s
 ORDER BY coalesce(d.due_date, (d.month + interval '1 month - 1 day')::date), d.quantity DESC
"""


def load_demand(tx, site_id: str, start: dt.date, end: dt.date, features: dict) -> list[dict]:
    """What has to be delivered in the horizon.

    Sales plan on: the sales plan lines of the site. Sales plan off: every finished product made at the site
    (it has a routing here) is planned at its maximum sellable quantity per market for every month that ends in
    the horizon, so plans fill capacity with what the markets can take."""
    if features.get("sales_plan", True):
        return tx.q(DEMAND_SQL, site_id, start, end)
    rows = tx.q(
        "SELECT im.item_id, im.market_id, m.code AS market, im.max_sellable_per_month AS max_qty, im.min_remaining_shelf_pct AS min_shelf"
        "  FROM item_markets im JOIN markets m ON m.id = im.market_id JOIN items i ON i.id = im.item_id"
        " WHERE im.active AND i.active AND i.type = 'finished' AND im.max_sellable_per_month > 0"
        "   AND EXISTS (SELECT 1 FROM routings r WHERE r.item_id = i.id AND r.site_id = %s::uuid)"
        " ORDER BY i.code, m.code", site_id)
    out = []
    month = start.replace(day=1)
    while month <= end:
        due = month_end(month)
        if start <= due <= end:
            for r in rows:
                out.append({"id": None, "item_id": r["item_id"], "market_id": r["market_id"], "month": month, "quantity": r["max_qty"],
                            "due_date": None, "market": r["market"], "max_qty": r["max_qty"], "min_shelf": r["min_shelf"]})
        month = month_end(month) + dt.timedelta(days=1)
    return out


def batch_sizes(net: Decimal, expected: Decimal, mode: str, min_pct) -> list[Decimal]:
    """Split a net quantity into batches. Fixed batches are always full; a partial last batch is
    allowed down to the minimum batch percentage."""
    if net <= 0 or expected <= 0:
        return []
    if mode != "partial":
        return [expected] * math.ceil(net / expected)
    full = int(net // expected)
    rest = net - expected * full
    sizes = [expected] * full
    if rest > 0:
        sizes.append(max(rest, expected * Decimal(min_pct or 0) / HUNDRED))
    return sizes


def shelf_ok(expiry: dt.date | None, made: dt.date | None, shelf_months, min_pct, on: dt.date) -> bool:
    """Whether a lot still has the market's minimum share of its shelf life left on the given day."""
    if expiry is None:
        return True
    if expiry < on:
        return False
    if not min_pct:
        return True
    total = (expiry - made).days if made else (float(shelf_months) * 30.44 if shelf_months else None)
    if not total:
        return True
    return (expiry - on).days >= float(total) * float(min_pct) / 100


def net_requirements(tx, site_id: str, start: dt.date, end: dt.date, features: dict, include_quarantine: bool,
                     today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    book = UnitBook(tx)
    costs_on = bool(features.get("costs", False))
    items = {str(r["id"]): r for r in tx.q(
        "SELECT i.id, i.code, i.name_en, i.name_ar, i.type, i.stock_uom_id, u.code AS uom, i.safety_stock, i.lead_time_days,"
        " i.qc_release_days, i.release_lead_days, i.not_stock_controlled, i.active, i.moq, i.standard_cost, i.shelf_life_months"
        " FROM items i JOIN uoms u ON u.id = i.stock_uom_id")}
    boms = {str(b["item_id"]): b for b in tx.q("SELECT * FROM boms WHERE status = 'active'")}
    lines = defaultdict(list)
    for l in tx.q("SELECT l.* FROM bom_lines l JOIN boms b ON b.id = l.bom_id WHERE b.status = 'active' ORDER BY l.line_no"):
        lines[str(l["bom_id"])].append(l)
    factors = potency_factors(tx, site_id, include_quarantine, start, bool(features.get("assay_compensation", True)))

    # Low-level codes: an item sits one level below the deepest parent that uses it.
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

    # Demand due in the horizon: the due date, or the end of the month when there is none.
    demand_rows = load_demand(tx, site_id, start, end, features)
    gross: dict[str, Decimal] = defaultdict(Decimal)
    demand: dict[str, Decimal] = defaultdict(Decimal)
    used_by: dict[str, list] = defaultdict(list)
    over_limit, value = [], defaultdict(Decimal)
    first_due: dict[str, dt.date] = {}
    loosest: dict[str, float] = {}          # the least strict minimum remaining shelf life among markets with demand
    for d in demand_rows:
        iid, qty = str(d["item_id"]), Decimal(d["quantity"])
        gross[iid] += qty
        demand[iid] += qty
        due = d["due_date"] or month_end(d["month"])
        first_due[iid] = min(first_due.get(iid, due), due)
        loosest[iid] = min(loosest.get(iid, 100.0), float(d["min_shelf"] or 0))
        if d["max_qty"] is not None and qty > Decimal(d["max_qty"]):
            over_limit.append({"item_id": iid, "code": items[iid]["code"], "market": d["market"], "month": d["month"].strftime("%Y-%m"),
                               "quantity": qty, "limit": Decimal(d["max_qty"])})
        p = price_on(tx, d["item_id"], d["market_id"], today)
        if p:
            value[p["currency"]] += qty * Decimal(p["price"])

    # Stock by lot: expired lots are not usable; finished lots too short-dated for every market are set aside.
    stock = defaultdict(lambda: {"released": ZERO, "quarantine": ZERO, "rejected": ZERO, "lots": 0, "next_expiry": None,
                                 "expired": ZERO, "short_dated": ZERO})
    for s in tx.q("SELECT item_id, status, quantity, manufactured_on, expires_on FROM stock_lots WHERE site_id = %s::uuid", site_id):
        iid = str(s["item_id"])
        rec, it = stock[iid], items.get(iid)
        if not it:
            continue
        q = Decimal(s["quantity"])
        rec["lots"] += 1
        if s["status"] == "rejected":
            rec["rejected"] += q
            continue
        exp = lot_expiry(s, it["shelf_life_months"])
        if exp and exp < start:
            rec["expired"] += q
            continue
        if it["type"] == "finished" and iid in first_due and \
                not shelf_ok(exp, s["manufactured_on"], it["shelf_life_months"], loosest.get(iid), first_due[iid]):
            rec["short_dated"] += q
            continue
        rec[s["status"]] += q
        if exp and (rec["next_expiry"] is None or exp < rec["next_expiry"]):
            rec["next_expiry"] = exp

    produced, materials, problems = [], [], []
    order = sorted(items, key=lambda i: (llc.get(i, 0), items[i]["code"]))
    for iid in order:
        it = items[iid]
        g = gross.get(iid, ZERO)
        st = stock[iid]
        safety = Decimal(it["safety_stock"] or 0)
        if it["type"] in PRODUCED:
            use = features.get(USE_STOCK_FEATURE[it["type"]], True)
            usable = (st["released"] + (st["quarantine"] if include_quarantine else ZERO)) if use else ZERO
            if g == 0 and (not use or usable >= safety):
                continue
            net = max(ZERO, g + (safety if use else ZERO) - usable)
            row = {
                "item_id": iid, "code": it["code"], "name_en": it["name_en"], "name_ar": it["name_ar"], "type": it["type"],
                "uom": it["uom"], "level": llc.get(iid, 0), "demand": demand.get(iid, ZERO), "dependent": g - demand.get(iid, ZERO),
                "safety": safety, "released": st["released"], "quarantine": st["quarantine"], "stock_counted": use,
                "usable": usable, "stock_used": min(usable, g + safety) if use else ZERO, "net": net, "used_by": used_by.get(iid, []),
                "batches": 0, "batch_sizes": [], "batch_output": None, "batch_mode": None, "planned": ZERO, "surplus": ZERO,
                "bom_version": None, "no_bom": False, "first_due": first_due.get(iid),
                "expired": st["expired"], "short_dated": st["short_dated"],
            }
            bom = boms.get(iid)
            if not bom:
                row["no_bom"] = net > 0
                if net > 0:
                    problems.append({"kind": "no_bom", "code": it["code"]})
                produced.append(row)
                continue
            nominal = book.to_stock(iid, Decimal(bom["batch_size"]), str(bom["batch_uom_id"]))
            expected = nominal * Decimal(bom["yield_pct"]) / HUNDRED
            sizes = batch_sizes(net, expected, bom["batch_mode"], bom["min_batch_pct"])
            planned = sum(sizes, ZERO)
            row.update(batches=len(sizes), batch_sizes=sizes, batch_output=expected, batch_mode=bom["batch_mode"],
                       planned=planned, surplus=planned - net, bom_version=bom["version"])
            produced.append(row)
            if planned > 0:
                needs, probs = line_needs(book, lines[str(bom["id"])], planned / expected, features, factors)
                for pr in probs:
                    if pr not in problems:
                        problems.append({**pr, "item": it["code"]})
                for l, need in needs:
                    cid = str(l["component_item_id"])
                    gross[cid] += need
                    used_by[cid].append({"code": it["code"], "quantity": need, "batches": len(sizes)})
        else:
            if g == 0:
                continue
            unlimited = bool(it["not_stock_controlled"])
            available = st["released"] + (st["quarantine"] if include_quarantine else ZERO)
            shortage = ZERO if unlimited else max(ZERO, g - available)
            lead = int(it["lead_time_days"] or 0)
            qc = math.ceil(Decimal(it["qc_release_days"] or 0))
            arrival = today + dt.timedelta(days=lead + qc) if shortage > 0 else None
            # Suggested purchase: the shortage plus what brings stock back to safety stock, at least the minimum order.
            order_qty = ZERO
            if not unlimited and (shortage > 0 or (safety > 0 and available - g < safety)):
                order_qty = max(ZERO, g + safety - available)
                if it["moq"] and order_qty < Decimal(it["moq"]):
                    order_qty = Decimal(it["moq"])
            row = {
                "item_id": iid, "code": it["code"], "name_en": it["name_en"], "name_ar": it["name_ar"], "type": it["type"],
                "uom": it["uom"], "required": g, "released": st["released"], "quarantine": st["quarantine"],
                "available": available, "shortage": shortage, "after": available - g, "safety": safety,
                "below_safety": (not unlimited) and safety > 0 and available - g < safety,
                "not_stock_controlled": unlimited, "lead_time_days": lead, "qc_release_days": qc,
                "earliest_arrival": arrival, "late": bool(arrival and arrival > end), "used_by": used_by.get(iid, []),
                "next_expiry": st["next_expiry"], "expired": st["expired"],
                "quarantine_would_cover": (not include_quarantine) and shortage > 0 and st["released"] + st["quarantine"] >= g,
                "potency": factors.get(iid), "moq": it["moq"], "order_qty": order_qty,
                "unit_cost": it["standard_cost"] if costs_on else None,
                "order_value": (order_qty * Decimal(it["standard_cost"])) if costs_on and it["standard_cost"] and order_qty else None,
                "required_value": (g * Decimal(it["standard_cost"])) if costs_on and it["standard_cost"] else None,
            }
            materials.append(row)
            if shortage > 0:
                problems.append({"kind": "shortage", "code": it["code"]})

    produced.sort(key=lambda r: ({"finished": 0, "semi_finished": 1, "wip": 2}[r["type"]], r["code"]))
    materials.sort(key=lambda r: (r["shortage"] <= 0, r["type"], r["code"]))
    cost = None
    if costs_on:
        currency = tx.val("SELECT cost_currency FROM tenants LIMIT 1")
        cost = {"currency": currency,
                "materials": sum((m["required_value"] or ZERO for m in materials), ZERO),
                "orders": sum((m["order_value"] or ZERO for m in materials), ZERO),
                "missing": [m["code"] for m in materials if m["unit_cost"] is None]}
    return {
        "horizon": {"start": start, "end": end, "days": (end - start).days + 1},
        "options": {"include_quarantine": include_quarantine,
                    "use_stock": {k: bool(features.get(v, True)) for k, v in USE_STOCK_FEATURE.items()},
                    "sales_plan": bool(features.get("sales_plan", True)),
                    "assay_compensation": bool(features.get("assay_compensation", True))},
        "produced": produced, "materials": materials, "over_limit": over_limit, "problems": problems,
        "sales_value": [{"currency": c, "value": v} for c, v in sorted(value.items())],
        "cost": cost,
        "totals": {"batches": sum(r["batches"] for r in produced), "shortages": sum(1 for m in materials if m["shortage"] > 0),
                   "late": sum(1 for m in materials if m["late"]), "no_bom": sum(1 for r in produced if r["no_bom"]),
                   "demand_lines": len(demand_rows)},
    }
