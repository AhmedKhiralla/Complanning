"""Production orders: templates, batch numbers, generating orders, electronic approval, issue, reissue and files."""
import datetime as dt
import io
import zipfile

import pytest

from conftest import sign_in_first_time


@pytest.fixture(scope="module")
def co(server, platform):
    status, body, _ = platform.post("/api/platform/tenants", {
        "code": "ORDERS", "name": "Orders Pharma", "admin": {"email": "admin@orders.test", "full_name": "Olga Admin"}})
    assert status == 200, body
    admin = sign_in_first_time(server, "admin@orders.test", body["temporary_password"], "Orders#Admin2026")
    assert admin.post("/api/sample-data")[0] == 200
    _, sites, _ = admin.get("/api/sites")
    sid = sites["items"][0]["id"]
    start = dt.date.today()
    status, p, _ = admin.post(f"/api/sites/{sid}/plans", {
        "horizon_start": start.isoformat(), "horizon_end": (start + dt.timedelta(days=40)).isoformat(), "material_constraints": False})
    assert status == 200, p
    return {"admin": admin, "sid": sid, "plan": p, "server": server}


def test_default_templates(co):
    a = co["admin"]
    status, t, _ = a.get("/api/order-templates")
    assert status == 200
    kinds = {x["kind"] for x in t["items"] if x["is_default"]}
    assert kinds == {"packaging", "manufacturing"}
    pk = next(x for x in t["items"] if x["kind"] == "packaging")
    assert pk["title"] == "Packaging Order" and pk["number_pattern"] == "{YY}-{MM}-{BATCH}P"
    assert [c["key"] for c in pk["columns"]][:3] == ["ser", "name", "code"]
    assert len(pk["signatures"]) == 5
    # A preview renders without saving.
    status, pdf, h = a.call("POST", "/api/order-templates/preview?kind=packaging", {**pk, "title": "My packaging order"}, raw=True)
    assert status == 200 and pdf[:4] == b"%PDF"


def test_orders_need_a_released_plan_and_batch_numbers(co):
    a, p, sid = co["admin"], co["plan"], co["sid"]
    _, full, _ = a.get(f"/api/plans/{p['id']}")
    bids = [b["id"] for b in full["batches"] if b["status"] == "scheduled"]
    status, err, _ = a.post(f"/api/plans/{p['id']}/orders", {"batch_ids": bids, "kinds": ["packaging"]})
    assert status == 409 and err["error"]["code"] == "not_released"
    assert a.post(f"/api/plans/{p['id']}/release")[0] == 200
    status, err, _ = a.post(f"/api/plans/{p['id']}/orders", {"batch_ids": bids, "kinds": ["packaging"]})
    assert status == 422 and err["error"]["code"] == "no_batch_numbers"
    # A pattern must count, so every batch gets its own number.
    status, err, _ = a.put(f"/api/sites/{sid}/batch-numbering", {"pattern": "{YY}", "next": 1})
    assert status == 422
    status, num, _ = a.put(f"/api/sites/{sid}/batch-numbering", {"pattern": "{YY}{SEQ:3}", "next": 13})
    assert status == 200 and num["example"] == f"{dt.date.today().year % 100:02d}013"
    status, filled, _ = a.post(f"/api/plans/{p['id']}/batch-numbers/fill", {})
    assert status == 200 and filled["filled"] == len(bids)
    values = list(filled["batch_numbers"].values())
    assert len(values) == len(set(values))
    _, full, _ = a.get(f"/api/plans/{p['id']}")
    assert all(b["lot_no"] for b in full["batches"] if b["status"] == "scheduled")


def test_generate_edit_and_download(co):
    a, p = co["admin"], co["plan"]
    _, full, _ = a.get(f"/api/plans/{p['id']}")
    bids = [b["id"] for b in full["batches"] if b["status"] == "scheduled"]
    status, res, _ = a.post(f"/api/plans/{p['id']}/orders", {"batch_ids": bids, "kinds": ["packaging", "manufacturing"]})
    assert status == 200, res
    assert res["created"]
    kinds = {o["kind"] for o in res["orders"]}
    assert kinds == {"packaging", "manufacturing"}
    # Batches without the listed materials are skipped, and a second run does not duplicate.
    assert any(s["reason"] == "no_components" for s in res["skipped"])
    status, again, _ = a.post(f"/api/plans/{p['id']}/orders", {"batch_ids": bids, "kinds": ["packaging"]})
    assert status == 200 and not again["created"] and all(s["reason"] in ("exists", "no_components") for s in again["skipped"])
    pk = next(o for o in res["orders"] if o["kind"] == "packaging")
    assert pk["number"] == f"{dt.date.today():%y-%m}-{pk['batch_number']}P" and pk["status"] == "draft"
    # Changing the batch number renames the draft order.
    status, _r, _ = a.put(f"/api/plans/{p['id']}/batch-numbers", {"numbers": {pk["batch_id"]: "X-777"}})
    assert status == 200
    _, lst, _ = a.get(f"/api/plans/{p['id']}/orders")
    pk2 = next(o for o in lst["orders"] if o["id"] == pk["id"])
    assert pk2["batch_number"] == "X-777" and pk2["number"].endswith("X-777P")
    # Duplicate batch numbers within a plan are refused.
    other = next(b for b in bids if b != pk["batch_id"])
    status, err, _ = a.put(f"/api/plans/{p['id']}/batch-numbers", {"numbers": {other: "X-777"}})
    assert status == 422 and err["error"]["code"] == "duplicate_batch_number"
    # Files: one PDF or Word file for many orders.
    ids = ",".join(o["id"] for o in lst["orders"][:3])
    status, pdf, h = a.call("GET", f"/api/orders/file?ids={ids}&format=pdf", raw=True)
    assert status == 200 and pdf[:4] == b"%PDF" and h["Content-Type"] == "application/pdf"
    status, docx, h = a.call("GET", f"/api/orders/file?ids={ids}&format=docx", raw=True)
    assert status == 200 and docx[:2] == b"PK"
    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()
    assert "Req. quantity" in xml or "Item Name" in xml
    _, audit, _ = a.get("/api/audit?entity=production_orders&page_size=50")
    assert any(e["action"] == "EXPORT" for e in audit["items"])


def test_electronic_approval_issue_and_reissue(co):
    a, p, sid = co["admin"], co["plan"], co["sid"]
    _, t, _ = a.get("/api/order-templates")
    pk = next(x for x in t["items"] if x["kind"] == "packaging")
    body = {k: pk[k] for k in ("name", "title", "format_number", "number_pattern", "next_seq", "orientation", "logo",
                               "header_columns", "header_fields", "columns", "component_types", "signatures",
                               "remarks_label", "remarks_lines", "footer_note", "active")}
    body.update(require_esign=True, signatures=[{"title": "Planning"}, {"title": "Quality Assurance"}])
    status, saved, _ = a.put(f"/api/order-templates/{pk['id']}", body)
    assert status == 200 and saved["require_esign"] is True
    # Only administrators change templates.
    status, u, _ = a.post("/api/users", {"email": "qa@orders.test", "full_name": "Qasim QA", "roles": [{"site_id": sid, "role": "planner"}]})
    assert status == 200, u
    qa = sign_in_first_time(co["server"], "qa@orders.test", u["temporary_password"], "Orders#QA2026x")
    assert qa.put(f"/api/order-templates/{pk['id']}", body)[0] == 403

    _, lst, _ = a.get(f"/api/plans/{p['id']}/orders")
    order = next(o for o in lst["orders"] if o["kind"] == "packaging")
    # Not issued before every level has signed.
    status, err, _ = a.post("/api/orders/issue", {"order_ids": [order["id"]]})
    assert status == 409 and err["error"]["code"] == "not_approved"
    status, err, _ = a.post("/api/orders/sign", {"order_ids": [order["id"]], "password": "wrong"})
    assert status == 403
    _, audit, _ = a.get("/api/audit?page_size=20")
    assert any(e["action"] == "SIGNATURE_FAILED" for e in audit["items"])
    status, res, _ = a.post("/api/orders/sign", {"order_ids": [order["id"]], "password": "Orders#Admin2026"})
    assert status == 200 and res["orders"][0]["signatures"][0]["title"] == "Planning"
    status, err, _ = a.post("/api/orders/sign", {"order_ids": [order["id"]], "password": "Orders#Admin2026"})
    assert status == 409 and err["error"]["code"] == "already_signed"
    status, res, _ = qa.post("/api/orders/sign", {"order_ids": [order["id"]], "password": "Orders#QA2026x"})
    assert status == 200 and res["orders"][0]["status"] == "approved"
    status, res, _ = a.post("/api/orders/issue", {"order_ids": [order["id"]]})
    assert status == 200 and res["orders"][0]["status"] == "issued"
    # The issued order keeps its content; a later batch number change marks it outdated, and reissue makes revision 1.
    status, _r, _ = a.put(f"/api/plans/{p['id']}/batch-numbers", {"numbers": {order["batch_id"]: "Z-100"}})
    assert status == 200
    _, lst, _ = a.get(f"/api/plans/{p['id']}/orders")
    issued = next(o for o in lst["orders"] if o["id"] == order["id"])
    assert issued["outdated"] is True
    status, pdf, _ = a.call("GET", f"/api/orders/file?ids={order['id']}&format=pdf", raw=True)
    assert status == 200 and pdf[:4] == b"%PDF"
    assert a.post("/api/orders/reissue", {"order_ids": [order["id"]], "reason": ""})[0] == 422
    status, rr, _ = a.post("/api/orders/reissue", {"order_ids": [order["id"]], "reason": "Batch number corrected"})
    assert status == 200 and len(rr["created"]) == 1
    _, lst, _ = a.get(f"/api/plans/{p['id']}/orders")
    new = next(o for o in lst["orders"] if o["id"] == rr["created"][0])
    old = next(o for o in lst["orders"] if o["id"] == order["id"])
    assert new["revision"] == 1 and new["batch_number"] == "Z-100" and new["status"] == "draft"
    assert old["status"] == "cancelled" and "revision 1" in old["cancel_reason"]
    # Drafts can be deleted; cancelling needs a reason.
    assert a.post("/api/orders/cancel", {"order_ids": [new["id"]], "reason": "x"})[0] == 422
    assert a.post("/api/orders/delete", {"order_ids": [new["id"]]})[0] == 200


def test_yearly_restart(co, db_url):
    """With the yearly option, the counter goes back to 1 with the first batch numbered in a new year."""
    import psycopg
    a, sid = co["admin"], co["sid"]
    status, n, _ = a.put(f"/api/sites/{sid}/batch-numbering", {"pattern": "{YY}{SEQ:3}", "next": 57, "yearly": True})
    assert status == 200 and n["yearly"] is True and n["next"] == 57
    # Pretend the counter was last used last year.
    conn = psycopg.connect(db_url)
    conn.execute("UPDATE sites SET batch_number_year = batch_number_year - 1 WHERE id = %s", (sid,))
    conn.commit()
    conn.close()
    _, n, _ = a.get(f"/api/sites/{sid}/batch-numbering")
    assert n["next"] == 1 and n["example"] == f"{dt.date.today().year % 100:02d}001"
    status, n, _ = a.put(f"/api/sites/{sid}/batch-numbering", {"pattern": "{YY}{SEQ:3}", "next": 57, "yearly": False})
    assert n["next"] == 57


def test_fill_skips_numbers_on_orders(co):
    """Filling numbers on another plan never reuses a batch number that is already on an order of the site."""
    a, sid = co["admin"], co["sid"]
    _, lst, _ = a.get(f"/api/plans/{co['plan']['id']}/orders")
    taken = {o["batch_number"] for o in lst["orders"] if o["status"] != "cancelled"}
    start = dt.date.today()
    _, p2, _ = a.post(f"/api/sites/{sid}/plans", {"horizon_start": start.isoformat(),
                                                  "horizon_end": (start + dt.timedelta(days=40)).isoformat(), "material_constraints": False})
    assert a.put(f"/api/sites/{sid}/batch-numbering", {"pattern": "{YY}{SEQ:3}", "next": 13})[0] == 200
    status, filled, _ = a.post(f"/api/plans/{p2['id']}/batch-numbers/fill", {})
    assert status == 200 and filled["filled"] > 0
    assert not (set(filled["batch_numbers"].values()) & taken)
