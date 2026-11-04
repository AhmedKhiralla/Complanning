"""Phase 4: sales plan, stock on hand and net requirements, with Excel template, import and export."""
from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from starlette.responses import Response

from ..api import ApiError, Call, endpoint, not_found
from ..defaults import effective_features
from ..netting import month_end, net_requirements, price_on
from ..perms import require_plan
from .excel import XLSX, _autosize, _cell, _read_upload, _style_header, _wb, _xlsx

STATUSES = ("released", "quarantine", "rejected")
STATUS_NAMES = {"released": "Released", "quarantine": "Quarantine", "rejected": "Rejected"}


def _today(call: Call) -> dt.date:
    return call.tx.val("SELECT current_date")


def _month(v: str | None, default: dt.date) -> dt.date:
    if not v:
        return default.replace(day=1)
    try:
        return dt.date.fromisoformat(v[:7] + "-01")
    except ValueError:
        raise ApiError(422, "invalid", "Use a month like 2026-11.")


def _add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, 1)


def _features(call: Call) -> dict:
    return effective_features(call.tx.val("SELECT features FROM tenants WHERE id = %s", call.tenant_id))


# ================================================================== sales plan
@endpoint(auth="tenant_user")
def get_demand(call: Call):
    """Grid of finished products x markets (rows) by month (columns)."""
    sid = call.path["site_id"]
    require_plan(call, sid)
    today = _today(call)
    start = _month(call.query.get("start"), today)
    try:
        n = max(1, min(12, int(call.query.get("months") or 6)))
    except ValueError:
        n = 6
    months = [_add_months(start, i) for i in range(n)]
    end = _add_months(start, n)
    rows = call.tx.q(
        "SELECT im.item_id, im.market_id, im.max_sellable_per_month AS max_qty, im.active AS market_active,"
        "       i.code, i.name_en, i.name_ar, u.code AS uom, m.code AS market, m.name_en AS market_name_en,"
        "       m.name_ar AS market_name_ar, m.currency"
        "  FROM item_markets im JOIN items i ON i.id = im.item_id JOIN markets m ON m.id = im.market_id"
        "  JOIN uoms u ON u.id = i.stock_uom_id"
        " WHERE (i.type = 'finished' AND i.active AND m.active AND im.active)"
        "    OR EXISTS (SELECT 1 FROM demand_lines d WHERE d.site_id = %s::uuid AND d.item_id = im.item_id"
        "               AND d.market_id = im.market_id AND d.month >= %s AND d.month < %s)"
        " ORDER BY i.code, m.code", sid, start, end)
    lines = call.tx.q("SELECT id, item_id, market_id, month, quantity, due_date, notes FROM demand_lines"
                      " WHERE site_id = %s::uuid AND month >= %s AND month < %s", sid, start, end)
    cells: dict[tuple, dict] = {}
    for l in lines:
        cells[(str(l["item_id"]), str(l["market_id"]), l["month"].strftime("%Y-%m"))] = {
            "id": l["id"], "quantity": l["quantity"], "due_date": l["due_date"], "notes": l["notes"]}
    out = []
    for r in rows:
        key = (str(r["item_id"]), str(r["market_id"]))
        p = price_on(call.tx, r["item_id"], r["market_id"], today)
        out.append({**r, "price": p["price"] if p else None,
                    "cells": {m.strftime("%Y-%m"): cells[key + (m.strftime("%Y-%m"),)]
                              for m in months if key + (m.strftime("%Y-%m"),) in cells}})
    return {"start": start.strftime("%Y-%m"), "months": [m.strftime("%Y-%m") for m in months], "today": today,
            "rows": out, "lines": len(lines)}


class DemandCell(BaseModel):
    item_id: str
    market_id: str
    month: str
    quantity: Decimal | None = Field(default=None, ge=0, le=Decimal("1e12"))
    due_date: dt.date | None = None
    notes: str | None = Field(default=None, max_length=300)

    @field_validator("month")
    @classmethod
    def _m(cls, v):
        try:
            return dt.date.fromisoformat(v[:7] + "-01").strftime("%Y-%m")
        except ValueError:
            raise ValueError("Use a month like 2026-11.")


class DemandIn(BaseModel):
    lines: list[DemandCell] = Field(max_length=5000)


def _save_demand(call: Call, sid: str, cells: list[DemandCell]) -> dict:
    """Upsert sales plan cells; an empty or zero quantity removes the cell."""
    known = {(str(r["item_id"]), str(r["market_id"])) for r in call.tx.q("SELECT item_id, market_id FROM item_markets")}
    codes = {str(r["id"]): r["code"] for r in call.tx.q("SELECT id, code FROM items")}
    errors: dict[str, str] = {}
    for i, c in enumerate(cells):
        month = dt.date.fromisoformat(c.month + "-01")
        if (c.item_id, c.market_id) not in known:
            errors[f"lines.{i}"] = f"{codes.get(c.item_id, 'This product')} is not sold in this market. Add the market to the product first."
        elif c.due_date and (c.due_date < month or c.due_date > month_end(month)):
            errors[f"lines.{i}"] = "The due date must be in the same month."
    if errors:
        raise ApiError(422, "invalid", "Some rows need attention.", fields=errors)
    saved = removed = 0
    for c in cells:
        month = dt.date.fromisoformat(c.month + "-01")
        if not c.quantity:
            removed += call.tx.x("DELETE FROM demand_lines WHERE site_id = %s::uuid AND item_id = %s::uuid AND market_id = %s::uuid"
                                 " AND month = %s", sid, c.item_id, c.market_id, month) or 0
            continue
        call.tx.x("INSERT INTO demand_lines (tenant_id, site_id, item_id, market_id, month, quantity, due_date, notes)"
                  " VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s)"
                  " ON CONFLICT (site_id, item_id, market_id, month) DO UPDATE SET quantity = EXCLUDED.quantity,"
                  " due_date = EXCLUDED.due_date, notes = EXCLUDED.notes",
                  call.tenant_id, sid, c.item_id, c.market_id, month, c.quantity, c.due_date, (c.notes or "").strip() or None)
        saved += 1
    return {"saved": saved, "removed": removed}


@endpoint(auth="tenant_user", body=DemandIn)
def save_demand(call: Call):
    sid = call.path["site_id"]
    require_plan(call, sid, edit=True)
    return _save_demand(call, sid, call.body.lines)


# ================================================================== stock
STOCK_SQL = """
SELECT s.id, s.item_id, i.code, i.name_en, i.name_ar, i.type, u.code AS uom, s.lot_no, s.status, s.quantity,
       s.manufactured_on, s.expires_on, s.assay_pct, s.lod_pct, s.notes, s.updated_at
  FROM stock_lots s JOIN items i ON i.id = s.item_id JOIN uoms u ON u.id = i.stock_uom_id
"""


class StockFields(BaseModel):
    lot_no: str | None = Field(default=None, max_length=40)
    status: Literal["released", "quarantine", "rejected"] = "released"
    quantity: Decimal = Field(ge=0, le=Decimal("1e12"))
    manufactured_on: dt.date | None = None
    expires_on: dt.date | None = None
    assay_pct: Decimal | None = Field(default=None, gt=0, le=200)
    lod_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    notes: str | None = Field(default=None, max_length=300)

    @field_validator("lot_no", "notes", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else (v.strip() if isinstance(v, str) else v)


class StockIn(StockFields):
    item_id: str


def _check_stock(b: StockFields) -> None:
    if b.expires_on and b.manufactured_on and b.expires_on <= b.manufactured_on:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"expires_on": "Must be after the manufacturing date."})


def _dup(e: Exception):
    if getattr(e, "sqlstate", None) == "23505":
        raise ApiError(409, "duplicate", "Some fields need attention.",
                       fields={"lot_no": "This item already has this lot with this status. Edit that line instead."})
    raise e


@endpoint(auth="tenant_user")
def list_stock(call: Call):
    sid = call.path["site_id"]
    require_plan(call, sid)
    return {"as_of": call.tx.val("SELECT stock_as_of FROM sites WHERE id = %s::uuid", sid),
            "items": call.tx.q(STOCK_SQL + " WHERE s.site_id = %s::uuid ORDER BY CASE i.type WHEN 'finished' THEN 1"
                               " WHEN 'semi_finished' THEN 2 WHEN 'wip' THEN 3 WHEN 'raw_material' THEN 4 ELSE 5 END,"
                               " i.code, s.status, s.expires_on NULLS LAST, s.lot_no", sid)}


@endpoint(auth="tenant_user", body=StockIn)
def create_stock(call: Call):
    sid = call.path["site_id"]
    require_plan(call, sid, edit=True)
    b: StockIn = call.body
    _check_stock(b)
    if not call.tx.val("SELECT 1 FROM items WHERE id = %s::uuid", b.item_id):
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"item_id": "Choose an item."})
    try:
        row = call.tx.one("INSERT INTO stock_lots (tenant_id, site_id, item_id, lot_no, status, quantity, manufactured_on, expires_on,"
                          " assay_pct, lod_pct, notes) VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                          call.tenant_id, sid, b.item_id, b.lot_no, b.status, b.quantity, b.manufactured_on, b.expires_on,
                          b.assay_pct, b.lod_pct, b.notes)
    except Exception as e:
        _dup(e)
    return call.tx.one(STOCK_SQL + " WHERE s.id = %s", row["id"])


@endpoint(auth="tenant_user", body=StockFields)
def update_stock(call: Call):
    s = call.tx.one("SELECT id, site_id FROM stock_lots WHERE id = %s::uuid", call.path["stock_id"])
    if not s:
        raise not_found("Stock line")
    require_plan(call, s["site_id"], edit=True)
    b: StockFields = call.body
    _check_stock(b)
    try:
        call.tx.x("UPDATE stock_lots SET lot_no = %s, status = %s, quantity = %s, manufactured_on = %s, expires_on = %s,"
                  " assay_pct = %s, lod_pct = %s, notes = %s WHERE id = %s",
                  b.lot_no, b.status, b.quantity, b.manufactured_on, b.expires_on, b.assay_pct, b.lod_pct, b.notes, s["id"])
    except Exception as e:
        _dup(e)
    return call.tx.one(STOCK_SQL + " WHERE s.id = %s", s["id"])


@endpoint(auth="tenant_user")
def delete_stock(call: Call):
    s = call.tx.one("SELECT id, site_id FROM stock_lots WHERE id = %s::uuid", call.path["stock_id"])
    if not s:
        raise not_found("Stock line")
    require_plan(call, s["site_id"], edit=True)
    call.tx.x("DELETE FROM stock_lots WHERE id = %s", s["id"])
    return {"ok": True}


class StockDateIn(BaseModel):
    stock_as_of: dt.date | None


@endpoint(auth="tenant_user", body=StockDateIn)
def set_stock_date(call: Call):
    sid = call.path["site_id"]
    require_plan(call, sid, edit=True)
    call.tx.x("UPDATE sites SET stock_as_of = %s WHERE id = %s::uuid", call.body.stock_as_of, sid)
    return {"as_of": call.body.stock_as_of}


# ================================================================== net requirements
@endpoint(auth="tenant_user")
def requirements(call: Call):
    sid = call.path["site_id"]
    require_plan(call, sid)
    today = _today(call)
    q = call.query
    try:
        start = dt.date.fromisoformat(q["start"]) if q.get("start") else today
        end = dt.date.fromisoformat(q["end"]) if q.get("end") else start + dt.timedelta(days=29)
    except ValueError:
        raise ApiError(422, "invalid", "Use dates like 2026-11-04.")
    if end < start:
        raise ApiError(422, "invalid", "The end of the horizon must be on or after the start.")
    if (end - start).days > 400:
        raise ApiError(422, "invalid", "Choose a horizon of 13 months or less.")
    return net_requirements(call.tx, sid, start, end, _features(call), q.get("quarantine") == "1", today)


# ================================================================== Excel
DEMAND_COLUMNS = [("Product code", True), ("Market", True), ("Month (YYYY-MM)", True), ("Quantity", True),
                  ("Due date (YYYY-MM-DD)", False), ("Notes", False)]
STOCK_COLUMNS = [("Item code", True), ("Lot number", False), ("Status", True), ("Quantity", True),
                 ("Manufactured on", False), ("Expires on", False), ("Assay (%)", False), ("LOD (%)", False), ("Notes", False)]


def _template(entity: str) -> Response:
    wb = _wb()
    ws = wb.active
    cols = DEMAND_COLUMNS if entity == "demand" else STOCK_COLUMNS
    ws.title = "Sales plan" if entity == "demand" else "Stock"
    ws.append([h + (" *" if req else "") for h, req in cols])
    _style_header(ws)
    if entity == "demand":
        ws.append(["FG-EXAMPLE-EG", "LOCAL", "2026-12", 24000, "", ""])
        hints = ["Code of a finished product.", "Market code; the product must be sold in that market.",
                 "Month of the demand, for example 2026-12.", "Quantity in the product's stock unit. 0 removes the month.",
                 "Optional. A date in the same month when the order must ship; otherwise the end of the month.", "Optional."]
    else:
        ws.append(["RM-EXAMPLE", "L2611-004", "Released", 250, "2026-10-01", "2028-09-30", 99.6, 0.4, ""])
        hints = ["Code of any item.", "Optional, up to 40 characters.", "Released, Quarantine (waiting for QC) or Rejected.",
                 "Quantity in the item's stock unit.", "Optional date.", "Optional date.",
                 "Optional. Assay of the lot, used for assay compensation.", "Optional. Loss on drying of the lot.", "Optional."]
    _autosize(ws)
    guide = wb.create_sheet("How to fill")
    guide.append(["Column", "What to enter"])
    _style_header(guide)
    for (h, req), hint in zip(cols, hints):
        guide.append([h, ("Required. " if req else "") + hint])
    if entity == "stock":
        guide.append(["", ""])
        guide.append(["Note", "Importing replaces all stock lines of the site with the lines in the file."])
    guide.column_dimensions["A"].width = 26
    guide.column_dimensions["B"].width = 100
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="complanning-{entity}-template.xlsx"'})


def _date(raw) -> dt.date:
    if isinstance(raw, dt.datetime):
        return raw.date()
    if isinstance(raw, dt.date):
        return raw
    return dt.date.fromisoformat(str(raw).strip()[:10])


def _rows(call: Call, cols) -> tuple[list[tuple[int, dict]], list[dict]]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(_read_upload(call)), read_only=True, data_only=True)
    except Exception:
        raise ApiError(422, "bad_file", "This file could not be read. Save it as an Excel workbook (.xlsx) and try again.")
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    if not rows:
        raise ApiError(422, "empty", "The first sheet is empty.")
    headers = [str(h or "").replace("*", "").strip().lower() for h in rows[0]]
    index = {}
    for h, req in cols:
        if h.lower() in headers:
            index[h] = headers.index(h.lower())
        elif req:
            raise ApiError(422, "missing_column", f"The column “{h}” is missing. Start from the template.")
    out = []
    for n, row in enumerate(rows[1:], start=2):
        if row is None or all(_cell(v) is None for v in row):
            continue
        out.append((n, {h: (_cell(row[i]) if i < len(row) else None) for h, i in index.items()}))
    return out, []


def import_demand(call: Call, sid: str, commit: bool) -> dict:
    require_plan(call, sid, edit=True)
    rows, _ = _rows(call, DEMAND_COLUMNS)
    items = {r["code"].upper(): str(r["id"]) for r in call.tx.q("SELECT id, code FROM items WHERE type = 'finished'")}
    markets = {r["code"].upper(): str(r["id"]) for r in call.tx.q("SELECT id, code FROM markets")}
    known = {(str(r["item_id"]), str(r["market_id"])) for r in call.tx.q("SELECT item_id, market_id FROM item_markets")}
    existing = {(str(r["item_id"]), str(r["market_id"]), r["month"].strftime("%Y-%m"))
                for r in call.tx.q("SELECT item_id, market_id, month FROM demand_lines WHERE site_id = %s::uuid", sid)}
    cells, errors, seen = [], [], set()
    for n, r in rows:
        problems = []
        code = str(r.get("Product code") or "").strip().upper()
        mcode = str(r.get("Market") or "").strip().upper()
        iid, mid = items.get(code), markets.get(mcode)
        if not iid:
            problems.append(f"Unknown finished product {code or '(empty)'}.")
        if not mid:
            problems.append(f"Unknown market {mcode or '(empty)'}.")
        if iid and mid and (iid, mid) not in known:
            problems.append(f"{code} is not sold in market {mcode}.")
        month = due = qty = None
        try:
            raw = r.get("Month (YYYY-MM)")
            month = (_date(raw) if isinstance(raw, (dt.date, dt.datetime)) else dt.date.fromisoformat(str(raw).strip()[:7] + "-01")).replace(day=1)
        except (ValueError, TypeError):
            problems.append("Month: use a month like 2026-12.")
        try:
            qty = Decimal(str(r.get("Quantity")))
            if qty < 0:
                problems.append("Quantity: use 0 or more.")
        except Exception:
            problems.append("Quantity: not a number.")
        if r.get("Due date (YYYY-MM-DD)") is not None:
            try:
                due = _date(r["Due date (YYYY-MM-DD)"])
                if month and due.replace(day=1) != month:
                    problems.append("Due date: must be in the same month.")
            except (ValueError, TypeError):
                problems.append("Due date: use a date like 2026-12-15.")
        key = (iid, mid, month.strftime("%Y-%m") if month else None)
        if not problems and key in seen:
            problems.append("This product, market and month appear more than once in the file.")
        seen.add(key)
        if problems:
            errors.append({"row": n, "code": code or None, "problems": problems})
        else:
            cells.append(DemandCell(item_id=iid, market_id=mid, month=month.strftime("%Y-%m"), quantity=qty, due_date=due,
                                    notes=str(r.get("Notes"))[:300] if r.get("Notes") else None))
    summary = {"rows": len(cells) + len(errors), "create": sum(1 for c in cells if c.quantity and (c.item_id, c.market_id, c.month) not in existing),
               "update": sum(1 for c in cells if (c.item_id, c.market_id, c.month) in existing),
               "errors": errors[:200], "error_count": len(errors), "committed": False}
    if commit and not errors:
        _save_demand(call, sid, cells)
        call.tx.event("IMPORT", "demand_lines", None, "sales plan import", {"rows": len(cells)})
        summary["committed"] = True
    return summary


def import_stock(call: Call, sid: str, commit: bool) -> dict:
    require_plan(call, sid, edit=True)
    rows, _ = _rows(call, STOCK_COLUMNS)
    items = {r["code"].upper(): str(r["id"]) for r in call.tx.q("SELECT id, code FROM items")}
    current = call.tx.val("SELECT count(*) FROM stock_lots WHERE site_id = %s::uuid", sid)
    recs, errors, seen = [], [], set()
    for n, r in rows:
        problems, rec = [], {}
        code = str(r.get("Item code") or "").strip().upper()
        rec["item_id"] = items.get(code)
        if not rec["item_id"]:
            problems.append(f"Unknown item {code or '(empty)'}.")
        rec["lot_no"] = str(r["Lot number"]).strip()[:40] if r.get("Lot number") is not None else None
        st = str(r.get("Status") or "").strip().lower()
        rec["status"] = next((k for k, v in STATUS_NAMES.items() if st in (k, v.lower())), None)
        if not rec["status"]:
            problems.append("Status: use Released, Quarantine or Rejected.")
        try:
            rec["quantity"] = Decimal(str(r.get("Quantity")))
            if rec["quantity"] < 0:
                problems.append("Quantity: use 0 or more.")
        except Exception:
            problems.append("Quantity: not a number.")
        for h, f in (("Manufactured on", "manufactured_on"), ("Expires on", "expires_on")):
            rec[f] = None
            if r.get(h) is not None:
                try:
                    rec[f] = _date(r[h])
                except (ValueError, TypeError):
                    problems.append(f"{h}: use a date like 2027-06-30.")
        if rec.get("manufactured_on") and rec.get("expires_on") and rec["expires_on"] <= rec["manufactured_on"]:
            problems.append("Expires on: must be after the manufacturing date.")
        for h, f, lo, hi in (("Assay (%)", "assay_pct", 0, 200), ("LOD (%)", "lod_pct", -1, 99.999)):
            rec[f] = None
            if r.get(h) is not None:
                try:
                    v = Decimal(str(r[h]))
                    if not (lo < v <= hi):
                        raise ValueError
                    rec[f] = v
                except Exception:
                    problems.append(f"{h}: not a valid percentage.")
        rec["notes"] = str(r["Notes"])[:300] if r.get("Notes") is not None else None
        key = (rec["item_id"], rec["lot_no"] or "", rec["status"])
        if not problems and key in seen:
            problems.append("This item, lot and status appear more than once in the file.")
        seen.add(key)
        if problems:
            errors.append({"row": n, "code": code or None, "problems": problems})
        else:
            recs.append(rec)
    summary = {"rows": len(recs) + len(errors), "create": len(recs), "update": 0, "remove": current,
               "errors": errors[:200], "error_count": len(errors), "committed": False}
    if commit and not errors:
        call.tx.x("DELETE FROM stock_lots WHERE site_id = %s::uuid", sid)
        for rec in recs:
            call.tx.x("INSERT INTO stock_lots (tenant_id, site_id, item_id, lot_no, status, quantity, manufactured_on, expires_on,"
                      " assay_pct, lod_pct, notes) VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)",
                      call.tenant_id, sid, rec["item_id"], rec["lot_no"], rec["status"], rec["quantity"], rec["manufactured_on"],
                      rec["expires_on"], rec["assay_pct"], rec["lod_pct"], rec["notes"])
        call.tx.x("UPDATE sites SET stock_as_of = current_date WHERE id = %s::uuid", sid)
        call.tx.event("IMPORT", "stock_lots", None, "stock import", {"rows": len(recs), "replaced": current})
        summary["committed"] = True
    return summary


def export(call: Call, entity: str, sid: str) -> Response:
    site = require_plan(call, sid)
    wb = _wb()
    ws = wb.active
    if entity == "demand":
        ws.title = "Sales plan"
        ws.append([h for h, _ in DEMAND_COLUMNS] + ["Price today", "Currency", "Value"])
        today = _today(call)
        for r in call.tx.q("SELECT d.item_id, d.market_id, i.code, m.code AS market, d.month, d.quantity, d.due_date, d.notes"
                           "  FROM demand_lines d JOIN items i ON i.id = d.item_id JOIN markets m ON m.id = d.market_id"
                           " WHERE d.site_id = %s::uuid ORDER BY d.month, i.code, m.code", sid):
            p = price_on(call.tx, r["item_id"], r["market_id"], today)
            ws.append([r["code"], r["market"], r["month"].strftime("%Y-%m"), float(r["quantity"]), r["due_date"], r["notes"],
                       float(p["price"]) if p else None, p["currency"] if p else None,
                       float(p["price"] * r["quantity"]) if p else None])
    else:
        ws.title = "Stock"
        ws.append([h for h, _ in STOCK_COLUMNS])
        for r in call.tx.q(STOCK_SQL + " WHERE s.site_id = %s::uuid ORDER BY i.code, s.status, s.lot_no", sid):
            f = lambda v: float(v) if v is not None else None
            ws.append([r["code"], r["lot_no"], STATUS_NAMES[r["status"]], float(r["quantity"]), r["manufactured_on"], r["expires_on"],
                       f(r["assay_pct"]), f(r["lod_pct"]), r["notes"]])
    _style_header(ws)
    _autosize(ws)
    stamp = call.tx.val("SELECT to_char(now(), 'YYYYMMDD-HH24MI')")
    name = "sales-plan" if entity == "demand" else "stock"
    return _xlsx(wb, f"complanning-{name}-{site['code']}-{stamp}.xlsx", call, "demand_lines" if entity == "demand" else "stock_lots")
