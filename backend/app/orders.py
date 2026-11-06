"""Production orders: numbering, the content of one order (header and material lines) and its template defaults.

An order is built for one batch of a plan and one template (manufacturing or packaging). The template decides
the title, the header fields and their labels, the material table columns and their labels, which component
types are listed, the signature levels, the remarks area and the footer. Draft orders are built from the plan
each time they are shown; approved and issued orders keep the content they had at that moment.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

from .api import ApiError
from .defaults import effective_features
from .netting import line_needs, potency_factors
from .units import UnitBook

# ------------------------------------------------------------------ template vocabulary
HEADER_FIELDS = {
    "product_name": "Product Name", "product_code": "Product Code", "batch_number": "Batch No.",
    "batch_size": "Batch size", "date_issued": "Date Issued", "order_number": "Order Number",
    "mfg_date": "MFG date", "exp_date": "EXP Date", "shelf_life": "Shelf life", "bom_version": "BOM version",
    "planned_start": "Planned start", "planned_end": "Planned end", "plan": "Plan", "site": "Site",
}
COLUMNS = {
    "ser": "Ser. No.", "name": "Item Name", "code": "Item code", "qty_required": "Req. quantity",
    "qty_issued": "Issued quantity", "uom": "U/M", "lot": "Lot No.", "qc": "QC No.", "assay": "Assay / potency",
    "remarks": "Remarks", "dispensed_by": "Dispensed by", "checked_by": "Checked by",
}
ITEM_TYPES = ("raw_material", "packaging", "wip", "semi_finished", "finished")

DEFAULTS = {
    "packaging": {
        "name": "Packaging order", "title": "Packaging Order", "format_number": "PL001-01/F02",
        "number_pattern": "{YY}-{MM}-{BATCH}P", "component_types": ["packaging"],
        "header_fields": ["product_name", "batch_number", "date_issued", "product_code", "batch_size", "order_number",
                          "shelf_life", "mfg_date", "exp_date"],
        "columns": ["ser", "name", "code", "qty_required", "qty_issued", "uom", "lot", "qc"],
        "signatures": ["Planning", "Production", "Quality Assurance", "Material Delivered By", "Material Received By"],
    },
    "manufacturing": {
        "name": "Manufacturing order", "title": "Manufacturing Order", "format_number": "PL001-01/F01",
        "number_pattern": "{YY}-{MM}-{BATCH}M", "component_types": ["raw_material"],
        "header_fields": ["product_name", "batch_number", "date_issued", "product_code", "batch_size", "order_number",
                          "shelf_life", "mfg_date", "exp_date"],
        "columns": ["ser", "name", "code", "qty_required", "qty_issued", "uom", "lot", "qc"],
        "signatures": ["Planning", "Production", "Quality Assurance", "Material Delivered By", "Material Received By"],
    },
}


def default_template(kind: str) -> dict:
    d = DEFAULTS[kind]
    return {"kind": kind, "name": d["name"], "title": d["title"], "format_number": d["format_number"],
            "number_pattern": d["number_pattern"], "orientation": "landscape", "logo": None, "header_columns": 3,
            "header_fields": [{"key": k, "label": HEADER_FIELDS[k]} for k in d["header_fields"]],
            "columns": [{"key": k, "label": COLUMNS[k]} for k in d["columns"]],
            "component_types": d["component_types"], "signatures": [{"title": s} for s in d["signatures"]],
            "require_esign": False, "remarks_label": "Remarks", "remarks_lines": 2, "footer_note": None}


# ------------------------------------------------------------------ numbering
TOKEN = re.compile(r"\{([A-Z]+)(?::(\d+))?\}")


def expand(pattern: str, when: dt.date, *, batch: str = "", code: str = "", seq: int | None = None) -> str:
    """{YY} {YYYY} {MM} {DD} {BATCH} {CODE} {SEQ} {SEQ:4} -> text. Unknown tokens are left as typed."""
    def one(m: re.Match) -> str:
        tok, width = m.group(1), m.group(2)
        if tok == "YY":
            return f"{when.year % 100:02d}"
        if tok == "YYYY":
            return f"{when.year:04d}"
        if tok == "MM":
            return f"{when.month:02d}"
        if tok == "DD":
            return f"{when.day:02d}"
        if tok == "BATCH":
            return batch
        if tok == "CODE":
            return code
        if tok == "SEQ" and seq is not None:
            return str(seq).zfill(int(width or 1))
        return m.group(0)
    return TOKEN.sub(one, pattern).strip()


def uses_seq(pattern: str | None) -> bool:
    return bool(pattern) and any(m.group(1) == "SEQ" for m in TOKEN.finditer(pattern))


def batch_key(item_id, ordinal) -> str:
    return f"{item_id}:{ordinal}"


# ------------------------------------------------------------------ content
def _num(v: Decimal | float, places: int = 3) -> str:
    q = Decimal(str(v)).quantize(Decimal(1).scaleb(-places))
    s = f"{q:,.{places}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _date(d: dt.date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _month(d: dt.date | None) -> str:
    return d.strftime("%m/%Y") if d else ""


def _shelf(months: int | None) -> str:
    if not months:
        return ""
    if months % 12 == 0:
        y = months // 12
        return f"{y} year" + ("s" if y != 1 else "")
    return f"{months} months"


def build_content(tx, order: dict, template: dict, plan: dict | None, site: dict, batch: dict | None, issued_on: dt.date) -> dict:
    """Everything printed on one order. `batch` is the plan batch (None when the plan or batch no longer exists:
    the order then keeps what it had)."""
    tz = ZoneInfo(site.get("timezone") or "UTC")
    item = tx.one("SELECT i.id, i.code, i.name_en, i.name_ar, i.shelf_life_months, u.code AS uom FROM items i"
                  " JOIN uoms u ON u.id = i.stock_uom_id WHERE i.id = %s::uuid", str(order["item_id"]))
    lines: list[dict] = []
    values: dict[str, str] = {}
    if batch:
        start = batch["start_at"].astimezone(tz).date() if batch["start_at"] else None
        end = batch["end_at"].astimezone(tz).date() if batch["end_at"] else None
        exp = batch["expires_on"]
        values.update({
            "batch_size": f"{_num(batch['quantity'])} {item['uom']}", "mfg_date": _month(start), "exp_date": _month(exp),
            "bom_version": f"v{batch['bom_version']}" if batch["bom_version"] else "",
            "planned_start": batch["start_at"].astimezone(tz).strftime("%d/%m/%Y %H:%M") if batch["start_at"] else "",
            "planned_end": batch["end_at"].astimezone(tz).strftime("%d/%m/%Y %H:%M") if batch["end_at"] else "",
        })
        lines = material_lines(tx, site, plan, batch, template["component_types"])
        del end
    values.update({
        "product_name": item["name_en"], "product_code": item["code"], "batch_number": order["batch_number"],
        "date_issued": _date(issued_on), "order_number": order["number"], "shelf_life": _shelf(item["shelf_life_months"]),
        "plan": plan["name"] if plan else "", "site": f"{site['code']} · {site['name']}",
    })
    return {
        "template": {k: template[k] for k in ("kind", "title", "format_number", "orientation", "logo", "header_columns",
                                              "header_fields", "columns", "signatures", "remarks_label", "remarks_lines",
                                              "footer_note", "require_esign")},
        "number": order["number"], "batch_number": order["batch_number"], "values": values, "lines": lines,
        "issued_on": issued_on.isoformat(),
    }


def material_lines(tx, site: dict, plan: dict | None, batch: dict, types: list[str]) -> list[dict]:
    """Bill-of-materials lines of the batch's BOM version, scaled to its quantity, for the listed component types."""
    bom = tx.one("SELECT * FROM boms WHERE item_id = %s AND version = %s", batch["item_id"], batch["bom_version"]) \
        if batch["bom_version"] else None
    if not bom:
        return []
    feats = effective_features(tx.val("SELECT features FROM tenants WHERE id = %s", bom["tenant_id"]))
    book = UnitBook(tx)
    nominal = book.to_stock(str(bom["item_id"]), Decimal(bom["batch_size"]), str(bom["batch_uom_id"]))
    expected = nominal * Decimal(bom["yield_pct"]) / Decimal(100)
    lines = tx.q("SELECT l.* FROM bom_lines l WHERE l.bom_id = %s ORDER BY l.line_no", bom["id"])
    opts = (plan or {}).get("options") or {}
    factors = potency_factors(tx, str(site["id"]), bool(opts.get("include_quarantine")), dt.date.today(),
                              feats.get("assay_compensation", True))
    needs, _probs = line_needs(book, lines, Decimal(str(batch["quantity"])) / expected, feats, factors)
    comps = {str(r["id"]): r for r in tx.q(
        "SELECT i.id, i.code, i.name_en, i.type, u.code AS uom FROM items i JOIN uoms u ON u.id = i.stock_uom_id"
        " WHERE i.id = ANY(string_to_array(%s, ',')::uuid[])", ",".join(str(l["component_item_id"]) for l in lines))}
    out = []
    for l, need in needs:
        c = comps[str(l["component_item_id"])]
        if c["type"] not in types:
            continue
        f = factors.get(str(l["component_item_id"])) if l["assay_compensated"] else None
        out.append({"name": c["name_en"], "code": c["code"], "qty_required": _num(need), "uom": c["uom"],
                    "assay": f"× {_num(f, 4)}" if f else ""})
    for i, r in enumerate(out, start=1):
        r["ser"] = str(i)
    return out


def has_components(tx, batch: dict, types: list[str]) -> bool:
    if not batch["bom_version"]:
        return False
    return bool(tx.val(
        "SELECT 1 FROM bom_lines l JOIN boms b ON b.id = l.bom_id JOIN items c ON c.id = l.component_item_id"
        " WHERE b.item_id = %s AND b.version = %s AND c.type = ANY(string_to_array(%s, ',')) LIMIT 1",
        batch["item_id"], batch["bom_version"], ",".join(types)))


def check_template(t: dict) -> dict[str, str]:
    errors = {}
    for i, f in enumerate(t["header_fields"]):
        if f["key"] not in HEADER_FIELDS:
            errors[f"header_fields.{i}"] = "Unknown field."
    for i, c in enumerate(t["columns"]):
        if c["key"] not in COLUMNS:
            errors[f"columns.{i}"] = "Unknown column."
    if not t["columns"]:
        errors["columns"] = "Keep at least one column."
    if any(x not in ITEM_TYPES for x in t["component_types"]) or not t["component_types"]:
        errors["component_types"] = "Choose at least one type of material to list."
    if "{BATCH}" not in t["number_pattern"] and not uses_seq(t["number_pattern"]):
        errors["number_pattern"] = "Include {BATCH} or {SEQ} so every order gets its own number."
    if t.get("logo") and not re.match(r"^data:image/(png|jpeg);base64,", t["logo"]):
        errors["logo"] = "Use a PNG or JPEG image."
    return errors


def tz_today(site: dict) -> dt.date:
    return dt.datetime.now(ZoneInfo(site.get("timezone") or "UTC")).date()


def ensure_templates(tx, tenant_id) -> None:
    """Every company starts with one default template of each kind, which it can then change."""
    import json
    for kind in ("packaging", "manufacturing"):
        if tx.val("SELECT 1 FROM order_templates WHERE tenant_id = %s AND kind = %s LIMIT 1", tenant_id, kind):
            continue
        d = default_template(kind)
        tx.x("INSERT INTO order_templates (tenant_id, kind, name, title, format_number, number_pattern, orientation,"
             " header_columns, header_fields, columns, component_types, signatures, require_esign, remarks_label,"
             " remarks_lines, is_default) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,"
             " %s, %s, %s, true)", tenant_id, kind, d["name"], d["title"], d["format_number"], d["number_pattern"],
             d["orientation"], d["header_columns"], json.dumps(d["header_fields"]), json.dumps(d["columns"]),
             json.dumps(d["component_types"]), json.dumps(d["signatures"]), d["require_esign"], d["remarks_label"],
             d["remarks_lines"])


def not_found_order() -> ApiError:
    return ApiError(404, "not_found", "Order was not found.")
