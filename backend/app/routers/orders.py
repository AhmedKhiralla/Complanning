"""Production orders: templates, batch numbers, generating orders from a released plan, electronic approval,
issue, cancel, reissue, and the PDF or Word file of one or many orders."""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Literal

from pydantic import BaseModel, Field
from starlette.responses import Response

from .. import orders as O
from ..api import ApiError, Call, endpoint, not_found
from ..order_render import render_docx, render_pdf
from ..perms import require_plan
from ..security import verify_password

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ------------------------------------------------------------------ templates
class FieldIn(BaseModel):
    key: str = Field(max_length=40)
    label: str = Field(max_length=60)


class SignIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    format_number: str | None = Field(default=None, max_length=60)
    number_pattern: str = Field(min_length=1, max_length=80)
    next_seq: int = Field(default=1, ge=1, le=10_000_000)
    orientation: Literal["landscape", "portrait"] = "landscape"
    logo: str | None = Field(default=None, max_length=1_500_000)
    header_columns: int = Field(default=3, ge=1, le=4)
    header_fields: list[FieldIn] = Field(default_factory=list, max_length=20)
    columns: list[FieldIn] = Field(default_factory=list, max_length=14)
    component_types: list[str] = Field(default_factory=list, max_length=5)
    signatures: list[SignIn] = Field(default_factory=list, max_length=8)
    require_esign: bool = False
    remarks_label: str | None = Field(default=None, max_length=60)
    remarks_lines: int = Field(default=2, ge=0, le=10)
    footer_note: str | None = Field(default=None, max_length=140)
    active: bool = True


TEMPLATE_COLS = ("name", "title", "format_number", "number_pattern", "next_seq", "orientation", "logo", "header_columns",
                 "header_fields", "columns", "component_types", "signatures", "require_esign", "remarks_label",
                 "remarks_lines", "footer_note", "active")
JSON_COLS = {"header_fields", "columns", "component_types", "signatures"}


def _templates(call: Call) -> list[dict]:
    O.ensure_templates(call.tx, call.tenant_id)
    return call.tx.q("SELECT * FROM order_templates ORDER BY kind DESC, is_default DESC, name")


@endpoint(auth="tenant_user")
def list_templates(call: Call):
    return {"items": _templates(call), "header_fields": O.HEADER_FIELDS, "columns": O.COLUMNS,
            "item_types": list(O.ITEM_TYPES)}


def _require_admin(call: Call):
    if not call.user["is_tenant_admin"]:
        raise ApiError(403, "forbidden", "Only company administrators change order templates.")


@endpoint(auth="tenant_user", body=TemplateIn)
def update_template(call: Call):
    _require_admin(call)
    tid = call.path["template_id"]
    if not call.tx.val("SELECT 1 FROM order_templates WHERE id = %s::uuid", tid):
        raise not_found("Template")
    b: TemplateIn = call.body
    data = b.model_dump()
    data["header_fields"] = [f.model_dump() for f in b.header_fields]
    data["columns"] = [f.model_dump() for f in b.columns]
    data["signatures"] = [s.model_dump() for s in b.signatures]
    errors = O.check_template(data)
    if errors:
        raise ApiError(422, "invalid", "Some fields need attention.", fields=errors)
    sets = ", ".join(f"{c} = %s::jsonb" if c in JSON_COLS else f"{c} = %s" for c in TEMPLATE_COLS)
    vals = [json.dumps(data[c]) if c in JSON_COLS else data[c] for c in TEMPLATE_COLS]
    call.tx.x(f"UPDATE order_templates SET {sets} WHERE id = %s::uuid", *vals, tid)
    return call.tx.one("SELECT * FROM order_templates WHERE id = %s::uuid", tid)


@endpoint(auth="tenant_user", body=TemplateIn)
def preview_template(call: Call):
    """A sample order laid out with the template as edited (not saved)."""
    b: TemplateIn = call.body
    t = b.model_dump()
    t["header_fields"] = [f.model_dump() for f in b.header_fields]
    t["columns"] = [f.model_dump() for f in b.columns]
    t["signatures"] = [s.model_dump() for s in b.signatures]
    t["kind"] = call.query.get("kind") or "packaging"
    errors = O.check_template({**t, "number_pattern": t["number_pattern"] or "{BATCH}"})
    errors.pop("number_pattern", None)
    if errors:
        raise ApiError(422, "invalid", "Some fields need attention.", fields=errors)
    today = dt.date.today()
    number = O.expand(t["number_pattern"], today, batch="26013", code="FP-SAMPLE", seq=t["next_seq"])
    values = {"product_name": "Sample product 50 mg, 30 capsules", "product_code": "FP-SAMPLE", "batch_number": "26013",
              "batch_size": "50,000 EA", "date_issued": today.strftime("%d/%m/%Y"), "order_number": number,
              "mfg_date": today.strftime("%m/%Y"), "exp_date": today.replace(year=today.year + 2).strftime("%m/%Y"),
              "shelf_life": "2 years", "bom_version": "v3", "planned_start": today.strftime("%d/%m/%Y 07:00"),
              "planned_end": today.strftime("%d/%m/%Y 19:00"), "plan": "December plan", "site": "SITE_01 · Main plant"}
    lines = [{"ser": "1", "name": "Sample box", "code": "PM-0001", "qty_required": "50,000", "uom": "EA"},
             {"ser": "2", "name": "Sample leaflet", "code": "PM-0002", "qty_required": "50,000", "uom": "EA"},
             {"ser": "3", "name": "Aluminium foil", "code": "PM-0003", "qty_required": "295", "uom": "KG"}]
    content = {"template": t, "number": number, "batch_number": "26013", "values": values, "lines": lines}
    data = render_pdf([{"content": content, "status": "draft", "signatures": [], "revision": 0}])
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="preview.pdf"'})


# ------------------------------------------------------------------ batch numbers
class NumberingIn(BaseModel):
    pattern: str | None = Field(default=None, max_length=60)
    next: int = Field(default=1, ge=1, le=10_000_000)


@endpoint(auth="tenant_user", body=NumberingIn)
def save_numbering(call: Call):
    sid = call.path["site_id"]
    require_plan(call, sid, edit=True)
    b: NumberingIn = call.body
    pat = (b.pattern or "").strip() or None
    if pat and not O.uses_seq(pat):
        raise ApiError(422, "invalid", "Some fields need attention.",
                       fields={"pattern": "Include {SEQ} (for example {YY}{SEQ:3}) so each batch gets its own number."})
    call.tx.x("UPDATE sites SET batch_number_pattern = %s, batch_number_next = %s WHERE id = %s::uuid", pat, b.next, sid)
    return _numbering(call, sid)


def _numbering(call: Call, sid: str) -> dict:
    s = call.tx.one("SELECT batch_number_pattern, batch_number_next, timezone FROM sites WHERE id = %s::uuid", sid)
    nxt = O.expand(s["batch_number_pattern"], O.tz_today(s), seq=s["batch_number_next"], code="CODE") if s["batch_number_pattern"] else None
    return {"pattern": s["batch_number_pattern"], "next": s["batch_number_next"], "example": nxt}


@endpoint(auth="tenant_user")
def get_numbering(call: Call):
    sid = call.path["site_id"]
    require_plan(call, sid)
    return _numbering(call, sid)


def _plan(call: Call, pid: str, edit: bool = False) -> tuple[dict, dict]:
    p = call.tx.one("SELECT id, site_id, name, status, options, batch_numbers FROM plans WHERE id = %s::uuid", pid)
    if not p:
        raise not_found("Plan")
    site = require_plan(call, p["site_id"], edit=edit)
    return p, site


class NumbersIn(BaseModel):
    numbers: dict[str, str | None]          # plan batch id -> batch number (empty clears it)


def _set_numbers(call: Call, p: dict, changes: dict[str, str | None]) -> None:
    batches = {str(b["id"]): b for b in call.tx.q("SELECT id, item_id, ordinal, lot_no, batch_no FROM plan_batches WHERE plan_id = %s", p["id"])}
    current = dict(p["batch_numbers"] or {})
    for bid, num in changes.items():
        b = batches.get(bid)
        if not b:
            raise ApiError(422, "invalid", "A batch is not in this plan.")
        key = O.batch_key(b["item_id"], b["ordinal"])
        num = (num or "").strip() or None
        if num and (len(num) > 40 or not re.match(r"^[\w./\-]+$", num)):
            raise ApiError(422, "invalid", "Some fields need attention.",
                           fields={bid: "Use letters, digits and . / - _ only (up to 40)."})
        if num:
            current[key] = num
        else:
            current.pop(key, None)
    # One number per batch within the plan.
    seen: dict[str, str] = {}
    for key, num in current.items():
        if num in seen:
            raise ApiError(422, "duplicate_batch_number", f"Batch number {num} is used twice in this plan.", fields={"number": num})
        seen[num] = key
    call.tx.x("UPDATE plans SET batch_numbers = %s::jsonb WHERE id = %s", json.dumps(current), p["id"])
    for b in batches.values():
        call.tx.x("UPDATE plan_batches SET lot_no = %s WHERE id = %s", current.get(O.batch_key(b["item_id"], b["ordinal"])), b["id"])
    # Draft orders follow the batch number.
    for o in call.tx.q("SELECT o.*, t.number_pattern FROM production_orders o JOIN order_templates t ON t.id = o.template_id"
                       " WHERE o.plan_id = %s AND o.status = 'draft'", p["id"]):
        num = current.get(O.batch_key(o["item_id"], o["ordinal"]))
        if num and num != o["batch_number"]:
            code = call.tx.val("SELECT code FROM items WHERE id = %s", o["item_id"])
            number = O.expand(o["number_pattern"], o["created_at"].date(), batch=num, code=code, seq=o["seq"])
            call.tx.x("UPDATE production_orders SET batch_number = %s, number = %s WHERE id = %s", num, number, o["id"])
    p["batch_numbers"] = current


@endpoint(auth="tenant_user", body=NumbersIn)
def set_batch_numbers(call: Call):
    p, _site = _plan(call, call.path["plan_id"], edit=True)
    _set_numbers(call, p, call.body.numbers)
    return {"batch_numbers": p["batch_numbers"]}


class FillIn(BaseModel):
    batch_ids: list[str] | None = None


def _fill(call: Call, p: dict, site: dict, batch_ids: list[str] | None) -> int:
    s = call.tx.one("SELECT batch_number_pattern, batch_number_next, timezone FROM sites WHERE id = %s FOR UPDATE", site["id"])
    if not s["batch_number_pattern"]:
        raise ApiError(409, "no_pattern", "Set a batch number pattern for this site first (Orders tab › Batch numbers).")
    current = p["batch_numbers"] or {}
    rows = call.tx.q("SELECT b.id, b.item_id, b.ordinal, i.code FROM plan_batches b JOIN items i ON i.id = b.item_id"
                     " WHERE b.plan_id = %s AND b.status = 'scheduled' ORDER BY b.batch_no", p["id"])
    nxt, changes = s["batch_number_next"], {}
    used = set(current.values())
    today = O.tz_today(s)
    for r in rows:
        if batch_ids and str(r["id"]) not in batch_ids:
            continue
        if current.get(O.batch_key(r["item_id"], r["ordinal"])):
            continue
        while True:
            num = O.expand(s["batch_number_pattern"], today, seq=nxt, code=r["code"])
            nxt += 1
            if num not in used:
                break
        used.add(num)
        changes[str(r["id"])] = num
    if changes:
        _set_numbers(call, p, changes)
        call.tx.x("UPDATE sites SET batch_number_next = %s WHERE id = %s", nxt, site["id"])
    return len(changes)


@endpoint(auth="tenant_user", body=FillIn)
def fill_batch_numbers(call: Call):
    p, site = _plan(call, call.path["plan_id"], edit=True)
    n = _fill(call, p, site, call.body.batch_ids)
    return {"filled": n, "batch_numbers": p["batch_numbers"]}


# ------------------------------------------------------------------ orders
ORDER_SQL = """
SELECT o.*, i.code AS item_code, i.name_en AS item_name, i.name_ar AS item_name_ar, i.type AS item_type,
       t.name AS template_name, t.signatures AS template_signatures, t.require_esign AS template_esign,
       coalesce((SELECT json_agg(json_build_object('level', s.level, 'title', s.title, 'user_id', s.user_id,
                 'user_name', s.user_name, 'signed_at', s.signed_at, 'meaning', s.meaning) ORDER BY s.level)
                 FROM order_signatures s WHERE s.order_id = o.id), '[]'::json) AS signatures
  FROM production_orders o JOIN items i ON i.id = o.item_id JOIN order_templates t ON t.id = o.template_id
"""


def _decorate(call: Call, rows: list[dict], p: dict | None) -> list[dict]:
    nums = (p or {}).get("batch_numbers") or {}
    batches = {}
    if p:
        batches = {O.batch_key(b["item_id"], b["ordinal"]): b for b in call.tx.q(
            "SELECT id, item_id, ordinal, batch_no FROM plan_batches WHERE plan_id = %s", p["id"])}
    for o in rows:
        content = o.pop("content", None)
        levels = (content or {}).get("template", {}).get("signatures") if content else o["template_signatures"]
        o["levels"] = [s["title"] for s in (levels or [])]
        o["esign"] = (content or {}).get("template", {}).get("require_esign", o["template_esign"]) if content else o["template_esign"]
        key = O.batch_key(o["item_id"], o["ordinal"])
        b = batches.get(key)
        o["batch_id"] = str(b["id"]) if b else None
        o["plan_batch_no"] = b["batch_no"] if b else None
        cur = nums.get(key)
        o["outdated"] = o["status"] in ("approved", "issued") and bool(cur) and cur != o["batch_number"]
        o.pop("template_signatures", None)
        o.pop("template_esign", None)
    return rows


@endpoint(auth="tenant_user")
def plan_orders(call: Call):
    p, site = _plan(call, call.path["plan_id"])
    rows = call.tx.q(ORDER_SQL + " WHERE o.plan_id = %s ORDER BY o.kind, o.number", p["id"])
    tpl = [{"id": t["id"], "kind": t["kind"], "name": t["name"], "is_default": t["is_default"], "active": t["active"],
            "component_types": t["component_types"]} for t in _templates(call)]
    return {"orders": _decorate(call, rows, p), "templates": tpl, "batch_numbers": p["batch_numbers"] or {},
            "numbering": _numbering(call, str(site["id"]))}


class CreateIn(BaseModel):
    batch_ids: list[str] = Field(min_length=1, max_length=500)
    kinds: list[Literal["manufacturing", "packaging"]] = Field(min_length=1)
    template_ids: dict[str, str] | None = None        # kind -> template id (default template otherwise)


@endpoint(auth="tenant_user", body=CreateIn)
def create_orders(call: Call):
    p, site = _plan(call, call.path["plan_id"], edit=True)
    if p["status"] != "released":
        raise ApiError(409, "not_released", "Release the plan before issuing production orders, so orders follow the official plan.")
    b: CreateIn = call.body
    tpls = {}
    for kind in b.kinds:
        tid = (b.template_ids or {}).get(kind)
        t = call.tx.one("SELECT * FROM order_templates WHERE id = %s::uuid AND kind = %s AND active", tid, kind) if tid else \
            call.tx.one("SELECT * FROM order_templates WHERE kind = %s AND active ORDER BY is_default DESC, name LIMIT 1", kind)
        if not t:
            raise ApiError(422, "no_template", f"There is no active {kind} order template.")
        tpls[kind] = t
    batches = {str(x["id"]): x for x in call.tx.q(
        "SELECT b.*, i.code FROM plan_batches b JOIN items i ON i.id = b.item_id WHERE b.plan_id = %s", p["id"])}
    picked = [batches[x] for x in b.batch_ids if x in batches]
    if not picked:
        raise ApiError(422, "invalid", "Choose batches of this plan.")
    nums = p["batch_numbers"] or {}
    missing = [x for x in picked if not nums.get(O.batch_key(x["item_id"], x["ordinal"]))]
    if missing:
        s = call.tx.val("SELECT batch_number_pattern FROM sites WHERE id = %s", site["id"])
        if not s:
            raise ApiError(422, "no_batch_numbers", "Give these batches a batch number first: "
                           + ", ".join(sorted({f"{x['batch_no']} ({x['code']})" for x in missing})[:12]) + ".")
        _fill(call, p, site, [str(x["id"]) for x in missing])
        nums = p["batch_numbers"]
    today = O.tz_today(site)
    created, skipped = [], []
    for x in sorted(picked, key=lambda r: r["batch_no"]):
        if x["status"] != "scheduled":
            skipped.append({"batch": x["batch_no"], "kind": None, "reason": "unscheduled"})
            continue
        num = nums[O.batch_key(x["item_id"], x["ordinal"])]
        for kind, t in tpls.items():
            if not O.has_components(call.tx, x, t["component_types"]):
                skipped.append({"batch": x["batch_no"], "kind": kind, "reason": "no_components"})
                continue
            if call.tx.val("SELECT 1 FROM production_orders WHERE plan_id = %s AND item_id = %s AND ordinal = %s AND kind = %s"
                           " AND status <> 'cancelled'", p["id"], x["item_id"], x["ordinal"], kind):
                skipped.append({"batch": x["batch_no"], "kind": kind, "reason": "exists"})
                continue
            seq = None
            if O.uses_seq(t["number_pattern"]):
                seq = call.tx.val("UPDATE order_templates SET next_seq = next_seq + 1 WHERE id = %s RETURNING next_seq - 1", t["id"])
            number = O.expand(t["number_pattern"], today, batch=num, code=x["code"], seq=seq)
            if call.tx.val("SELECT 1 FROM production_orders WHERE kind = %s AND number = %s AND status <> 'cancelled'", kind, number):
                raise ApiError(409, "duplicate_order_number",
                               f"Order number {number} is already in use. Change the batch number of {x['batch_no']} or the "
                               "template's number pattern.")
            oid = call.tx.val(
                "INSERT INTO production_orders (tenant_id, site_id, plan_id, template_id, kind, number, seq, item_id, ordinal, batch_number)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                call.tenant_id, site["id"], p["id"], t["id"], kind, number, seq, x["item_id"], x["ordinal"], num)
            created.append(str(oid))
    rows = call.tx.q(ORDER_SQL + " WHERE o.plan_id = %s ORDER BY o.kind, o.number", p["id"])
    return {"created": created, "skipped": skipped, "orders": _decorate(call, rows, p)}


def _load(call: Call, ids: list[str], edit: bool = False) -> list[dict]:
    rows = call.tx.q(ORDER_SQL + " WHERE o.id = ANY(string_to_array(%s, ',')::uuid[]) ORDER BY o.kind, o.number", ",".join(ids))
    if len(rows) != len(set(ids)):
        raise O.not_found_order()
    for site_id in {str(r["site_id"]) for r in rows}:
        require_plan(call, site_id, edit=edit)
    return rows


def _content(call: Call, o: dict) -> dict:
    """The printed content: frozen once approved or issued, otherwise built now from the plan and template."""
    if o.get("content"):
        return o["content"]
    t = call.tx.one("SELECT * FROM order_templates WHERE id = %s", o["template_id"])
    site = call.tx.one("SELECT id, code, name, timezone FROM sites WHERE id = %s", o["site_id"])
    p = call.tx.one("SELECT id, name, options FROM plans WHERE id = %s", o["plan_id"]) if o["plan_id"] else None
    b = call.tx.one("SELECT * FROM plan_batches WHERE plan_id = %s AND item_id = %s AND ordinal = %s",
                    o["plan_id"], o["item_id"], o["ordinal"]) if p else None
    from zoneinfo import ZoneInfo
    issued_on = (o["issued_at"].astimezone(ZoneInfo(site["timezone"] or "UTC")).date() if o.get("issued_at") else O.tz_today(site))
    return O.build_content(call.tx, o, t, p, site, b, issued_on)


def _freeze(call: Call, o: dict) -> None:
    c = _content(call, {**o, "content": None})
    call.tx.x("UPDATE production_orders SET content = %s::jsonb WHERE id = %s", json.dumps(c, default=str), o["id"])


class IdsIn(BaseModel):
    order_ids: list[str] = Field(min_length=1, max_length=500)


class SignOrdersIn(IdsIn):
    password: str = Field(min_length=1, max_length=200)
    meaning: Literal["approved", "reviewed", "issued", "received"] = "approved"


@endpoint(auth="tenant_user", body=SignOrdersIn)
def sign_orders(call: Call):
    """Electronic signature (21 CFR Part 11): the signer re-enters their password; each order is signed at its next
    open level, in order, and one person signs one level per order."""
    b: SignOrdersIn = call.body
    rows = _load(call, b.order_ids)
    pw = call.tx.val("SELECT password_hash FROM users WHERE id = %s", call.user["id"])
    if not verify_password(b.password, pw):
        call.tx.event("SIGNATURE_FAILED", "production_orders", None, call.user["email"],
                      {"orders": [o["number"] for o in rows]})
        call.tx.commit()  # keep the audit entry even though nothing is signed
        raise ApiError(403, "bad_password", "The password is not correct. Nothing was signed.")
    for o in rows:
        content = call.tx.val("SELECT content FROM production_orders WHERE id = %s", o["id"])
        tsig = call.tx.one("SELECT signatures, require_esign FROM order_templates WHERE id = %s", o["template_id"])
        if not tsig["require_esign"]:
            raise ApiError(409, "no_esign", f"Order {o['number']} is approved on paper; its template has no electronic approval.")
        if o["status"] != "draft":
            raise ApiError(409, "not_draft", f"Order {o['number']} is {o['status']} and cannot be signed.")
        levels = tsig["signatures"]
        done = {s["level"] for s in o["signatures"]}
        if any(s["user_id"] == str(call.user["id"]) for s in o["signatures"]):
            raise ApiError(409, "already_signed", f"You have already signed order {o['number']}; another person signs the next level.")
        level = next((i for i in range(len(levels)) if i not in done), None)
        if level is None:
            continue
        call.tx.x("INSERT INTO order_signatures (tenant_id, order_id, level, title, user_id, user_name, meaning)"
                  " VALUES (%s, %s, %s, %s, %s, %s, %s)", call.tenant_id, o["id"], level, levels[level]["title"],
                  call.user["id"], call.user["full_name"], b.meaning)
        if level == len(levels) - 1:
            call.tx.x("UPDATE production_orders SET status = 'approved' WHERE id = %s", o["id"])
            _freeze(call, {**o, "content": content})
    return {"orders": _decorate(call, call.tx.q(ORDER_SQL + " WHERE o.id = ANY(string_to_array(%s, ',')::uuid[])", ",".join(b.order_ids)), None)}


@endpoint(auth="tenant_user", body=IdsIn)
def issue_orders(call: Call):
    b: IdsIn = call.body
    rows = _load(call, b.order_ids, edit=True)
    for o in rows:
        esign = call.tx.val("SELECT require_esign FROM order_templates WHERE id = %s", o["template_id"])
        if o["status"] == "issued":
            continue
        if o["status"] == "cancelled":
            raise ApiError(409, "cancelled", f"Order {o['number']} is cancelled.")
        if esign and o["status"] != "approved":
            raise ApiError(409, "not_approved", f"Order {o['number']} needs all its electronic approvals before it is issued.")
        if o["status"] == "draft":
            _freeze(call, o)
        call.tx.x("UPDATE production_orders SET status = 'issued', issued_at = now(), issued_by = %s WHERE id = %s",
                  call.user["id"], o["id"])
    return {"orders": _decorate(call, call.tx.q(ORDER_SQL + " WHERE o.id = ANY(string_to_array(%s, ',')::uuid[])", ",".join(b.order_ids)), None)}


class CancelIn(IdsIn):
    reason: str = Field(min_length=3, max_length=300)


@endpoint(auth="tenant_user", body=CancelIn)
def cancel_orders(call: Call):
    b: CancelIn = call.body
    rows = _load(call, b.order_ids, edit=True)
    for o in rows:
        if o["status"] == "cancelled":
            continue
        if not call.tx.val("SELECT content FROM production_orders WHERE id = %s", o["id"]) and o["status"] != "draft":
            _freeze(call, o)
        call.tx.x("UPDATE production_orders SET status = 'cancelled', cancel_reason = %s WHERE id = %s", b.reason.strip(), o["id"])
    return {"ok": True}


@endpoint(auth="tenant_user", body=IdsIn)
def delete_drafts(call: Call):
    b: IdsIn = call.body
    rows = _load(call, b.order_ids, edit=True)
    for o in rows:
        if o["status"] != "draft" or o["signatures"]:
            raise ApiError(409, "not_draft", f"Order {o['number']} has been signed or issued; cancel it instead.")
    call.tx.x("DELETE FROM production_orders WHERE id = ANY(string_to_array(%s, ',')::uuid[])", ",".join(b.order_ids))
    return {"ok": True}


@endpoint(auth="tenant_user", body=CancelIn)
def reissue_orders(call: Call):
    """Cancel approved or issued orders and make new drafts (next revision) with today's plan data and batch number."""
    b: CancelIn = call.body
    rows = _load(call, b.order_ids, edit=True)
    new = []
    for o in rows:
        if o["status"] not in ("approved", "issued"):
            raise ApiError(409, "not_issued", f"Order {o['number']} is {o['status']}; only approved or issued orders are reissued.")
        p = call.tx.one("SELECT id, batch_numbers FROM plans WHERE id = %s", o["plan_id"]) if o["plan_id"] else None
        num = ((p or {}).get("batch_numbers") or {}).get(O.batch_key(o["item_id"], o["ordinal"])) or o["batch_number"]
        t = call.tx.one("SELECT * FROM order_templates WHERE id = %s", o["template_id"])
        site = call.tx.one("SELECT timezone FROM sites WHERE id = %s", o["site_id"])
        call.tx.x("UPDATE production_orders SET status = 'cancelled', cancel_reason = %s WHERE id = %s",
                  f"Reissued as revision {o['revision'] + 1}: {b.reason.strip()}", o["id"])
        number = O.expand(t["number_pattern"], O.tz_today(site), batch=num, code=o["item_code"], seq=o["seq"]) \
            if num != o["batch_number"] else o["number"]
        oid = call.tx.val(
            "INSERT INTO production_orders (tenant_id, site_id, plan_id, template_id, kind, number, seq, item_id, ordinal,"
            " batch_number, revision) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            call.tenant_id, o["site_id"], o["plan_id"], o["template_id"], o["kind"], number, o["seq"], o["item_id"],
            o["ordinal"], num, o["revision"] + 1)
        new.append(str(oid))
    return {"created": new}


@endpoint(auth="tenant_user")
def order_file(call: Call):
    ids = [x for x in (call.query.get("ids") or "").split(",") if x]
    fmt = call.query.get("format") or "pdf"
    if not ids or len(ids) > 500 or fmt not in ("pdf", "docx"):
        raise ApiError(422, "invalid", "Choose orders and a format (pdf or docx).")
    rows = _load(call, ids)
    full = {str(r["id"]): r for r in call.tx.q("SELECT id, content, issued_at FROM production_orders WHERE id = ANY(string_to_array(%s, ',')::uuid[])", ",".join(ids))}
    docs = []
    for o in sorted(rows, key=lambda r: ids.index(str(r["id"]))):
        o["content"] = full[str(o["id"])]["content"]
        content = _content(call, o)
        sigs = [{**s, "signed_at": _fmt_ts(call, s["signed_at"], o["site_id"])} for s in o["signatures"]]
        docs.append({"content": content, "status": o["status"], "signatures": sigs, "revision": o["revision"]})
    data = render_pdf(docs) if fmt == "pdf" else render_docx(docs)
    first = rows[0]["number"] if len(rows) == 1 else f"{len(rows)}-orders"
    name = re.sub(r"[^\w.\-]+", "_", f"production-order-{first}.{fmt}")
    call.tx.event("EXPORT", "production_orders", ids[0] if len(ids) == 1 else None, name,
                  {"format": fmt, "orders": [r["number"] for r in rows]})
    media = "application/pdf" if fmt == "pdf" else DOCX
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _fmt_ts(call: Call, ts, site_id) -> str:
    tz = call.tx.val("SELECT timezone FROM sites WHERE id = %s", site_id) or "UTC"
    if isinstance(ts, str):
        ts = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    from zoneinfo import ZoneInfo
    return ts.astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y %H:%M")
