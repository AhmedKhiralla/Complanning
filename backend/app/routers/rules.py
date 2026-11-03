"""Phase 3 planning rules: cleaning groups, changeovers, campaigns, equipment holds, holding and QC times."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..api import ApiError, Call, endpoint, not_found
from ..perms import require_company_edit, require_site
from .master import _code, patch_row

ZERO = Decimal(0)


# ================================================================== cleaning groups
GROUP_SQL = """
SELECT g.id, g.code, g.name_en, g.name_ar, g.notes, g.sort_order, g.active,
       (SELECT count(*) FROM items i WHERE i.cleaning_group = g.code) AS item_count
  FROM cleaning_groups g
"""


class GroupIn(BaseModel):
    code: str
    name_en: str = Field(min_length=1, max_length=120)
    name_ar: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("code")
    @classmethod
    def _c(cls, v): return _code(v, 20).upper()


class GroupPatch(BaseModel):
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    name_ar: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)
    sort_order: int | None = None
    active: bool | None = None


@endpoint(auth="tenant_user")
def list_groups(call: Call):
    return {"items": call.tx.q(GROUP_SQL + " ORDER BY g.sort_order, g.code")}


@endpoint(auth="tenant_user", body=GroupIn)
def create_group(call: Call):
    require_company_edit(call)
    b: GroupIn = call.body
    if call.tx.val("SELECT 1 FROM cleaning_groups WHERE code = %s", b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used."})
    order = (call.tx.val("SELECT max(sort_order) FROM cleaning_groups") or 0) + 10
    row = call.tx.one("INSERT INTO cleaning_groups (tenant_id, code, name_en, name_ar, notes, sort_order) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                      call.tenant_id, b.code, b.name_en.strip(), b.name_ar, b.notes, order)
    return call.tx.one(GROUP_SQL + " WHERE g.id = %s", row["id"])


@endpoint(auth="tenant_user", body=GroupPatch)
def update_group(call: Call):
    require_company_edit(call)
    gid = call.path["group_id"]
    if not call.tx.val("SELECT 1 FROM cleaning_groups WHERE id = %s::uuid", gid):
        raise not_found("Cleaning group")
    patch_row(call, "cleaning_groups", gid, call.body, ("name_en", "name_ar", "notes", "sort_order", "active"))
    return call.tx.one(GROUP_SQL + " WHERE g.id = %s::uuid", gid)


@endpoint(auth="tenant_user")
def delete_group(call: Call):
    require_company_edit(call)
    g = call.tx.one("SELECT id, code FROM cleaning_groups WHERE id = %s::uuid", call.path["group_id"])
    if not g:
        raise not_found("Cleaning group")
    used = call.tx.val("SELECT count(*) FROM items WHERE cleaning_group = %s", g["code"])
    rules = call.tx.val("SELECT count(*) FROM changeover_rules WHERE from_group = %s OR to_group = %s", g["code"], g["code"])
    if used or rules:
        raise ApiError(409, "in_use", f"{g['code']} is used by {used} items and {rules} changeover rules. Deactivate it instead.")
    call.tx.x("DELETE FROM cleaning_groups WHERE id = %s", g["id"])
    return {"ok": True}


# ================================================================== changeover rules
RULE_SQL = """
SELECT c.id, c.resource_id, r.code AS resource_code, c.kind, c.from_group, c.to_group,
       c.from_item_id, fi.code AS from_item_code, c.to_item_id, ti.code AS to_item_code,
       c.cleaning_minutes, c.format_minutes, c.verification, c.verification_wait_minutes, c.notes, c.updated_at,
       (c.cleaning_minutes + c.format_minutes + c.verification_wait_minutes) AS total_minutes
  FROM changeover_rules c
  LEFT JOIN resources r ON r.id = c.resource_id
  LEFT JOIN items fi ON fi.id = c.from_item_id
  LEFT JOIN items ti ON ti.id = c.to_item_id
"""

KIND_ORDER = "CASE c.kind WHEN 'default' THEN 1 WHEN 'same_product' THEN 2 WHEN 'same_group' THEN 3 WHEN 'group_to_group' THEN 4 ELSE 5 END"


class RuleFields(BaseModel):
    cleaning_minutes: Decimal = Field(default=ZERO, ge=0, le=100000)
    format_minutes: Decimal = Field(default=ZERO, ge=0, le=100000)
    verification: Literal["none", "visual", "rinse", "swab"] = "none"
    verification_wait_minutes: Decimal = Field(default=ZERO, ge=0, le=100000)
    notes: str | None = Field(default=None, max_length=300)


class RuleIn(RuleFields):
    resource_id: str | None = None
    kind: Literal["same_product", "same_group", "group_to_group", "product_pair", "default"]
    from_group: str | None = None
    to_group: str | None = None
    from_item_id: str | None = None
    to_item_id: str | None = None


def _validate_rule(call: Call, site_id: str, b: RuleIn) -> None:
    fields: dict[str, str] = {}
    if b.resource_id and not call.tx.val("SELECT 1 FROM resources WHERE id = %s::uuid AND site_id = %s::uuid", b.resource_id, site_id):
        fields["resource_id"] = "Choose a machine at this site."
    groups = {r["code"] for r in call.tx.q("SELECT code FROM cleaning_groups")}
    if b.kind == "group_to_group":
        if b.from_group not in groups:
            fields["from_group"] = "Choose a cleaning group."
        if b.to_group not in groups:
            fields["to_group"] = "Choose a cleaning group."
        if b.from_group and b.from_group == b.to_group:
            fields["to_group"] = "Choose a different group, or use a within-group rule."
    if b.kind == "same_group" and b.from_group and b.from_group not in groups:
        fields["from_group"] = "Choose a cleaning group."
    if b.kind == "product_pair":
        for k in ("from_item_id", "to_item_id"):
            v = getattr(b, k)
            if not v or not call.tx.val("SELECT 1 FROM items WHERE id = %s::uuid AND type IN ('wip', 'semi_finished', 'finished')", v):
                fields[k] = "Choose a produced item."
        if b.from_item_id and b.from_item_id == b.to_item_id:
            fields["to_item_id"] = "Choose a different product, or use the same-product rule."
    if fields:
        raise ApiError(422, "invalid", "Some fields need attention.", fields=fields)


def _rule_values(b: RuleIn) -> tuple:
    keep_groups = b.kind in ("group_to_group", "same_group")
    return (b.resource_id or None, b.kind,
            b.from_group if keep_groups else None, b.to_group if b.kind == "group_to_group" else None,
            b.from_item_id if b.kind == "product_pair" else None, b.to_item_id if b.kind == "product_pair" else None,
            b.cleaning_minutes, b.format_minutes, b.verification, b.verification_wait_minutes, (b.notes or "").strip() or None)


@endpoint(auth="tenant_user")
def list_rules(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid)
    return {"items": call.tx.q(RULE_SQL + f" WHERE c.site_id = %s::uuid ORDER BY c.resource_id NULLS FIRST, {KIND_ORDER}, c.from_group, c.to_group, fi.code", sid)}


@endpoint(auth="tenant_user", body=RuleIn)
def create_rule(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid, edit=True)
    b: RuleIn = call.body
    _validate_rule(call, sid, b)
    try:
        row = call.tx.one(
            "INSERT INTO changeover_rules (tenant_id, site_id, resource_id, kind, from_group, to_group, from_item_id, to_item_id,"
            " cleaning_minutes, format_minutes, verification, verification_wait_minutes, notes)"
            " VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s) RETURNING id",
            call.tenant_id, sid, *_rule_values(b))
    except Exception as e:
        if getattr(e, "sqlstate", None) == "23505":
            raise ApiError(409, "duplicate", "A rule for this case already exists. Edit that rule instead.")
        raise
    return call.tx.one(RULE_SQL + " WHERE c.id = %s", row["id"])


@endpoint(auth="tenant_user", body=RuleFields)
def update_rule(call: Call):
    r = call.tx.one("SELECT id, site_id FROM changeover_rules WHERE id = %s::uuid", call.path["rule_id"])
    if not r:
        raise not_found("Changeover rule")
    require_site(call, r["site_id"], edit=True)
    b: RuleFields = call.body
    call.tx.x("UPDATE changeover_rules SET cleaning_minutes = %s, format_minutes = %s, verification = %s,"
              " verification_wait_minutes = %s, notes = %s WHERE id = %s",
              b.cleaning_minutes, b.format_minutes, b.verification, b.verification_wait_minutes, (b.notes or "").strip() or None, r["id"])
    return call.tx.one(RULE_SQL + " WHERE c.id = %s", r["id"])


@endpoint(auth="tenant_user")
def delete_rule(call: Call):
    r = call.tx.one("SELECT id, site_id FROM changeover_rules WHERE id = %s::uuid", call.path["rule_id"])
    if not r:
        raise not_found("Changeover rule")
    require_site(call, r["site_id"], edit=True)
    call.tx.x("DELETE FROM changeover_rules WHERE id = %s", r["id"])
    return {"ok": True}


# ------------------------------------------------------------------ resolver
class Resolver:
    """Finds the changeover between two products on a machine, most specific rule first:
    product pair > group to group / within group > any product change; a machine rule beats a site rule.
    The same product uses the same-product rule."""

    def __init__(self, tx, site_id: str):
        self.rules = tx.q(RULE_SQL + " WHERE c.site_id = %s::uuid", site_id)
        self.groups = {str(r["id"]): r["cleaning_group"] for r in tx.q(
            "SELECT id, cleaning_group FROM items WHERE type IN ('wip', 'semi_finished', 'finished')")}

    def _pick(self, resource_id: str | None, pred):
        for scope in (resource_id, None):
            for r in self.rules:
                rid = str(r["resource_id"]) if r["resource_id"] else None
                if rid == scope and pred(r):
                    return r
        return None

    def resolve(self, resource_id: str | None, from_item: str, to_item: str) -> dict:
        fg, tg = self.groups.get(from_item), self.groups.get(to_item)
        if from_item == to_item:
            r, src = self._pick(resource_id, lambda r: r["kind"] == "same_product"), "same_product"
        else:
            r = self._pick(resource_id, lambda r: r["kind"] == "product_pair" and str(r["from_item_id"]) == from_item
                           and str(r["to_item_id"]) == to_item)
            src = "product_pair"
            if not r and fg and tg and fg == tg:
                r = self._pick(resource_id, lambda r: r["kind"] == "same_group" and r["from_group"] == fg) or \
                    self._pick(resource_id, lambda r: r["kind"] == "same_group" and r["from_group"] is None)
                src = "same_group"
            if not r and fg and tg and fg != tg:
                r = self._pick(resource_id, lambda r: r["kind"] == "group_to_group" and r["from_group"] == fg and r["to_group"] == tg)
                src = "group_to_group"
            if not r:
                r, src = self._pick(resource_id, lambda r: r["kind"] == "default"), "default"
        if not r:
            return {"rule": None, "source": "none", "from_group": fg, "to_group": tg, "total_minutes": 0,
                    "cleaning_minutes": 0, "format_minutes": 0, "verification": "none", "verification_wait_minutes": 0}
        return {"rule": r, "source": r["kind"], "scope": "machine" if r["resource_id"] else "site", "from_group": fg, "to_group": tg,
                "total_minutes": r["total_minutes"], "cleaning_minutes": r["cleaning_minutes"], "format_minutes": r["format_minutes"],
                "verification": r["verification"], "verification_wait_minutes": r["verification_wait_minutes"]}


@endpoint(auth="tenant_user")
def resolve_changeover(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid)
    q = call.query
    if not q.get("from_item_id") or not q.get("to_item_id"):
        raise ApiError(422, "invalid", "Choose both products.")
    return Resolver(call.tx, sid).resolve(q.get("resource_id") or None, q["from_item_id"], q["to_item_id"])


@endpoint(auth="tenant_user")
def changeover_matrix(call: Call):
    """Group-to-group times for one machine (or the site default), with the rule each cell comes from."""
    sid = call.path["site_id"]
    require_site(call, sid)
    rid = call.query.get("resource_id") or None
    groups = call.tx.q("SELECT code, name_en, name_ar FROM cleaning_groups WHERE active ORDER BY sort_order, code")
    rules = call.tx.q(RULE_SQL + " WHERE c.site_id = %s::uuid", sid)

    def pick(pred):
        for scope in ((rid, None) if rid else (None,)):
            for r in rules:
                if (str(r["resource_id"]) if r["resource_id"] else None) == scope and pred(r):
                    return r
        return None

    def cell(r, specific):
        """specific: the rule is written for exactly this cell; scope: whether it comes from the machine or the site."""
        if not r:
            return None
        return {"rule_id": r["id"], "kind": r["kind"], "total_minutes": r["total_minutes"], "verification": r["verification"],
                "specific": specific, "scope": "machine" if r["resource_id"] else "site"}

    default = pick(lambda r: r["kind"] == "default")
    same_product = pick(lambda r: r["kind"] == "same_product")
    matrix = []
    for f in groups:
        row = []
        for t in groups:
            if f["code"] == t["code"]:
                r = pick(lambda r: r["kind"] == "same_group" and r["from_group"] == f["code"])
                fallback = pick(lambda r: r["kind"] == "same_group" and r["from_group"] is None)
                row.append(cell(r, True) or cell(fallback, False) or cell(default, False))
            else:
                r = pick(lambda r: r["kind"] == "group_to_group" and r["from_group"] == f["code"] and r["to_group"] == t["code"])
                row.append(cell(r, True) or cell(default, False))
        matrix.append(row)
    return {"groups": groups, "matrix": matrix, "same_product": cell(same_product, True), "default": cell(default, True)}


# ================================================================== campaigns
CAMP_SQL = """
SELECT c.id, c.item_id, i.code AS item_code, i.name_en AS item_name_en, i.name_ar AS item_name_ar, i.type AS item_type,
       c.resource_id, r.code AS resource_code, c.max_batches, c.max_days, c.min_batches, c.notes, c.updated_at
  FROM campaign_rules c JOIN items i ON i.id = c.item_id LEFT JOIN resources r ON r.id = c.resource_id
"""


class CampaignFields(BaseModel):
    max_batches: int | None = Field(default=None, gt=0, le=1000)
    max_days: Decimal | None = Field(default=None, gt=0, le=365)
    min_batches: int | None = Field(default=None, gt=0, le=1000)
    notes: str | None = Field(default=None, max_length=300)


class CampaignIn(CampaignFields):
    item_id: str
    resource_id: str | None = None


def _check_campaign(b: CampaignFields) -> None:
    if b.max_batches is None and b.max_days is None and b.min_batches is None:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"max_batches": "Set at least one limit."})
    if b.min_batches and b.max_batches and b.min_batches > b.max_batches:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"min_batches": "Cannot be more than the maximum."})


@endpoint(auth="tenant_user")
def list_campaigns(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid)
    return {"items": call.tx.q(CAMP_SQL + " WHERE c.site_id = %s::uuid ORDER BY i.code, r.code NULLS FIRST", sid)}


@endpoint(auth="tenant_user", body=CampaignIn)
def create_campaign(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid, edit=True)
    b: CampaignIn = call.body
    _check_campaign(b)
    if not call.tx.val("SELECT 1 FROM items WHERE id = %s::uuid AND type IN ('wip', 'semi_finished', 'finished')", b.item_id):
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"item_id": "Choose a produced item."})
    if b.resource_id and not call.tx.val("SELECT 1 FROM resources WHERE id = %s::uuid AND site_id = %s::uuid", b.resource_id, sid):
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"resource_id": "Choose a machine at this site."})
    if call.tx.val("SELECT 1 FROM campaign_rules WHERE site_id = %s::uuid AND item_id = %s::uuid AND resource_id IS NOT DISTINCT FROM %s::uuid",
                   sid, b.item_id, b.resource_id):
        raise ApiError(409, "duplicate", "This product already has a campaign limit on this machine. Edit it instead.")
    row = call.tx.one("INSERT INTO campaign_rules (tenant_id, site_id, item_id, resource_id, max_batches, max_days, min_batches, notes)"
                      " VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s) RETURNING id",
                      call.tenant_id, sid, b.item_id, b.resource_id, b.max_batches, b.max_days, b.min_batches, (b.notes or "").strip() or None)
    return call.tx.one(CAMP_SQL + " WHERE c.id = %s", row["id"])


@endpoint(auth="tenant_user", body=CampaignFields)
def update_campaign(call: Call):
    c = call.tx.one("SELECT id, site_id FROM campaign_rules WHERE id = %s::uuid", call.path["campaign_id"])
    if not c:
        raise not_found("Campaign limit")
    require_site(call, c["site_id"], edit=True)
    b: CampaignFields = call.body
    _check_campaign(b)
    call.tx.x("UPDATE campaign_rules SET max_batches = %s, max_days = %s, min_batches = %s, notes = %s WHERE id = %s",
              b.max_batches, b.max_days, b.min_batches, (b.notes or "").strip() or None, c["id"])
    return call.tx.one(CAMP_SQL + " WHERE c.id = %s", c["id"])


@endpoint(auth="tenant_user")
def delete_campaign(call: Call):
    c = call.tx.one("SELECT id, site_id FROM campaign_rules WHERE id = %s::uuid", call.path["campaign_id"])
    if not c:
        raise not_found("Campaign limit")
    require_site(call, c["site_id"], edit=True)
    call.tx.x("DELETE FROM campaign_rules WHERE id = %s", c["id"])
    return {"ok": True}


# ================================================================== equipment hold times
class HoldRow(BaseModel):
    resource_id: str
    dirty_hold_hours: Decimal | None = Field(default=None, gt=0, le=8760)
    clean_hold_hours: Decimal | None = Field(default=None, gt=0, le=8760)


class HoldsIn(BaseModel):
    rows: list[HoldRow]


@endpoint(auth="tenant_user", body=HoldsIn)
def save_equipment_holds(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid, edit=True)
    current = {str(r["id"]): r for r in call.tx.q("SELECT id, dirty_hold_hours, clean_hold_hours FROM resources WHERE site_id = %s::uuid", sid)}
    for row in call.body.rows:
        cur = current.get(row.resource_id)
        if not cur:
            raise ApiError(422, "invalid", "Unknown machine.")
        if cur["dirty_hold_hours"] != row.dirty_hold_hours or cur["clean_hold_hours"] != row.clean_hold_hours:
            call.tx.x("UPDATE resources SET dirty_hold_hours = %s, clean_hold_hours = %s WHERE id = %s",
                      row.dirty_hold_hours, row.clean_hold_hours, cur["id"])
    return {"items": call.tx.q("SELECT id, code, name_en, name_ar, area, type, dirty_hold_hours, clean_hold_hours FROM resources"
                               " WHERE site_id = %s::uuid AND active ORDER BY area NULLS LAST, code", sid)}


@endpoint(auth="tenant_user")
def list_equipment_holds(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid)
    return {"items": call.tx.q("SELECT id, code, name_en, name_ar, area, type, dirty_hold_hours, clean_hold_hours FROM resources"
                               " WHERE site_id = %s::uuid AND active ORDER BY area NULLS LAST, code", sid)}


# ================================================================== holding and QC times (company-wide, per produced item)
TIMES_SQL = """
SELECT i.id, i.code, i.name_en, i.name_ar, i.type, i.cleaning_group, i.hold_min_hours, i.hold_max_hours,
       i.release_lead_days, i.release_at_risk_allowed, i.test_before_sale
  FROM items i WHERE i.type IN ('wip', 'semi_finished', 'finished') AND i.active
 ORDER BY CASE i.type WHEN 'wip' THEN 1 WHEN 'semi_finished' THEN 2 ELSE 3 END, i.code
"""


class TimesRow(BaseModel):
    item_id: str
    cleaning_group: str | None = None
    hold_min_hours: Decimal | None = Field(default=None, ge=0, le=8760)
    hold_max_hours: Decimal | None = Field(default=None, gt=0, le=8760)
    release_lead_days: Decimal | None = Field(default=None, ge=0, le=365)
    release_at_risk_allowed: bool = False
    test_before_sale: bool = False


class TimesIn(BaseModel):
    rows: list[TimesRow]


@endpoint(auth="tenant_user")
def list_item_times(call: Call):
    return {"items": call.tx.q(TIMES_SQL)}


@endpoint(auth="tenant_user", body=TimesIn)
def save_item_times(call: Call):
    require_company_edit(call)
    groups = {r["code"] for r in call.tx.q("SELECT code FROM cleaning_groups")}
    current = {str(r["id"]): r for r in call.tx.q(TIMES_SQL)}
    errors: dict[str, str] = {}
    for i, row in enumerate(call.body.rows):
        if row.item_id not in current:
            errors[f"rows.{i}"] = "Unknown item."
        elif row.hold_min_hours is not None and row.hold_max_hours is not None and row.hold_min_hours > row.hold_max_hours:
            errors[f"rows.{i}"] = "The minimum wait cannot be longer than the maximum hold."
        elif row.cleaning_group and row.cleaning_group.upper() not in groups:
            errors[f"rows.{i}"] = "Unknown cleaning group."
    if errors:
        raise ApiError(422, "invalid", "Some rows need attention.", fields=errors)
    cols = ("cleaning_group", "hold_min_hours", "hold_max_hours", "release_lead_days", "release_at_risk_allowed", "test_before_sale")
    for row in call.body.rows:
        cur = current[row.item_id]
        new = {c: getattr(row, c) for c in cols}
        new["cleaning_group"] = (new["cleaning_group"] or "").upper() or None
        if cur["type"] != "finished":
            new["test_before_sale"] = cur["test_before_sale"]
        changed = [c for c in cols if cur[c] != new[c]]
        if changed:
            call.tx.x(f"UPDATE items SET {', '.join(c + ' = %s' for c in changed)} WHERE id = %s::uuid",
                      *[new[c] for c in changed], row.item_id)
    return {"items": call.tx.q(TIMES_SQL)}
