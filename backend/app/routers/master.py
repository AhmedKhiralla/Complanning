"""Company-wide master data: units, items, pack conversions, markets, sales limits and prices."""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..api import ApiError, Call, endpoint, not_found
from ..perms import require_company_edit

ITEM_TYPES = ("raw_material", "packaging", "wip", "semi_finished", "finished")


def patch_row(call: Call, table: str, row_id: str, model: BaseModel, allowed: tuple[str, ...]) -> None:
    """UPDATE only the fields the client sent (fields set to null clear the value)."""
    sent = [f for f in model.model_fields_set if f in allowed]
    if not sent:
        return
    cols = ", ".join(f"{f} = %s" for f in sent)
    call.tx.x(f"UPDATE {table} SET {cols} WHERE id = %s::uuid", *[getattr(model, f) for f in sent], row_id)


def _code(v: str, max_len: int) -> str:
    v = v.strip()
    if not re.match(rf"^[A-Za-z0-9][A-Za-z0-9_./-]{{0,{max_len - 1}}}$", v):
        raise ValueError(f"Use up to {max_len} letters, digits, dot, dash, slash or underscore, starting with a letter or digit.")
    return v


# ================================================================== units
UOM_SQL = "SELECT id, code, name_en, name_ar, dimension, factor_to_base, is_system, active FROM uoms"


class UomIn(BaseModel):
    code: str
    name_en: str = Field(min_length=1, max_length=60)
    name_ar: str | None = Field(default=None, max_length=60)
    dimension: Literal["mass", "volume", "count", "time", "energy", "gas", "other"]
    factor_to_base: Decimal = Field(default=Decimal(1), gt=0)

    @field_validator("code")
    @classmethod
    def _c(cls, v): return _code(v, 12).upper()


class UomPatch(BaseModel):
    name_en: str | None = Field(default=None, min_length=1, max_length=60)
    name_ar: str | None = Field(default=None, max_length=60)
    factor_to_base: Decimal | None = Field(default=None, gt=0)
    active: bool | None = None


@endpoint(auth="tenant_user")
def list_uoms(call: Call):
    return {"items": call.tx.q(UOM_SQL + " ORDER BY dimension, factor_to_base DESC, code")}


@endpoint(auth="tenant_user", body=UomIn)
def create_uom(call: Call):
    require_company_edit(call)
    b: UomIn = call.body
    if call.tx.val("SELECT 1 FROM uoms WHERE upper(code) = %s", b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used."})
    row = call.tx.one("INSERT INTO uoms (tenant_id, code, name_en, name_ar, dimension, factor_to_base)"
                      " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                      call.tenant_id, b.code, b.name_en.strip(), b.name_ar, b.dimension, b.factor_to_base)
    return call.tx.one(UOM_SQL + " WHERE id = %s", row["id"])


@endpoint(auth="tenant_user", body=UomPatch)
def update_uom(call: Call):
    require_company_edit(call)
    uid = call.path["uom_id"]
    u = call.tx.one(UOM_SQL + " WHERE id = %s::uuid", uid)
    if not u:
        raise not_found("Unit")
    b: UomPatch = call.body
    if u["is_system"] and "factor_to_base" in b.model_fields_set and b.factor_to_base != u["factor_to_base"]:
        raise ApiError(422, "system_unit", "Standard units keep their conversion factor.")
    patch_row(call, "uoms", uid, b, ("name_en", "name_ar", "factor_to_base", "active"))
    return call.tx.one(UOM_SQL + " WHERE id = %s::uuid", uid)


# ================================================================== items
ITEM_COLS = ("code", "name_en", "name_ar", "type", "stock_uom_id", "dispensing_uom_id", "density_kg_per_l",
             "description", "grade", "dosage_form", "cleaning_group", "lead_time_days", "moq", "safety_stock",
             "qc_release_days", "shelf_life_months", "pack_size", "units_per_shipper", "standard_cost",
             "test_before_sale", "release_lead_days", "active", "hold_min_hours", "hold_max_hours", "release_at_risk_allowed",
             "not_stock_controlled", "assay_basis")

ITEM_LIST_SQL = """
SELECT i.id, i.code, i.name_en, i.name_ar, i.type, i.stock_uom_id, su.code AS stock_uom, i.dosage_form,
       i.active, i.updated_at,
       (SELECT b.version FROM boms b WHERE b.item_id = i.id AND b.status = 'active') AS active_bom_version,
       (SELECT count(*) FROM boms b WHERE b.item_id = i.id) AS bom_versions
  FROM items i JOIN uoms su ON su.id = i.stock_uom_id
"""


class ItemFields(BaseModel):
    name_en: str | None = Field(default=None, min_length=1, max_length=160)
    name_ar: str | None = Field(default=None, max_length=160)
    stock_uom_id: str | None = None
    dispensing_uom_id: str | None = None
    density_kg_per_l: Decimal | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=500)
    grade: str | None = Field(default=None, max_length=80)
    dosage_form: str | None = Field(default=None, max_length=80)
    cleaning_group: str | None = Field(default=None, max_length=40)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    moq: Decimal | None = Field(default=None, ge=0)
    safety_stock: Decimal | None = Field(default=None, ge=0)
    qc_release_days: Decimal | None = Field(default=None, ge=0, le=365)
    shelf_life_months: int | None = Field(default=None, gt=0, le=240)
    pack_size: Decimal | None = Field(default=None, gt=0)
    units_per_shipper: int | None = Field(default=None, gt=0)
    standard_cost: Decimal | None = Field(default=None, ge=0)
    test_before_sale: bool | None = None
    release_lead_days: Decimal | None = Field(default=None, ge=0, le=365)
    active: bool | None = None
    hold_min_hours: Decimal | None = Field(default=None, ge=0, le=8760)
    hold_max_hours: Decimal | None = Field(default=None, gt=0, le=8760)
    release_at_risk_allowed: bool | None = None
    not_stock_controlled: bool | None = None
    assay_basis: Literal["as_is", "dried"] | None = None

    @field_validator("name_ar", "description", "grade", "dosage_form", "cleaning_group", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("cleaning_group")
    @classmethod
    def _group(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class ItemIn(ItemFields):
    code: str
    name_en: str = Field(min_length=1, max_length=160)
    type: Literal["raw_material", "packaging", "wip", "semi_finished", "finished"]
    stock_uom_id: str

    @field_validator("code")
    @classmethod
    def _c(cls, v): return _code(v, 40).upper()


def _check_group(call: Call, code: str | None) -> None:
    if code and not call.tx.val("SELECT 1 FROM cleaning_groups WHERE code = %s", code):
        raise ApiError(422, "invalid", "Some fields need attention.",
                       fields={"cleaning_group": "Unknown cleaning group. Add it under Rules → Changeovers first."})


def _check_uoms(call: Call, *ids: str | None) -> None:
    for uid in ids:
        if uid and not call.tx.val("SELECT 1 FROM uoms WHERE id = %s::uuid AND active", uid):
            raise ApiError(422, "invalid", "Some fields need attention.", fields={"stock_uom_id": "Choose an active unit."})


def _item_detail(call: Call, item_id) -> dict:
    item = call.tx.one("SELECT i.*, su.code AS stock_uom, du.code AS dispensing_uom FROM items i"
                       " JOIN uoms su ON su.id = i.stock_uom_id LEFT JOIN uoms du ON du.id = i.dispensing_uom_id"
                       " WHERE i.id = %s::uuid", str(item_id))
    if not item:
        raise not_found("Item")
    item["conversions"] = call.tx.q(
        "SELECT c.id, c.uom_id, u.code AS uom, c.factor FROM item_uom_conversions c JOIN uoms u ON u.id = c.uom_id"
        " WHERE c.item_id = %s ORDER BY c.factor", item["id"])
    item["markets"] = call.tx.q(
        "SELECT im.id, im.market_id, m.code AS market, m.currency, im.max_sellable_per_month, im.min_remaining_shelf_pct, im.active"
        "  FROM item_markets im JOIN markets m ON m.id = im.market_id WHERE im.item_id = %s ORDER BY m.code", item["id"])
    item["prices"] = call.tx.q(
        "SELECT p.id, p.market_id, m.code AS market, p.price, p.currency, p.valid_from, p.valid_to, p.created_at,"
        "       (p.valid_from <= current_date AND (p.valid_to IS NULL OR p.valid_to >= current_date)) AS current"
        "  FROM prices p JOIN markets m ON m.id = p.market_id WHERE p.item_id = %s ORDER BY m.code, p.valid_from DESC",
        item["id"])
    item["used_in"] = call.tx.q(
        "SELECT DISTINCT i.id, i.code, i.name_en, i.name_ar, b.version, b.status FROM bom_lines l"
        "  JOIN boms b ON b.id = l.bom_id JOIN items i ON i.id = b.item_id"
        " WHERE l.component_item_id = %s AND b.status <> 'archived' ORDER BY i.code", item["id"])
    return item


@endpoint(auth="tenant_user")
def list_items(call: Call):
    where, params = ["true"], []
    q = call.query
    if q.get("type"):
        types = [t for t in q["type"].split(",") if t in ITEM_TYPES]
        if types:
            where.append("i.type IN (" + ",".join(["%s"] * len(types)) + ")")
            params += types
    if q.get("active") in ("true", "false"):
        where.append("i.active = %s")
        params.append(q["active"] == "true")
    if q.get("q"):
        term = "%" + q["q"].replace("%", r"\%").replace("_", r"\_")[:80] + "%"
        where.append("(i.code ILIKE %s OR i.name_en ILIKE %s OR i.name_ar ILIKE %s)")
        params += [term, term, term]
    rows = call.tx.q(ITEM_LIST_SQL + " WHERE " + " AND ".join(where) + " ORDER BY i.code LIMIT 2000", *params)
    return {"items": rows}


@endpoint(auth="tenant_user")
def get_item(call: Call):
    return _item_detail(call, call.path["item_id"])


@endpoint(auth="tenant_user", body=ItemIn)
def create_item(call: Call):
    require_company_edit(call)
    b: ItemIn = call.body
    if call.tx.val("SELECT 1 FROM items WHERE upper(code) = %s", b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used."})
    _check_uoms(call, b.stock_uom_id, b.dispensing_uom_id)
    _check_group(call, b.cleaning_group)
    cols = [c for c in ITEM_COLS if c in b.model_fields_set or c in ("code", "name_en", "type", "stock_uom_id")]
    vals = [getattr(b, c) for c in cols]
    row = call.tx.one(f"INSERT INTO items (tenant_id, {', '.join(cols)}) VALUES (%s, {', '.join(['%s'] * len(cols))}) RETURNING id",
                      call.tenant_id, *vals)
    return _item_detail(call, row["id"])


@endpoint(auth="tenant_user", body=ItemFields)
def update_item(call: Call):
    require_company_edit(call)
    iid = call.path["item_id"]
    current = call.tx.one("SELECT id, stock_uom_id FROM items WHERE id = %s::uuid", iid)
    if not current:
        raise not_found("Item")
    b: ItemFields = call.body
    if "stock_uom_id" in b.model_fields_set and b.stock_uom_id is None:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"stock_uom_id": "A stock unit is required."})
    if b.stock_uom_id and str(b.stock_uom_id) != str(current["stock_uom_id"]):
        used = call.tx.val("SELECT count(*) FROM bom_lines WHERE component_item_id = %s::uuid", iid) or 0
        used += call.tx.val("SELECT count(*) FROM boms WHERE item_id = %s::uuid", iid) or 0
        if used:
            raise ApiError(422, "unit_in_use", "The stock unit cannot change while the item is used in bills of materials.")
    _check_uoms(call, b.stock_uom_id, b.dispensing_uom_id)
    if "cleaning_group" in b.model_fields_set:
        _check_group(call, b.cleaning_group)
    if b.hold_min_hours is not None and b.hold_max_hours is not None and b.hold_min_hours > b.hold_max_hours:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"hold_min_hours": "Cannot be longer than the maximum hold."})
    patch_row(call, "items", iid, b, tuple(c for c in ITEM_COLS if c not in ("code", "type")))
    return _item_detail(call, iid)


class ConversionIn(BaseModel):
    uom_id: str
    factor: Decimal = Field(gt=0)


class ConversionsIn(BaseModel):
    conversions: list[ConversionIn]


@endpoint(auth="tenant_user", body=ConversionsIn)
def set_conversions(call: Call):
    require_company_edit(call)
    iid = call.path["item_id"]
    item = call.tx.one("SELECT id, stock_uom_id FROM items WHERE id = %s::uuid", iid)
    if not item:
        raise not_found("Item")
    wanted = {c.uom_id: c.factor for c in call.body.conversions if str(c.uom_id) != str(item["stock_uom_id"])}
    current = {str(r["uom_id"]): r for r in call.tx.q("SELECT id, uom_id, factor FROM item_uom_conversions WHERE item_id = %s", item["id"])}
    for uom, r in current.items():
        if uom not in wanted:
            call.tx.x("DELETE FROM item_uom_conversions WHERE id = %s", r["id"])
        elif Decimal(r["factor"]) != wanted[uom]:
            call.tx.x("UPDATE item_uom_conversions SET factor = %s WHERE id = %s", wanted[uom], r["id"])
    for uom, f in wanted.items():
        if uom not in current:
            _check_uoms(call, uom)
            call.tx.x("INSERT INTO item_uom_conversions (tenant_id, item_id, uom_id, factor) VALUES (%s, %s, %s::uuid, %s)",
                      call.tenant_id, item["id"], uom, f)
    return _item_detail(call, iid)


class ItemMarketIn(BaseModel):
    market_id: str
    max_sellable_per_month: Decimal | None = Field(default=None, ge=0)
    min_remaining_shelf_pct: Decimal | None = Field(default=None, ge=0, le=100)
    active: bool = True


class ItemMarketsIn(BaseModel):
    markets: list[ItemMarketIn]


@endpoint(auth="tenant_user", body=ItemMarketsIn)
def set_item_markets(call: Call):
    require_company_edit(call)
    iid = call.path["item_id"]
    if not call.tx.val("SELECT 1 FROM items WHERE id = %s::uuid", iid):
        raise not_found("Item")
    wanted = {m.market_id: m for m in call.body.markets}
    current = {str(r["market_id"]): r for r in call.tx.q(
        "SELECT id, market_id, max_sellable_per_month, min_remaining_shelf_pct, active FROM item_markets WHERE item_id = %s::uuid", iid)}
    for mid, r in current.items():
        if mid not in wanted:
            call.tx.x("DELETE FROM item_markets WHERE id = %s", r["id"])
        else:
            w = wanted[mid]
            call.tx.x("UPDATE item_markets SET max_sellable_per_month = %s, min_remaining_shelf_pct = %s, active = %s WHERE id = %s",
                      w.max_sellable_per_month, w.min_remaining_shelf_pct, w.active, r["id"])
    for mid, w in wanted.items():
        if mid not in current:
            if not call.tx.val("SELECT 1 FROM markets WHERE id = %s::uuid", mid):
                raise ApiError(422, "invalid", "Unknown market.")
            call.tx.x("INSERT INTO item_markets (tenant_id, item_id, market_id, max_sellable_per_month, min_remaining_shelf_pct, active)"
                      " VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s)",
                      call.tenant_id, iid, mid, w.max_sellable_per_month, w.min_remaining_shelf_pct, w.active)
    return _item_detail(call, iid)


# ================================================================== markets
MARKET_SQL = "SELECT id, code, name_en, name_ar, currency, active FROM markets"


class MarketIn(BaseModel):
    code: str
    name_en: str = Field(min_length=1, max_length=120)
    name_ar: str | None = Field(default=None, max_length=120)
    currency: str = Field(default="EGP", min_length=3, max_length=3)

    @field_validator("code")
    @classmethod
    def _c(cls, v): return _code(v, 20).upper()

    @field_validator("currency")
    @classmethod
    def _cur(cls, v):
        v = v.strip().upper()
        if not re.match(r"^[A-Z]{3}$", v):
            raise ValueError("Use a 3-letter currency code such as EGP or USD.")
        return v


class MarketPatch(BaseModel):
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    name_ar: str | None = Field(default=None, max_length=120)
    active: bool | None = None


@endpoint(auth="tenant_user")
def list_markets(call: Call):
    return {"items": call.tx.q(MARKET_SQL + " ORDER BY active DESC, code")}


@endpoint(auth="tenant_user", body=MarketIn)
def create_market(call: Call):
    require_company_edit(call)
    b: MarketIn = call.body
    if call.tx.val("SELECT 1 FROM markets WHERE code = %s", b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used."})
    row = call.tx.one("INSERT INTO markets (tenant_id, code, name_en, name_ar, currency) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                      call.tenant_id, b.code, b.name_en.strip(), b.name_ar, b.currency)
    return call.tx.one(MARKET_SQL + " WHERE id = %s", row["id"])


@endpoint(auth="tenant_user", body=MarketPatch)
def update_market(call: Call):
    require_company_edit(call)
    mid = call.path["market_id"]
    if not call.tx.val("SELECT 1 FROM markets WHERE id = %s::uuid", mid):
        raise not_found("Market")
    patch_row(call, "markets", mid, call.body, ("name_en", "name_ar", "active"))
    return call.tx.one(MARKET_SQL + " WHERE id = %s::uuid", mid)


# ================================================================== prices
class PriceIn(BaseModel):
    market_id: str
    price: Decimal = Field(ge=0)
    valid_from: dt.date


@endpoint(auth="tenant_user", body=PriceIn)
def add_price(call: Call):
    """Add a price. An open price that started earlier is ended the day before the new one starts."""
    require_company_edit(call)
    iid = call.path["item_id"]
    b: PriceIn = call.body
    if not call.tx.val("SELECT 1 FROM items WHERE id = %s::uuid", iid):
        raise not_found("Item")
    market = call.tx.one("SELECT id, currency FROM markets WHERE id = %s::uuid", b.market_id)
    if not market:
        raise ApiError(422, "invalid", "Unknown market.")
    later = call.tx.val("SELECT max(valid_from) FROM prices WHERE item_id = %s::uuid AND market_id = %s AND valid_from >= %s",
                        iid, market["id"], b.valid_from)
    if later:
        raise ApiError(422, "invalid", "Some fields need attention.",
                       fields={"valid_from": f"A price already starts on {later.isoformat()}. Choose a later date."})
    open_price = call.tx.one("SELECT id, valid_from FROM prices WHERE item_id = %s::uuid AND market_id = %s AND valid_to IS NULL",
                             iid, market["id"])
    if open_price:
        call.tx.x("UPDATE prices SET valid_to = %s WHERE id = %s", b.valid_from - dt.timedelta(days=1), open_price["id"])
    call.tx.x("INSERT INTO prices (tenant_id, item_id, market_id, price, currency, valid_from) VALUES (%s, %s::uuid, %s, %s, %s, %s)",
              call.tenant_id, iid, market["id"], b.price, market["currency"], b.valid_from)
    return _item_detail(call, iid)


class PriceEnd(BaseModel):
    valid_to: dt.date


@endpoint(auth="tenant_user", body=PriceEnd)
def end_price(call: Call):
    require_company_edit(call)
    p = call.tx.one("SELECT id, item_id, valid_from, valid_to FROM prices WHERE id = %s::uuid", call.path["price_id"])
    if not p:
        raise not_found("Price")
    if p["valid_to"] is not None:
        raise ApiError(422, "ended", "This price has already ended.")
    if call.body.valid_to < p["valid_from"]:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"valid_to": "The end date must be on or after the start date."})
    call.tx.x("UPDATE prices SET valid_to = %s WHERE id = %s", call.body.valid_to, p["id"])
    return _item_detail(call, p["item_id"])
