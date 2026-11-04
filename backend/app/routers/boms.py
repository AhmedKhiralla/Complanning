"""Bills of materials: versions, lines, activation and multi-level explosion."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ..defaults import effective_features
from ..api import ApiError, Call, endpoint, not_found
from ..perms import require_company_edit
from ..units import UnitBook

PRODUCIBLE = ("wip", "semi_finished", "finished")

HEADER_SQL = """
SELECT b.id, b.item_id, b.version, b.status, b.valid_from, b.valid_to, b.batch_size, b.batch_uom_id,
       u.code AS batch_uom, b.yield_pct, b.batch_mode, b.min_batch_pct, b.notes, b.updated_at,
       i.code AS item_code, i.name_en AS item_name_en, i.name_ar AS item_name_ar, i.type AS item_type,
       i.stock_uom_id AS item_stock_uom_id
  FROM boms b JOIN items i ON i.id = b.item_id JOIN uoms u ON u.id = b.batch_uom_id
"""

LINES_SQL = """
SELECT l.id, l.line_no, l.component_item_id, c.code AS component_code, c.name_en AS component_name_en,
       c.name_ar AS component_name_ar, c.type AS component_type, l.quantity, l.uom_id, u.code AS uom,
       l.assay_compensated, l.overage_pct, l.is_compensating, l.notes, c.assay_basis AS component_assay_basis,
       (SELECT b2.version FROM boms b2 WHERE b2.item_id = c.id AND b2.status = 'active') AS component_active_bom
  FROM bom_lines l JOIN items c ON c.id = l.component_item_id JOIN uoms u ON u.id = l.uom_id
 WHERE l.bom_id = %s ORDER BY l.line_no
"""


def _bom(call: Call, bom_id) -> dict:
    b = call.tx.one(HEADER_SQL + " WHERE b.id = %s::uuid", str(bom_id))
    if not b:
        raise not_found("Bill of materials")
    b["lines"] = call.tx.q(LINES_SQL, b["id"])
    return b


@endpoint(auth="tenant_user")
def list_boms(call: Call):
    """Producible items with their BOM versions."""
    items = call.tx.q(
        "SELECT i.id, i.code, i.name_en, i.name_ar, i.type, i.active,"
        "  coalesce((SELECT json_agg(json_build_object('id', b.id, 'version', b.version, 'status', b.status,"
        "     'valid_from', b.valid_from, 'batch_size', b.batch_size, 'batch_uom', u.code,"
        "     'lines', (SELECT count(*) FROM bom_lines l WHERE l.bom_id = b.id)) ORDER BY b.version DESC)"
        "     FROM boms b JOIN uoms u ON u.id = b.batch_uom_id WHERE b.item_id = i.id), '[]'::json) AS versions"
        "  FROM items i WHERE i.type IN ('wip', 'semi_finished', 'finished') ORDER BY"
        "  CASE i.type WHEN 'finished' THEN 1 WHEN 'semi_finished' THEN 2 ELSE 3 END, i.code")
    return {"items": items}


@endpoint(auth="tenant_user")
def get_bom(call: Call):
    return _bom(call, call.path["bom_id"])


class BomHeader(BaseModel):
    batch_size: Decimal | None = Field(default=None, gt=0)
    batch_uom_id: str | None = None
    yield_pct: Decimal | None = Field(default=None, gt=0, le=100)
    batch_mode: Literal["fixed", "partial"] | None = None
    min_batch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    notes: str | None = Field(default=None, max_length=1000)


class BomCreate(BomHeader):
    batch_size: Decimal = Field(gt=0)
    batch_uom_id: str
    copy_from: str | None = None


def _check_batch_uom(call: Call, item_id: str, uom_id: str) -> None:
    book = UnitBook(call.tx)
    try:
        book.to_stock(item_id, Decimal(1), uom_id)
    except ApiError as e:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"batch_uom_id": e.message})


@endpoint(auth="tenant_user", body=BomCreate)
def create_bom(call: Call):
    require_company_edit(call)
    iid = call.path["item_id"]
    item = call.tx.one("SELECT id, type FROM items WHERE id = %s::uuid", iid)
    if not item:
        raise not_found("Item")
    if item["type"] not in PRODUCIBLE:
        raise ApiError(422, "not_producible", "Only work-in-process, semi-finished and finished items have bills of materials.")
    b: BomCreate = call.body
    _check_batch_uom(call, iid, b.batch_uom_id)
    if call.tx.val("SELECT 1 FROM boms WHERE item_id = %s::uuid AND status = 'draft'", iid):
        raise ApiError(409, "draft_exists", "This item already has a draft version. Finish or discard it first.")
    version = (call.tx.val("SELECT max(version) FROM boms WHERE item_id = %s::uuid", iid) or 0) + 1
    row = call.tx.one(
        "INSERT INTO boms (tenant_id, item_id, version, batch_size, batch_uom_id, yield_pct, batch_mode, min_batch_pct, notes)"
        " VALUES (%s, %s::uuid, %s, %s, %s::uuid, %s, %s, %s, %s) RETURNING id",
        call.tenant_id, iid, version, b.batch_size, b.batch_uom_id, b.yield_pct or Decimal(100),
        b.batch_mode or "fixed", b.min_batch_pct if (b.batch_mode == "partial") else None, b.notes)
    source = b.copy_from or call.tx.val("SELECT id FROM boms WHERE item_id = %s::uuid AND status = 'active'", iid)
    if source:
        call.tx.x(
            "INSERT INTO bom_lines (tenant_id, bom_id, line_no, component_item_id, quantity, uom_id, assay_compensated,"
            " overage_pct, is_compensating, notes)"
            " SELECT tenant_id, %s, line_no, component_item_id, quantity, uom_id, assay_compensated, overage_pct,"
            " is_compensating, notes FROM bom_lines WHERE bom_id = %s::uuid ORDER BY line_no", row["id"], str(source))
    return _bom(call, row["id"])


def _draft(call: Call, bom_id: str) -> dict:
    b = call.tx.one("SELECT id, item_id, status FROM boms WHERE id = %s::uuid", bom_id)
    if not b:
        raise not_found("Bill of materials")
    if b["status"] != "draft":
        raise ApiError(422, "not_draft", "Only draft versions can be edited. Create a new version to make changes.")
    return b


@endpoint(auth="tenant_user", body=BomHeader)
def update_bom(call: Call):
    require_company_edit(call)
    bid = call.path["bom_id"]
    b = _draft(call, bid)
    body: BomHeader = call.body
    if body.batch_uom_id:
        _check_batch_uom(call, str(b["item_id"]), body.batch_uom_id)
    from .master import patch_row
    patch_row(call, "boms", bid, body, ("batch_size", "batch_uom_id", "yield_pct", "batch_mode", "min_batch_pct", "notes"))
    if body.batch_mode == "fixed":
        call.tx.x("UPDATE boms SET min_batch_pct = NULL WHERE id = %s::uuid", bid)
    return _bom(call, bid)


class LineIn(BaseModel):
    id: str | None = None
    component_item_id: str
    quantity: Decimal = Field(gt=0)
    uom_id: str
    assay_compensated: bool = False
    overage_pct: Decimal = Field(default=Decimal(0), ge=0, le=100)
    is_compensating: bool = False
    notes: str | None = Field(default=None, max_length=300)


class LinesIn(BaseModel):
    lines: list[LineIn]


def _reaches(call: Call, start_item: str, target_item: str) -> bool:
    """True if target_item appears anywhere below start_item in draft or active BOMs."""
    return bool(call.tx.val(
        """WITH RECURSIVE tree(item_id) AS (
             SELECT %s::uuid
             UNION
             SELECT l.component_item_id FROM tree t
               JOIN boms b ON b.item_id = t.item_id AND b.status IN ('draft', 'active')
               JOIN bom_lines l ON l.bom_id = b.id)
           SELECT 1 FROM tree WHERE item_id = %s::uuid LIMIT 1""", start_item, target_item))


@endpoint(auth="tenant_user", body=LinesIn)
def set_lines(call: Call):
    require_company_edit(call)
    bid = call.path["bom_id"]
    bom = _draft(call, bid)
    parent = str(bom["item_id"])
    lines = call.body.lines
    book = UnitBook(call.tx)
    errors: dict[str, str] = {}
    comps = [l for l in lines if l.is_compensating]
    if len(comps) > 1:
        errors["lines"] = "Only one line can be the compensating material."
    seen = set()
    for i, l in enumerate(lines):
        key = f"lines.{i}"
        if l.component_item_id == parent:
            errors[key] = "An item cannot be a component of itself."
            continue
        if l.component_item_id in seen:
            errors[key] = "This component is already in the list. Combine the quantities on one line."
            continue
        seen.add(l.component_item_id)
        if l.is_compensating and l.assay_compensated:
            errors[key] = "The compensating material cannot also be assay-compensated."
            continue
        try:
            book.to_stock(l.component_item_id, l.quantity, l.uom_id)
        except ApiError as e:
            errors[key] = e.message
            continue
        if _reaches(call, l.component_item_id, parent):
            errors[key] = "This would create a loop: the component already uses this item."
    if errors:
        raise ApiError(422, "invalid", "Some lines need attention.", fields=errors)

    current = {str(r["id"]): r for r in call.tx.q("SELECT id FROM bom_lines WHERE bom_id = %s::uuid", bid)}
    keep = {l.id for l in lines if l.id and l.id in current}
    for lid in current:
        if lid not in keep:
            call.tx.x("DELETE FROM bom_lines WHERE id = %s::uuid", lid)
    for n, l in enumerate(lines, start=1):
        vals = (n, l.component_item_id, l.quantity, l.uom_id, l.assay_compensated, l.overage_pct,
                l.is_compensating, (l.notes or "").strip() or None)
        if l.id and l.id in current:
            call.tx.x("UPDATE bom_lines SET line_no = %s, component_item_id = %s::uuid, quantity = %s, uom_id = %s::uuid,"
                      " assay_compensated = %s, overage_pct = %s, is_compensating = %s, notes = %s WHERE id = %s::uuid",
                      *vals, l.id)
        else:
            call.tx.x("INSERT INTO bom_lines (tenant_id, bom_id, line_no, component_item_id, quantity, uom_id,"
                      " assay_compensated, overage_pct, is_compensating, notes)"
                      " VALUES (%s, %s::uuid, %s, %s::uuid, %s, %s::uuid, %s, %s, %s, %s)", call.tenant_id, bid, *vals)
    return _bom(call, bid)


class ActivateIn(BaseModel):
    valid_from: dt.date | None = None


@endpoint(auth="tenant_user", body=ActivateIn)
def activate_bom(call: Call):
    require_company_edit(call)
    bid = call.path["bom_id"]
    bom = _draft(call, bid)
    if not call.tx.val("SELECT count(*) FROM bom_lines WHERE bom_id = %s::uuid", bid):
        raise ApiError(422, "no_lines", "Add at least one component before activating this version.")
    start = call.body.valid_from or call.tx.val("SELECT current_date")
    prev = call.tx.one("SELECT id, valid_from FROM boms WHERE item_id = %s AND status = 'active'", bom["item_id"])
    if prev:
        if prev["valid_from"] and start <= prev["valid_from"]:
            raise ApiError(422, "invalid", "Some fields need attention.",
                           fields={"valid_from": f"Must be after the current version's start ({prev['valid_from'].isoformat()})."})
        call.tx.x("UPDATE boms SET status = 'archived', valid_to = %s WHERE id = %s", start - dt.timedelta(days=1), prev["id"])
    call.tx.x("UPDATE boms SET status = 'active', valid_from = %s WHERE id = %s::uuid", start, bid)
    return _bom(call, bid)


@endpoint(auth="tenant_user")
def discard_bom(call: Call):
    require_company_edit(call)
    bid = call.path["bom_id"]
    _draft(call, bid)
    call.tx.x("DELETE FROM bom_lines WHERE bom_id = %s::uuid", bid)
    call.tx.x("DELETE FROM boms WHERE id = %s::uuid", bid)
    return {"ok": True}


# ------------------------------------------------------------------ explosion
def _overage_on(call: Call) -> bool:
    if "_overage_on" not in call.__dict__:
        feats = effective_features(call.tx.val("SELECT features FROM tenants WHERE id = %s", call.tenant_id))
        call.__dict__["_overage_on"] = feats.get("overage", True)
    return call.__dict__["_overage_on"]


def _explode(call: Call, book: UnitBook, bom: dict, qty_stock: Decimal, depth: int, path: tuple) -> list[dict]:
    """Components needed to produce qty_stock (in the parent's stock unit) of bom's item."""
    item = book.item(str(bom["item_id"]))
    batch_out = book.to_stock(str(item["id"]), Decimal(bom["batch_size"]), str(bom["batch_uom_id"]))
    expected_out = batch_out * Decimal(bom["yield_pct"]) / Decimal(100)
    scale = qty_stock / expected_out
    nodes = []
    for l in call.tx.q(LINES_SQL, bom["id"]):
        over = Decimal(l["overage_pct"]) if _overage_on(call) else Decimal(0)
        need = Decimal(l["quantity"]) * scale * (Decimal(1) + over / Decimal(100))
        comp = book.item(str(l["component_item_id"]))
        need_stock = book.convert(comp, need, str(l["uom_id"]), str(comp["stock_uom_id"]))
        node = {
            "item_id": l["component_item_id"], "code": l["component_code"], "name_en": l["component_name_en"],
            "name_ar": l["component_name_ar"], "type": l["component_type"],
            "quantity": need_stock, "uom": book.uoms[str(comp["stock_uom_id"])]["code"],
            "bom_quantity": l["quantity"], "bom_uom": l["uom"],
            "assay_compensated": l["assay_compensated"], "overage_pct": l["overage_pct"],
            "is_compensating": l["is_compensating"], "children": [], "batches": None, "bom_version": None,
        }
        if l["component_type"] in PRODUCIBLE and depth < 8 and str(comp["id"]) not in path:
            sub = call.tx.one("SELECT * FROM boms WHERE item_id = %s AND status = 'active'", l["component_item_id"])
            if sub:
                sub_out = book.to_stock(str(comp["id"]), Decimal(sub["batch_size"]), str(sub["batch_uom_id"]))
                node["batches"] = need_stock / (sub_out * Decimal(sub["yield_pct"]) / Decimal(100))
                node["bom_version"] = sub["version"]
                node["children"] = _explode(call, book, sub, need_stock, depth + 1, path + (str(comp["id"]),))
        nodes.append(node)
    return nodes


@endpoint(auth="tenant_user")
def explode_bom(call: Call):
    bom = call.tx.one("SELECT * FROM boms WHERE id = %s::uuid", call.path["bom_id"])
    if not bom:
        raise not_found("Bill of materials")
    book = UnitBook(call.tx)
    item = book.item(str(bom["item_id"]))
    try:
        qty = Decimal(call.query.get("quantity") or bom["batch_size"])
    except Exception:
        raise ApiError(422, "invalid", "Quantity must be a number.")
    uom = call.query.get("uom_id") or str(bom["batch_uom_id"])
    qty_stock = book.to_stock(str(item["id"]), qty, uom)
    return {
        "item_id": item["id"], "code": item["code"], "quantity": qty_stock,
        "uom": book.uoms[str(item["stock_uom_id"])]["code"],
        "children": _explode(call, book, bom, qty_stock, 0, (str(item["id"]),)),
    }
