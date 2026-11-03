"""Role checks for master data.

Company-wide data (units, items, markets, prices, bills of materials) can be edited by
company administrators and by anyone who is a master-data editor at any site.
Site data (machines, routings, calendars) can be edited by company administrators and by
master-data editors of that site. Any company user can read company-wide data; site data
is readable by administrators and by users with any role at that site.
"""
from __future__ import annotations

from .api import ApiError, Call


def _roles(call: Call) -> list[dict]:
    cached = getattr(call, "_roles", None)
    if cached is None:
        cached = call.tx.q("SELECT site_id::text AS site_id, role FROM user_site_roles WHERE user_id = %s",
                           call.user["id"])
        setattr(call, "_roles", cached)
    return cached


def can_edit_company(call: Call) -> bool:
    return bool(call.user["is_tenant_admin"]) or any(r["role"] == "master_data_editor" for r in _roles(call))


def require_company_edit(call: Call) -> None:
    if not can_edit_company(call):
        raise ApiError(403, "forbidden", "Master-data editor access is required to change this.")


def site_roles(call: Call, site_id: str) -> set[str]:
    return {r["role"] for r in _roles(call) if r["site_id"] == str(site_id)}


def require_site(call: Call, site_id: str, edit: bool = False) -> dict:
    """Return the site row after checking the caller may read (or edit) it."""
    site = call.tx.one("SELECT id, code, name, country, timezone, active FROM sites WHERE id = %s::uuid", str(site_id))
    if not site:
        raise ApiError(404, "not_found", "Site was not found.")
    if call.user["is_tenant_admin"]:
        return site
    roles = site_roles(call, site_id)
    if edit and "master_data_editor" not in roles:
        raise ApiError(403, "forbidden", "Master-data editor access at this site is required to change this.")
    if not roles:
        raise ApiError(403, "forbidden", "You do not have access to this site.")
    return site


def can_plan(call: Call, site_id: str) -> bool:
    return bool(call.user["is_tenant_admin"]) or "planner" in site_roles(call, site_id)


def require_plan(call: Call, site_id: str, edit: bool = False) -> dict:
    """Planning data (sales plan, stock, plans): planners of the site and administrators change it,
    anyone with a role at the site reads it."""
    site = require_site(call, site_id)
    if edit and not can_plan(call, site_id):
        raise ApiError(403, "forbidden", "Planner access at this site is required to change this.")
    return site
