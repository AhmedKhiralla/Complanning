"""Excel templates, import (items and machines) and full master-data export.

Import is all-or-nothing: the file is validated first and nothing is written if any row has a problem.
Rows are matched by code: an existing code is updated, a new code is created.
"""
from __future__ import annotations

import io
import json
from decimal import Decimal, InvalidOperation

import anyio.from_thread
from starlette.responses import Response

from ..api import ApiError, Call, endpoint
from ..perms import require_company_edit, require_site

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_IMPORT_BYTES = 5 * 1024 * 1024

TYPE_NAMES = {
    "raw_material": "Raw material", "packaging": "Packaging material", "wip": "Work in process",
    "semi_finished": "Semi-finished product", "finished": "Finished product",
}
RES_TYPES = {"machine": "Machine", "qc_lab": "QC laboratory", "room": "Room", "operator_group": "Operator group"}

# (header, field, kind, required)
ITEM_COLUMNS = [
    ("Code", "code", "code", True), ("Type", "type", "item_type", True),
    ("Name (English)", "name_en", "text", True), ("Name (Arabic)", "name_ar", "text", False),
    ("Stock unit", "stock_uom_id", "uom", True), ("Dispensing unit", "dispensing_uom_id", "uom", False),
    ("Density (kg/L)", "density_kg_per_l", "pos", False), ("Grade", "grade", "text", False),
    ("Description", "description", "text", False), ("Dosage form", "dosage_form", "text", False),
    ("Cleaning group", "cleaning_group", "text", False), ("Lead time (days)", "lead_time_days", "int", False),
    ("Minimum order qty", "moq", "num", False), ("Safety stock", "safety_stock", "num", False),
    ("QC release (days)", "qc_release_days", "num", False), ("Shelf life (months)", "shelf_life_months", "int", False),
    ("Pack size", "pack_size", "pos", False), ("Units per shipper", "units_per_shipper", "int", False),
    ("Standard cost", "standard_cost", "num", False), ("Test before sale (yes/no)", "test_before_sale", "bool", False),
    ("Release lead time (days)", "release_lead_days", "num", False), ("Active (yes/no)", "active", "bool", False),
]
MACHINE_COLUMNS = [
    ("Code", "code", "code", True), ("Name (English)", "name_en", "text", True), ("Name (Arabic)", "name_ar", "text", False),
    ("Type", "type", "res_type", False), ("Area", "area", "text", False), ("Location", "location", "text", False),
    ("Efficiency (%)", "efficiency_pct", "pct", False), ("Notes", "notes", "text", False),
    ("Active (yes/no)", "active", "bool", False),
]
ENTITIES = {"items": ITEM_COLUMNS, "machines": MACHINE_COLUMNS}


def _wb():
    from openpyxl import Workbook
    return Workbook()


def _style_header(ws, row: int = 1):
    from openpyxl.styles import Font, PatternFill
    for cell in ws[row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="67138C")
    ws.freeze_panes = ws.cell(row + 1, 1)


def _autosize(ws):
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 48)


def _xlsx(wb, filename: str, call: Call, what: str) -> Response:
    """Add who exported the data and when (21 CFR Part 11), then send the workbook."""
    info = wb.create_sheet("Export info")
    stamp = call.tx.one("SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || ' UTC' AS utc,"
                        " (SELECT name FROM tenants WHERE id = %s) AS company", call.tenant_id)
    for row in (("Exported by", f"{call.user['full_name']} <{call.user['email']}>"), ("Exported at", stamp["utc"]),
                ("Company", stamp["company"]), ("Content", what), ("Source", "Complanning by Comp11 Labs")):
        info.append(row)
    info.column_dimensions["A"].width = 16
    info.column_dimensions["B"].width = 60
    buf = io.BytesIO()
    wb.save(buf)
    call.tx.event("EXPORT", what, None, filename, {"format": "xlsx"})
    return Response(buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@endpoint(auth="tenant_user")
def template(call: Call):
    entity = call.query.get("entity", "items")
    if entity in ("demand", "stock"):
        from .demand import _template
        return _template(entity)
    cols = ENTITIES.get(entity)
    if not cols:
        raise ApiError(422, "invalid", "Unknown template.")
    wb = _wb()
    ws = wb.active
    ws.title = entity.capitalize()
    ws.append([h + (" *" if req else "") for h, _f, _k, req in cols])
    _style_header(ws)
    if entity == "items":
        ws.append(["RM-EXAMPLE", "Raw material", "Example excipient", "سواغ مثال", "KG", "", "", "Ph. Eur.", "", "", "", 45,
                   100, 50, 5, "", "", "", "", "no", "", "yes"])
    else:
        ws.append(["TP-03", "Rotary tablet press 3", "ماكينة كبس 3", "Machine", "Compression", "Hall B", 85, "", "yes"])
    _autosize(ws)
    guide = wb.create_sheet("How to fill")
    guide.append(["Column", "What to enter"])
    _style_header(guide)
    for h, _f, kind, req in cols:
        hint = {
            "code": "Unique code. Existing codes are updated; new codes are created.",
            "item_type": "One of: " + ", ".join(TYPE_NAMES.values()),
            "res_type": "One of: " + ", ".join(RES_TYPES.values()) + " (default Machine)",
            "uom": "A unit code from Master data → Units, for example KG, L, EA, TAB, BLS, CTN",
            "bool": "yes or no", "int": "Whole number", "num": "Number, 0 or more", "pos": "Number greater than 0",
            "pct": "Number from 1 to 100", "text": "Text",
        }[kind]
        guide.append([h, ("Required. " if req else "") + hint])
    guide.column_dimensions["A"].width = 30
    guide.column_dimensions["B"].width = 90
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="complanning-{entity}-template.xlsx"'})


def _cell(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _parse(kind: str, raw, uoms: dict) -> tuple[object, str | None]:
    """Return (value, error)."""
    if raw is None:
        return None, None
    try:
        if kind == "code":
            s = str(raw).strip().upper()
            import re
            if not re.match(r"^[A-Z0-9][A-Z0-9_./-]{0,39}$", s):
                return None, "Use letters, digits, dot, dash, slash or underscore."
            return s, None
        if kind == "text":
            return str(raw).strip()[:500], None
        if kind == "item_type":
            s = str(raw).strip().lower()
            for k, name in TYPE_NAMES.items():
                if s in (k, name.lower()):
                    return k, None
            return None, "Unknown type."
        if kind == "res_type":
            s = str(raw).strip().lower()
            for k, name in RES_TYPES.items():
                if s in (k, name.lower()):
                    return k, None
            return None, "Unknown type."
        if kind == "uom":
            s = str(raw).strip().upper()
            if s not in uoms:
                return None, f"Unknown unit {s}."
            return uoms[s], None
        if kind == "bool":
            s = str(raw).strip().lower()
            if s in ("yes", "y", "true", "1", "نعم"):
                return True, None
            if s in ("no", "n", "false", "0", "لا"):
                return False, None
            return None, "Use yes or no."
        if kind == "int":
            f = Decimal(str(raw))
            if f != f.to_integral_value() or f < 0:
                return None, "Use a whole number."
            return int(f), None
        d = Decimal(str(raw))
        if kind == "num" and d < 0:
            return None, "Use 0 or more."
        if kind == "pos" and d <= 0:
            return None, "Use a number greater than 0."
        if kind == "pct" and not (0 < d <= 100):
            return None, "Use a number from 1 to 100."
        return d, None
    except (InvalidOperation, ValueError):
        return None, "Not a number."


def _read_upload(call: Call) -> bytes:
    raw = anyio.from_thread.run(call.request.body)
    if not raw:
        raise ApiError(422, "no_file", "Choose an Excel file to import.")
    if len(raw) > MAX_IMPORT_BYTES:
        raise ApiError(413, "too_large", "The file is larger than 5 MB. Split it into smaller files.")
    return raw


@endpoint(auth="tenant_user")
def import_file(call: Call):
    entity = call.query.get("entity", "items")
    if entity in ("demand", "stock"):
        from .demand import import_demand, import_stock
        if not call.query.get("site_id"):
            raise ApiError(422, "invalid", "Choose the site to import into.")
        fn = import_demand if entity == "demand" else import_stock
        return fn(call, call.query["site_id"], call.query.get("commit") == "1")
    cols = ENTITIES.get(entity)
    if not cols:
        raise ApiError(422, "invalid", "Unknown import type.")
    site_id = call.query.get("site_id")
    if entity == "items":
        require_company_edit(call)
    else:
        if not site_id:
            raise ApiError(422, "invalid", "Choose the site to import machines into.")
        require_site(call, site_id, edit=True)
    commit = call.query.get("commit") == "1"
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(_read_upload(call)), read_only=True, data_only=True)
    except Exception:
        raise ApiError(422, "bad_file", "This file could not be read. Save it as an Excel workbook (.xlsx) and try again.")
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ApiError(422, "empty", "The first sheet is empty.")
    headers = [str(h or "").replace("*", "").strip().lower() for h in rows[0]]
    index = {}
    for h, field, kind, req in cols:
        if h.lower() in headers:
            index[field] = headers.index(h.lower())
        elif req:
            raise ApiError(422, "missing_column", f"The column “{h}” is missing. Start from the template.")
    uoms = {r["code"].upper(): str(r["id"]) for r in call.tx.q("SELECT id, code FROM uoms WHERE active")}
    if entity == "items":
        existing = {r["code"].upper(): r for r in call.tx.q("SELECT id, code, type, stock_uom_id FROM items")}
    else:
        existing = {r["code"].upper(): r for r in call.tx.q("SELECT id, code FROM resources WHERE site_id = %s::uuid", site_id)}

    parsed, errors, seen = [], [], set()
    for n, row in enumerate(rows[1:], start=2):
        if row is None or all(_cell(v) is None for v in row):
            continue
        rec, problems = {}, []
        for h, field, kind, req in cols:
            raw = _cell(row[index[field]]) if field in index and index[field] < len(row) else None
            if raw is None and req:
                problems.append(f"{h} is required.")
                continue
            val, err = _parse(kind, raw, uoms)
            if err:
                problems.append(f"{h}: {err}")
            elif field in index and raw is not None:
                rec[field] = val
        code = rec.get("code")
        if code:
            if code in seen:
                problems.append(f"Code {code} appears more than once in the file.")
            seen.add(code)
            ex = existing.get(code)
            if ex and entity == "items":
                if rec.get("type") and rec["type"] != ex["type"]:
                    problems.append("The type of an existing item cannot change.")
                if rec.get("stock_uom_id") and str(rec["stock_uom_id"]) != str(ex["stock_uom_id"]):
                    problems.append("The stock unit of an existing item cannot change by import.")
        if problems:
            errors.append({"row": n, "code": code, "problems": problems})
        else:
            parsed.append(rec)

    summary = {
        "rows": len(parsed) + len(errors),
        "create": sum(1 for r in parsed if r["code"] not in existing),
        "update": sum(1 for r in parsed if r["code"] in existing),
        "errors": errors[:200], "error_count": len(errors), "committed": False,
    }
    if not commit or errors:
        return summary

    for rec in parsed:
        ex = existing.get(rec["code"])
        if entity == "items":
            if ex:
                fields = [f for f in rec if f not in ("code", "type", "stock_uom_id")]
                if fields:
                    call.tx.x(f"UPDATE items SET {', '.join(f + ' = %s' for f in fields)} WHERE id = %s",
                              *[rec[f] for f in fields], ex["id"])
            else:
                fields = list(rec)
                call.tx.x(f"INSERT INTO items (tenant_id, {', '.join(fields)}) VALUES (%s, {', '.join(['%s'] * len(fields))})",
                          call.tenant_id, *[rec[f] for f in fields])
        else:
            if ex:
                fields = [f for f in rec if f != "code"]
                if fields:
                    call.tx.x(f"UPDATE resources SET {', '.join(f + ' = %s' for f in fields)} WHERE id = %s",
                              *[rec[f] for f in fields], ex["id"])
            else:
                fields = list(rec)
                call.tx.x(f"INSERT INTO resources (tenant_id, site_id, {', '.join(fields)}) VALUES (%s, %s::uuid, {', '.join(['%s'] * len(fields))})",
                          call.tenant_id, site_id, *[rec[f] for f in fields])
    call.tx.event("IMPORT", "items" if entity == "items" else "resources", None, f"{entity} import",
                  {"rows": len(parsed), "created": summary["create"], "updated": summary["update"]})
    summary["committed"] = True
    return summary


@endpoint(auth="tenant_user")
def export_master(call: Call):
    """All company master data in one workbook; site sheets for the chosen site."""
    site_id = call.query.get("site_id")
    if call.query.get("entity") in ("demand", "stock"):
        if not site_id:
            raise ApiError(422, "invalid", "Choose the site to export.")
        from .demand import export
        return export(call, call.query["entity"], site_id)
    site = require_site(call, site_id) if site_id else None
    wb = _wb()
    ws = wb.active
    ws.title = "Items"
    ws.append([h for h, *_ in ITEM_COLUMNS])
    uom_code = {str(r["id"]): r["code"] for r in call.tx.q("SELECT id, code FROM uoms")}
    for it in call.tx.q("SELECT * FROM items ORDER BY code"):
        row = []
        for _h, f, kind, _r in ITEM_COLUMNS:
            v = it.get(f)
            if kind == "uom":
                v = uom_code.get(str(v)) if v else None
            elif kind == "item_type":
                v = TYPE_NAMES[v]
            elif kind == "bool":
                v = "yes" if v else "no"
            elif isinstance(v, Decimal):
                v = float(v)
            row.append(v)
        ws.append(row)
    _style_header(ws); _autosize(ws)

    ws = wb.create_sheet("Units")
    ws.append(["Code", "Name (English)", "Name (Arabic)", "Dimension", "Size in base unit", "Standard", "Active"])
    for u in call.tx.q("SELECT * FROM uoms ORDER BY dimension, code"):
        ws.append([u["code"], u["name_en"], u["name_ar"], u["dimension"], float(u["factor_to_base"]),
                   "yes" if u["is_system"] else "no", "yes" if u["active"] else "no"])
    _style_header(ws); _autosize(ws)

    ws = wb.create_sheet("Pack conversions")
    ws.append(["Item", "1 of this unit", "equals", "Stock unit"])
    for c in call.tx.q("SELECT i.code, u.code AS uom, c.factor, su.code AS stock FROM item_uom_conversions c"
                       " JOIN items i ON i.id = c.item_id JOIN uoms u ON u.id = c.uom_id JOIN uoms su ON su.id = i.stock_uom_id ORDER BY i.code"):
        ws.append([c["code"], c["uom"], float(c["factor"]), c["stock"]])
    _style_header(ws); _autosize(ws)

    ws = wb.create_sheet("Markets and prices")
    ws.append(["Item", "Market", "Price", "Currency", "Valid from", "Valid to"])
    for p in call.tx.q("SELECT i.code, m.code AS market, p.price, p.currency, p.valid_from, p.valid_to FROM prices p"
                       " JOIN items i ON i.id = p.item_id JOIN markets m ON m.id = p.market_id ORDER BY i.code, m.code, p.valid_from"):
        ws.append([p["code"], p["market"], float(p["price"]), p["currency"], p["valid_from"], p["valid_to"]])
    _style_header(ws); _autosize(ws)

    ws = wb.create_sheet("Bills of materials")
    ws.append(["Item", "Version", "Status", "Batch size", "Batch unit", "Yield (%)", "Line", "Component", "Quantity", "Unit",
               "Assay-compensated", "Overage (%)", "Compensating"])
    for r in call.tx.q(
            "SELECT i.code, b.version, b.status, b.batch_size, bu.code AS bu, b.yield_pct, l.line_no, c.code AS comp, l.quantity,"
            " lu.code AS lu, l.assay_compensated, l.overage_pct, l.is_compensating FROM boms b JOIN items i ON i.id = b.item_id"
            " JOIN uoms bu ON bu.id = b.batch_uom_id LEFT JOIN bom_lines l ON l.bom_id = b.id LEFT JOIN items c ON c.id = l.component_item_id"
            " LEFT JOIN uoms lu ON lu.id = l.uom_id WHERE b.status <> 'archived' ORDER BY i.code, b.version, l.line_no"):
        ws.append([r["code"], r["version"], r["status"], float(r["batch_size"]), r["bu"], float(r["yield_pct"]), r["line_no"],
                   r["comp"], float(r["quantity"]) if r["quantity"] is not None else None, r["lu"],
                   "yes" if r["assay_compensated"] else "no", float(r["overage_pct"] or 0), "yes" if r["is_compensating"] else "no"])
    _style_header(ws); _autosize(ws)

    if site:
        ws = wb.create_sheet("Machines")
        ws.append([h for h, *_ in MACHINE_COLUMNS])
        for r in call.tx.q("SELECT * FROM resources WHERE site_id = %s ORDER BY code", site["id"]):
            ws.append([r["code"], r["name_en"], r["name_ar"], RES_TYPES[r["type"]], r["area"], r["location"],
                       float(r["efficiency_pct"]), r["notes"], "yes" if r["active"] else "no"])
        _style_header(ws); _autosize(ws)

        ws = wb.create_sheet("Routings")
        ws.append(["Item", "Step", "Name", "Time model", "Minutes per batch", "Output per hour", "Setup (min)",
                   "Machine", "Preferred", "Own minutes", "Own output per hour"])
        for r in call.tx.q(
                "SELECT i.code, s.seq, s.name, s.time_model, s.fixed_minutes, s.rate_per_hour, s.setup_minutes, m.code AS machine,"
                " sr.preferred, sr.fixed_minutes AS own_min, sr.rate_per_hour AS own_rate FROM routings rt JOIN items i ON i.id = rt.item_id"
                " JOIN routing_steps s ON s.routing_id = rt.id JOIN routing_step_resources sr ON sr.step_id = s.id"
                " JOIN resources m ON m.id = sr.resource_id WHERE rt.site_id = %s ORDER BY i.code, s.seq, sr.preferred DESC", site["id"]):
            f = lambda v: float(v) if v is not None else None
            ws.append([r["code"], r["seq"], r["name"], r["time_model"], f(r["fixed_minutes"]), f(r["rate_per_hour"]),
                       f(r["setup_minutes"]), r["machine"], "yes" if r["preferred"] else "no", f(r["own_min"]), f(r["own_rate"])])
        _style_header(ws); _autosize(ws)
    stamp = call.tx.val("SELECT to_char(now(), 'YYYYMMDD-HH24MI')")
    return _xlsx(wb, f"complanning-master-data-{stamp}.xlsx", call, "master_data")
