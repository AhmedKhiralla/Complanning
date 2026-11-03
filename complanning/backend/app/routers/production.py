"""Site master data: machines (resources), downtime, routings and the working calendar."""
from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.request
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..api import ApiError, Call, endpoint, not_found
from ..holidays_builtin import builtin_holidays
from ..perms import require_site
from .master import _code, patch_row

log = logging.getLogger("complanning")


# ================================================================== resources
RES_SQL = """
SELECT r.id, r.site_id, r.code, r.name_en, r.name_ar, r.type, r.area, r.location, r.efficiency_pct, r.notes,
       r.active, r.updated_at, r.dirty_hold_hours, r.clean_hold_hours,
       (SELECT count(DISTINCT s.routing_id) FROM routing_step_resources sr JOIN routing_steps s ON s.id = sr.step_id
         WHERE sr.resource_id = r.id) AS routing_count
  FROM resources r
"""


class ResourceFields(BaseModel):
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    name_ar: str | None = Field(default=None, max_length=120)
    type: Literal["machine", "qc_lab", "room", "operator_group"] | None = None
    area: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=120)
    efficiency_pct: Decimal | None = Field(default=None, gt=0, le=100)
    notes: str | None = Field(default=None, max_length=500)
    active: bool | None = None
    dirty_hold_hours: Decimal | None = Field(default=None, gt=0, le=8760)
    clean_hold_hours: Decimal | None = Field(default=None, gt=0, le=8760)

    @field_validator("name_ar", "area", "location", "notes", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class ResourceIn(ResourceFields):
    code: str
    name_en: str = Field(min_length=1, max_length=120)

    @field_validator("code")
    @classmethod
    def _c(cls, v): return _code(v, 20).upper()


@endpoint(auth="tenant_user")
def list_resources(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid)
    return {"items": call.tx.q(RES_SQL + " WHERE r.site_id = %s::uuid ORDER BY r.active DESC, r.area NULLS LAST, r.code", sid)}


@endpoint(auth="tenant_user", body=ResourceIn)
def create_resource(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid, edit=True)
    b: ResourceIn = call.body
    if call.tx.val("SELECT 1 FROM resources WHERE site_id = %s::uuid AND code = %s", sid, b.code):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"code": "This code is already used at this site."})
    row = call.tx.one(
        "INSERT INTO resources (tenant_id, site_id, code, name_en, name_ar, type, area, location, efficiency_pct, notes)"
        " VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        call.tenant_id, sid, b.code, b.name_en.strip(), b.name_ar, b.type or "machine", b.area, b.location,
        b.efficiency_pct or Decimal(100), b.notes)
    return call.tx.one(RES_SQL + " WHERE r.id = %s", row["id"])


@endpoint(auth="tenant_user", body=ResourceFields)
def update_resource(call: Call):
    rid = call.path["resource_id"]
    r = call.tx.one("SELECT id, site_id FROM resources WHERE id = %s::uuid", rid)
    if not r:
        raise not_found("Machine")
    require_site(call, r["site_id"], edit=True)
    patch_row(call, "resources", rid, call.body, ("name_en", "name_ar", "type", "area", "location", "efficiency_pct", "notes", "active",
                                                  "dirty_hold_hours", "clean_hold_hours"))
    return call.tx.one(RES_SQL + " WHERE r.id = %s::uuid", rid)


# ------------------------------------------------------------------ downtime
class ExceptionIn(BaseModel):
    resource_id: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    reason: Literal["maintenance", "calibration", "qualification", "breakdown", "other"]
    notes: str | None = Field(default=None, max_length=300)


EXC_SQL = """
SELECT e.id, e.resource_id, r.code AS resource_code, r.name_en AS resource_name_en, r.name_ar AS resource_name_ar,
       e.starts_at, e.ends_at, e.reason, e.notes
  FROM resource_exceptions e JOIN resources r ON r.id = e.resource_id
"""


@endpoint(auth="tenant_user")
def list_exceptions(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid)
    return {"items": call.tx.q(EXC_SQL + " WHERE e.site_id = %s::uuid AND e.ends_at >= now() - interval '90 days'"
                               " ORDER BY e.starts_at", sid)}


@endpoint(auth="tenant_user", body=ExceptionIn)
def create_exception(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid, edit=True)
    b: ExceptionIn = call.body
    if b.ends_at <= b.starts_at:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"ends_at": "The end must be after the start."})
    if not call.tx.val("SELECT 1 FROM resources WHERE id = %s::uuid AND site_id = %s::uuid", b.resource_id, sid):
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"resource_id": "Choose a machine at this site."})
    row = call.tx.one("INSERT INTO resource_exceptions (tenant_id, site_id, resource_id, starts_at, ends_at, reason, notes)"
                      " VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s) RETURNING id",
                      call.tenant_id, sid, b.resource_id, b.starts_at, b.ends_at, b.reason, (b.notes or "").strip() or None)
    return call.tx.one(EXC_SQL + " WHERE e.id = %s", row["id"])


@endpoint(auth="tenant_user")
def delete_exception(call: Call):
    e = call.tx.one("SELECT id, site_id FROM resource_exceptions WHERE id = %s::uuid", call.path["exception_id"])
    if not e:
        raise not_found("Downtime")
    require_site(call, e["site_id"], edit=True)
    call.tx.x("DELETE FROM resource_exceptions WHERE id = %s", e["id"])
    return {"ok": True}


# ================================================================== routings
@endpoint(auth="tenant_user")
def list_routings(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid)
    rows = call.tx.q(
        """SELECT i.id AS item_id, i.code, i.name_en, i.name_ar, i.type, rt.id AS routing_id, rt.updated_at,
                  (SELECT count(*) FROM routing_steps s WHERE s.routing_id = rt.id) AS step_count,
                  coalesce((SELECT json_agg(DISTINCT r.code) FROM routing_steps s
                              JOIN routing_step_resources sr ON sr.step_id = s.id
                              JOIN resources r ON r.id = sr.resource_id WHERE s.routing_id = rt.id), '[]'::json) AS machines
             FROM items i LEFT JOIN routings rt ON rt.item_id = i.id AND rt.site_id = %s::uuid
            WHERE i.type IN ('wip', 'semi_finished', 'finished') AND i.active
            ORDER BY CASE i.type WHEN 'finished' THEN 1 WHEN 'semi_finished' THEN 2 ELSE 3 END, i.code""", sid)
    return {"items": rows}


def _routing(call: Call, site_id: str, item_id: str) -> dict:
    item = call.tx.one("SELECT i.id, i.code, i.name_en, i.name_ar, i.type, u.code AS stock_uom FROM items i"
                       " JOIN uoms u ON u.id = i.stock_uom_id WHERE i.id = %s::uuid", item_id)
    if not item:
        raise not_found("Item")
    rt = call.tx.one("SELECT id, notes, updated_at FROM routings WHERE site_id = %s::uuid AND item_id = %s::uuid", site_id, item_id)
    steps = []
    if rt:
        steps = call.tx.q(
            """SELECT s.id, s.seq, s.name, s.time_model, s.fixed_minutes, s.rate_per_hour, s.setup_minutes,
                      coalesce((SELECT json_agg(json_build_object('id', sr.id, 'resource_id', sr.resource_id, 'preferred', sr.preferred,
                                 'fixed_minutes', sr.fixed_minutes, 'rate_per_hour', sr.rate_per_hour)
                                 ORDER BY sr.preferred DESC, sr.created_at)
                         FROM routing_step_resources sr WHERE sr.step_id = s.id), '[]'::json) AS resources
                 FROM routing_steps s WHERE s.routing_id = %s ORDER BY s.seq""", rt["id"])
    batch = call.tx.one("SELECT b.batch_size, u.code AS batch_uom FROM boms b JOIN uoms u ON u.id = b.batch_uom_id"
                        " WHERE b.item_id = %s::uuid AND b.status = 'active'", item_id)
    return {"item": item, "routing": rt, "steps": steps, "active_batch": batch}


@endpoint(auth="tenant_user")
def get_routing(call: Call):
    sid, iid = call.path["site_id"], call.path["item_id"]
    require_site(call, sid)
    return _routing(call, sid, iid)


class StepResourceIn(BaseModel):
    resource_id: str
    preferred: bool = False
    fixed_minutes: Decimal | None = Field(default=None, gt=0)
    rate_per_hour: Decimal | None = Field(default=None, gt=0)


class StepIn(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    time_model: Literal["fixed", "rate"]
    fixed_minutes: Decimal | None = Field(default=None, gt=0)
    rate_per_hour: Decimal | None = Field(default=None, gt=0)
    setup_minutes: Decimal = Field(default=Decimal(0), ge=0)
    resources: list[StepResourceIn] = Field(default_factory=list)


class RoutingIn(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)
    steps: list[StepIn]


@endpoint(auth="tenant_user", body=RoutingIn)
def save_routing(call: Call):
    sid, iid = call.path["site_id"], call.path["item_id"]
    require_site(call, sid, edit=True)
    item = call.tx.one("SELECT id, type FROM items WHERE id = %s::uuid", iid)
    if not item:
        raise not_found("Item")
    if item["type"] not in ("wip", "semi_finished", "finished"):
        raise ApiError(422, "not_producible", "Only produced items have routings.")
    b: RoutingIn = call.body
    site_res = {str(r["id"]) for r in call.tx.q("SELECT id FROM resources WHERE site_id = %s::uuid AND active", sid)}
    errors: dict[str, str] = {}
    for i, s in enumerate(b.steps):
        if s.time_model == "fixed" and not s.fixed_minutes:
            errors[f"steps.{i}"] = "Enter the minutes per batch."
        elif s.time_model == "rate" and not s.rate_per_hour:
            errors[f"steps.{i}"] = "Enter the output per hour."
        elif not s.resources:
            errors[f"steps.{i}"] = "Drop at least one qualified machine on this step."
        elif any(r.resource_id not in site_res for r in s.resources):
            errors[f"steps.{i}"] = "Use active machines of this site."
        elif len({r.resource_id for r in s.resources}) != len(s.resources):
            errors[f"steps.{i}"] = "A machine is listed twice on this step."
    if errors:
        raise ApiError(422, "invalid", "Some steps need attention.", fields=errors)

    rt = call.tx.one("SELECT id, notes FROM routings WHERE site_id = %s::uuid AND item_id = %s::uuid", sid, iid)
    if not rt:
        rt = call.tx.one("INSERT INTO routings (tenant_id, site_id, item_id, notes) VALUES (%s, %s::uuid, %s::uuid, %s) RETURNING id, notes",
                         call.tenant_id, sid, iid, b.notes)
    elif (b.notes or None) != rt["notes"]:
        call.tx.x("UPDATE routings SET notes = %s WHERE id = %s", b.notes, rt["id"])

    existing = {str(r["id"]): r for r in call.tx.q("SELECT id FROM routing_steps WHERE routing_id = %s", rt["id"])}
    keep = {s.id for s in b.steps if s.id and s.id in existing}
    for step_id in existing:
        if step_id not in keep:
            call.tx.x("DELETE FROM routing_step_resources WHERE step_id = %s::uuid", step_id)
            call.tx.x("DELETE FROM routing_steps WHERE id = %s::uuid", step_id)
    for seq, s in enumerate(b.steps, start=1):
        fixed = s.fixed_minutes if s.time_model == "fixed" else None
        rate = s.rate_per_hour if s.time_model == "rate" else None
        if s.id and s.id in existing:
            step_id = s.id
            call.tx.x("UPDATE routing_steps SET seq = %s, name = %s, time_model = %s, fixed_minutes = %s, rate_per_hour = %s,"
                      " setup_minutes = %s WHERE id = %s::uuid", seq, s.name.strip(), s.time_model, fixed, rate, s.setup_minutes, step_id)
        else:
            step_id = str(call.tx.val(
                "INSERT INTO routing_steps (tenant_id, routing_id, seq, name, time_model, fixed_minutes, rate_per_hour, setup_minutes)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                call.tenant_id, rt["id"], seq, s.name.strip(), s.time_model, fixed, rate, s.setup_minutes))
        # Exactly one preferred machine per step: the first marked, otherwise the first listed.
        pref_index = next((i for i, r in enumerate(s.resources) if r.preferred), 0)
        current = {str(r["resource_id"]): r for r in call.tx.q(
            "SELECT id, resource_id, preferred, fixed_minutes, rate_per_hour FROM routing_step_resources WHERE step_id = %s::uuid", step_id)}
        wanted = {r.resource_id: (r, i == pref_index) for i, r in enumerate(s.resources)}
        for res_id, row in current.items():
            if res_id not in wanted:
                call.tx.x("DELETE FROM routing_step_resources WHERE id = %s", row["id"])
        for res_id, (r, pref) in wanted.items():
            rf = r.fixed_minutes if s.time_model == "fixed" else None
            rr = r.rate_per_hour if s.time_model == "rate" else None
            if res_id in current:
                row = current[res_id]
                if row["preferred"] != pref or row["fixed_minutes"] != rf or row["rate_per_hour"] != rr:
                    call.tx.x("UPDATE routing_step_resources SET preferred = %s, fixed_minutes = %s, rate_per_hour = %s WHERE id = %s",
                              pref, rf, rr, row["id"])
            else:
                call.tx.x("INSERT INTO routing_step_resources (tenant_id, step_id, resource_id, preferred, fixed_minutes, rate_per_hour)"
                          " VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s)", call.tenant_id, step_id, res_id, pref, rf, rr)
    return _routing(call, sid, iid)


# ================================================================== calendar
class PeriodIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    start_date: dt.date
    end_date: dt.date


class ShiftIn(BaseModel):
    weekday: int = Field(ge=1, le=7)
    name: str = Field(min_length=1, max_length=40)
    start_time: dt.time
    end_time: dt.time


class ShiftsIn(BaseModel):
    period_id: str | None = None
    shifts: list[ShiftIn]


class HolidayIn(BaseModel):
    date: dt.date
    name: str = Field(min_length=1, max_length=120)


class HolidayPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    confirmed: bool | None = None


class ImportIn(BaseModel):
    year: int = Field(ge=2020, le=2100)


def _shift_hours(start: dt.time, end: dt.time) -> float:
    s = start.hour * 60 + start.minute
    e = end.hour * 60 + end.minute
    if e <= s:
        e += 24 * 60
    return (e - s) / 60


def _calendar(call: Call, sid: str, year: int) -> dict:
    periods = call.tx.q("SELECT id, name, start_date, end_date FROM calendar_periods WHERE site_id = %s::uuid ORDER BY start_date", sid)
    shifts = call.tx.q("SELECT id, period_id, weekday, name, start_time, end_time FROM shifts WHERE site_id = %s::uuid"
                       " ORDER BY period_id NULLS FIRST, weekday, start_time", sid)
    holidays = call.tx.q("SELECT id, date, name, source, estimated, confirmed FROM holidays WHERE site_id = %s::uuid"
                         " AND extract(year FROM date) = %s ORDER BY date", sid, year)
    for s in shifts:
        s["hours"] = _shift_hours(s["start_time"], s["end_time"])
        s["start_time"] = s["start_time"].strftime("%H:%M")
        s["end_time"] = s["end_time"].strftime("%H:%M")
    return {"year": year, "periods": periods, "shifts": shifts, "holidays": holidays}


def _year(call: Call) -> int:
    try:
        return int(call.query.get("year") or call.tx.val("SELECT extract(year FROM current_date)::int"))
    except ValueError:
        raise ApiError(422, "invalid", "Year must be a number.")


@endpoint(auth="tenant_user")
def get_calendar(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid)
    return _calendar(call, sid, _year(call))


@endpoint(auth="tenant_user")
def calendar_hours(call: Call):
    """Available hours per day for a month, after holidays (confirmed ones) and period patterns."""
    sid = call.path["site_id"]
    require_site(call, sid)
    try:
        month = dt.date.fromisoformat((call.query.get("month") or "") + "-01")
    except ValueError:
        month = call.tx.val("SELECT date_trunc('month', current_date)::date")
    nxt = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    periods = call.tx.q("SELECT id, name, start_date, end_date FROM calendar_periods WHERE site_id = %s::uuid", sid)
    shifts = call.tx.q("SELECT period_id, weekday, start_time, end_time FROM shifts WHERE site_id = %s::uuid", sid)
    hols = {r["date"]: r for r in call.tx.q("SELECT date, name, confirmed FROM holidays WHERE site_id = %s::uuid"
                                           " AND date >= %s AND date < %s", sid, month, nxt)}
    days = []
    d = month
    while d < nxt:
        period = next((p for p in periods if p["start_date"] <= d <= p["end_date"]), None)
        pid = period["id"] if period else None
        day_shifts = [s for s in shifts if s["period_id"] == pid and s["weekday"] == d.isoweekday()]
        if period and not any(s["period_id"] == pid for s in shifts):
            day_shifts = [s for s in shifts if s["period_id"] is None and s["weekday"] == d.isoweekday()]
        hours = sum(_shift_hours(s["start_time"], s["end_time"]) for s in day_shifts)
        h = hols.get(d)
        if h and h["confirmed"]:
            hours = 0
        days.append({"date": d, "hours": hours, "holiday": h["name"] if h else None,
                     "holiday_confirmed": bool(h and h["confirmed"]), "period": period["name"] if period else None})
        d += dt.timedelta(days=1)
    return {"month": month, "days": days, "total_hours": sum(x["hours"] for x in days)}


@endpoint(auth="tenant_user", body=PeriodIn)
def create_period(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid, edit=True)
    b: PeriodIn = call.body
    if b.end_date < b.start_date:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"end_date": "The end must be on or after the start."})
    overlap = call.tx.val("SELECT name FROM calendar_periods WHERE site_id = %s::uuid AND start_date <= %s AND end_date >= %s",
                          sid, b.end_date, b.start_date)
    if overlap:
        raise ApiError(422, "invalid", "Some fields need attention.", fields={"start_date": f"Overlaps the period “{overlap}”."})
    call.tx.x("INSERT INTO calendar_periods (tenant_id, site_id, name, start_date, end_date) VALUES (%s, %s::uuid, %s, %s, %s)",
              call.tenant_id, sid, b.name.strip(), b.start_date, b.end_date)
    return _calendar(call, sid, b.start_date.year)


@endpoint(auth="tenant_user")
def delete_period(call: Call):
    p = call.tx.one("SELECT id, site_id, start_date FROM calendar_periods WHERE id = %s::uuid", call.path["period_id"])
    if not p:
        raise not_found("Period")
    require_site(call, p["site_id"], edit=True)
    call.tx.x("DELETE FROM shifts WHERE period_id = %s", p["id"])
    call.tx.x("DELETE FROM calendar_periods WHERE id = %s", p["id"])
    return _calendar(call, str(p["site_id"]), p["start_date"].year)


@endpoint(auth="tenant_user", body=ShiftsIn)
def save_shifts(call: Call):
    """Replace the weekly shift pattern for the default calendar or for one period."""
    sid = call.path["site_id"]
    require_site(call, sid, edit=True)
    b: ShiftsIn = call.body
    if b.period_id and not call.tx.val("SELECT 1 FROM calendar_periods WHERE id = %s::uuid AND site_id = %s::uuid", b.period_id, sid):
        raise ApiError(422, "invalid", "Unknown period.")
    for day in range(1, 8):
        total = sum(_shift_hours(s.start_time, s.end_time) for s in b.shifts if s.weekday == day)
        if total > 24:
            raise ApiError(422, "invalid", "Shifts on one day cannot add up to more than 24 hours.")
    pid_sql = "period_id = %s::uuid" if b.period_id else "period_id IS NULL"
    pid_args = [b.period_id] if b.period_id else []
    current = call.tx.q(f"SELECT id, weekday, name, start_time, end_time FROM shifts WHERE site_id = %s::uuid AND {pid_sql}", sid, *pid_args)
    key = lambda w, n, s, e: (int(w), n, s.strftime("%H:%M"), e.strftime("%H:%M"))
    wanted = {key(s.weekday, s.name.strip(), s.start_time, s.end_time) for s in b.shifts}
    have = {key(r["weekday"], r["name"], r["start_time"], r["end_time"]): r["id"] for r in current}
    for k, rid in have.items():
        if k not in wanted:
            call.tx.x("DELETE FROM shifts WHERE id = %s", rid)
    for k in wanted - set(have):
        call.tx.x("INSERT INTO shifts (tenant_id, site_id, period_id, weekday, name, start_time, end_time)"
                  " VALUES (%s, %s::uuid, %s, %s, %s, %s, %s)", call.tenant_id, sid, b.period_id, k[0], k[1], k[2], k[3])
    return _calendar(call, sid, _year(call))


@endpoint(auth="tenant_user", body=HolidayIn)
def add_holiday(call: Call):
    sid = call.path["site_id"]
    require_site(call, sid, edit=True)
    b: HolidayIn = call.body
    if call.tx.val("SELECT 1 FROM holidays WHERE site_id = %s::uuid AND date = %s", sid, b.date):
        raise ApiError(409, "duplicate", "Some fields need attention.", fields={"date": "There is already a day off on this date."})
    call.tx.x("INSERT INTO holidays (tenant_id, site_id, date, name) VALUES (%s, %s::uuid, %s, %s)",
              call.tenant_id, sid, b.date, b.name.strip())
    return _calendar(call, sid, b.date.year)


@endpoint(auth="tenant_user", body=HolidayPatch)
def update_holiday(call: Call):
    h = call.tx.one("SELECT id, site_id, date FROM holidays WHERE id = %s::uuid", call.path["holiday_id"])
    if not h:
        raise not_found("Day off")
    require_site(call, h["site_id"], edit=True)
    patch_row(call, "holidays", str(h["id"]), call.body, ("name", "confirmed"))
    return _calendar(call, str(h["site_id"]), h["date"].year)


@endpoint(auth="tenant_user")
def delete_holiday(call: Call):
    h = call.tx.one("SELECT id, site_id, date FROM holidays WHERE id = %s::uuid", call.path["holiday_id"])
    if not h:
        raise not_found("Day off")
    require_site(call, h["site_id"], edit=True)
    call.tx.x("DELETE FROM holidays WHERE id = %s", h["id"])
    return _calendar(call, str(h["site_id"]), h["date"].year)


def _fetch_nager(year: int, country: str) -> list[dict] | None:
    url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Complanning/0.2", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read() or b"[]")
        out = []
        for h in data if isinstance(data, list) else []:
            if h.get("global", True):
                out.append({"date": dt.date.fromisoformat(h["date"]), "name": h.get("name") or h.get("localName"),
                            "estimated": False})
        return out or None
    except Exception as e:  # network blocked, unsupported country, bad payload
        log.info("Holiday service unavailable for %s %s: %s", country, year, e)
        return None


@endpoint(auth="tenant_user", body=ImportIn)
def import_holidays(call: Call):
    """Add national holidays as proposals (unconfirmed) that the planner confirms one by one."""
    sid = call.path["site_id"]
    site = require_site(call, sid, edit=True)
    year = call.body.year
    country = site["country"].strip().upper()
    source = "service"
    found = _fetch_nager(year, country)
    if not found:
        found = builtin_holidays(country, year)
        source = "built-in"
    if not found:
        raise ApiError(422, "no_holidays", f"No holiday list is available for {country} {year}. Add the days off by hand.")
    existing = {r["date"] for r in call.tx.q("SELECT date FROM holidays WHERE site_id = %s::uuid", sid)}
    added = 0
    for h in found:
        if h["date"].year != year or h["date"] in existing:
            continue
        call.tx.x("INSERT INTO holidays (tenant_id, site_id, date, name, source, estimated, confirmed)"
                  " VALUES (%s, %s::uuid, %s, %s, 'imported', %s, false)", call.tenant_id, sid, h["date"], h["name"], h["estimated"])
        existing.add(h["date"])
        added += 1
    data = _calendar(call, sid, year)
    data["imported"] = {"added": added, "source": source, "country": country}
    return data
