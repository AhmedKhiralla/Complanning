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


def net_requirements(tx, site_id: str, start: dt.date, end: dt.date, features: dict, include_quarantine: bool,
                     today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    book = UnitBook(tx)
    items = {str(r["id"]): r for r in tx.q(
        "SELECT i.id, i.code, i.name_en, i.name_ar, i.type, i.stock_uom_id, u.code AS uom, i.safety_stock, i.lead_time_days,"
        " i.qc_release_days, i.release_lead_days, i.not_stock_controlled, i.active"
        " FROM items i JOIN uoms u ON u.id = i.stock_uom_id")}
    boms = {str(b["item_id"]): b for b in tx.q("SELECT * FROM boms WHERE status = 'active'")}
    lines = defaultdict(list)
    for l in tx.q("SELECT l.* FROM bom_lines l JOIN boms b ON b.id = l.bom_id WHERE b.status = 'active' ORDER BY l.line_no"):
        lines[str(l["bom_id"])].append(l)

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

    stock = defaultdict(lambda: {"released": ZERO, "quarantine": ZERO, "rejected": ZERO, "lots": 0, "next_expiry": None})
    for s in tx.q("SELECT item_id, status, sum(quantity) AS qty, count(*) AS lots, min(expires_on) FILTER (WHERE status <> 'rejected') AS exp"
                  " FROM stock_lots WHERE site_id = %s::uuid GROUP BY item_id, status", site_id):
        rec = stock[str(s["item_id"])]
        rec[s["status"]] += Decimal(s["qty"])
        rec["lots"] += s["lots"]
        if s["exp"] and (rec["next_expiry"] is None or s["exp"] < rec["next_expiry"]):
            rec["next_expiry"] = s["exp"]

    # Demand due in the horizon: the due date, or the end of the month when there is none.
    demand_rows = tx.q(
        "SELECT d.item_id, d.market_id, d.month, d.quantity, d.due_date, m.code AS market, im.max_sellable_per_month AS max_qty"
        "  FROM demand_lines d JOIN markets m ON m.id = d.market_id"
        "  LEFT JOIN item_markets im ON im.item_id = d.item_id AND im.market_id = d.market_id"
        " WHERE d.site_id = %s::uuid AND coalesce(d.due_date, (d.month + interval '1 month - 1 day')::date) BETWEEN %s AND %s",
        site_id, start, end)
    gross: dict[str, Decimal] = defaultdict(Decimal)
    demand: dict[str, Decimal] = defaultdict(Decimal)
    used_by: dict[str, list] = defaultdict(list)
    over_limit, value = [], defaultdict(Decimal)
    first_due: dict[str, dt.date] = {}
    for d in demand_rows:
        iid, qty = str(d["item_id"]), Decimal(d["quantity"])
        gross[iid] += qty
        demand[iid] += qty
        due = d["due_date"] or month_end(d["month"])
        first_due[iid] = min(first_due.get(iid, due), due)
        if d["max_qty"] is not None and qty > Decimal(d["max_qty"]):
            over_limit.append({"item_id": iid, "code": items[iid]["code"], "market": d["market"], "month": d["month"].strftime("%Y-%m"),
                               "quantity": qty, "limit": Decimal(d["max_qty"])})
        p = price_on(tx, d["item_id"], d["market_id"], today)
        if p:
            value[p["currency"]] += qty * Decimal(p["price"])

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
                scale = planned / expected
                for l in lines[str(bom["id"])]:
                    cid = str(l["component_item_id"])
                    comp = book.item(cid)
                    need = Decimal(l["quantity"]) * scale * (1 + Decimal(l["overage_pct"]) / HUNDRED)
                    need = book.convert(comp, need, str(l["uom_id"]), str(comp["stock_uom_id"]))
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
            row = {
                "item_id": iid, "code": it["code"], "name_en": it["name_en"], "name_ar": it["name_ar"], "type": it["type"],
                "uom": it["uom"], "required": g, "released": st["released"], "quarantine": st["quarantine"],
                "available": available, "shortage": shortage, "after": available - g, "safety": safety,
                "below_safety": (not unlimited) and safety > 0 and available - g < safety,
                "not_stock_controlled": unlimited, "lead_time_days": lead, "qc_release_days": qc,
                "earliest_arrival": arrival, "late": bool(arrival and arrival > end), "used_by": used_by.get(iid, []),
                "next_expiry": st["next_expiry"],
                "quarantine_would_cover": (not include_quarantine) and shortage > 0 and st["released"] + st["quarantine"] >= g,
            }
            materials.append(row)
            if shortage > 0:
                problems.append({"kind": "shortage", "code": it["code"]})

    produced.sort(key=lambda r: ({"finished": 0, "semi_finished": 1, "wip": 2}[r["type"]], r["code"]))
    materials.sort(key=lambda r: (r["shortage"] <= 0, r["type"], r["code"]))
    return {
        "horizon": {"start": start, "end": end, "days": (end - start).days + 1},
        "options": {"include_quarantine": include_quarantine,
                    "use_stock": {k: bool(features.get(v, True)) for k, v in USE_STOCK_FEATURE.items()}},
        "produced": produced, "materials": materials, "over_limit": over_limit,
        "sales_value": [{"currency": c, "value": v} for c, v in sorted(value.items())],
        "totals": {"batches": sum(r["batches"] for r in produced), "shortages": sum(1 for m in materials if m["shortage"] > 0),
                   "late": sum(1 for m in materials if m["late"]), "no_bom": sum(1 for r in produced if r["no_bom"]),
                   "demand_lines": len(demand_rows)},
    }
