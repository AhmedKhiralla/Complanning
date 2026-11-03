"""Complanning web application: JSON API under /api and the web app for everything else."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import settings
from .routers import audit_trail, auth, boms, company, excel, master, platform, production, rules, sample

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("complanning")

API_ROUTES = [
    Route("/api/health", lambda r: JSONResponse({"status": "ok"}), methods=["GET"]),
    # Authentication and personal settings
    Route("/api/auth/login", auth.login, methods=["POST"]),
    Route("/api/auth/logout", auth.logout, methods=["POST"]),
    Route("/api/auth/me", auth.me, methods=["GET"]),
    Route("/api/auth/change-password", auth.change_password, methods=["POST"]),
    Route("/api/auth/preferences", auth.preferences, methods=["PATCH"]),
    # Platform administration
    Route("/api/platform/tenants", platform.list_tenants, methods=["GET"]),
    Route("/api/platform/tenants", platform.create_tenant, methods=["POST"]),
    Route("/api/platform/tenants/{tenant_id}", platform.update_tenant, methods=["PATCH"]),
    Route("/api/platform/tenants/{tenant_id}/admins", platform.list_tenant_admins, methods=["GET"]),
    Route("/api/platform/tenants/{tenant_id}/admins", platform.create_tenant_admin, methods=["POST"]),
    Route("/api/platform/users/{user_id}/reset-password", platform.reset_tenant_admin_password, methods=["POST"]),
    # Company administration
    Route("/api/sites", company.list_sites, methods=["GET"]),
    Route("/api/sites", company.create_site, methods=["POST"]),
    Route("/api/sites/{site_id}", company.update_site, methods=["PATCH"]),
    Route("/api/users", company.list_users, methods=["GET"]),
    Route("/api/users", company.create_user, methods=["POST"]),
    Route("/api/users/{user_id}", company.update_user, methods=["PATCH"]),
    Route("/api/users/{user_id}/roles", company.set_user_roles, methods=["PUT"]),
    Route("/api/users/{user_id}/reset-password", company.reset_user_password, methods=["POST"]),
    Route("/api/users/{user_id}/unlock", company.unlock_user, methods=["POST"]),
    Route("/api/settings", company.get_settings, methods=["GET"]),
    Route("/api/settings/company", company.update_company, methods=["PATCH"]),
    Route("/api/settings/features", company.update_features, methods=["PUT"]),
    Route("/api/settings/terminology", company.update_terminology, methods=["PUT"]),
    Route("/api/settings/security", company.update_security, methods=["PUT"]),
    # Master data: company-wide
    Route("/api/uoms", master.list_uoms, methods=["GET"]),
    Route("/api/uoms", master.create_uom, methods=["POST"]),
    Route("/api/uoms/{uom_id}", master.update_uom, methods=["PATCH"]),
    Route("/api/items", master.list_items, methods=["GET"]),
    Route("/api/items", master.create_item, methods=["POST"]),
    Route("/api/items/{item_id}", master.get_item, methods=["GET"]),
    Route("/api/items/{item_id}", master.update_item, methods=["PATCH"]),
    Route("/api/items/{item_id}/conversions", master.set_conversions, methods=["PUT"]),
    Route("/api/items/{item_id}/markets", master.set_item_markets, methods=["PUT"]),
    Route("/api/items/{item_id}/prices", master.add_price, methods=["POST"]),
    Route("/api/prices/{price_id}/end", master.end_price, methods=["POST"]),
    Route("/api/markets", master.list_markets, methods=["GET"]),
    Route("/api/markets", master.create_market, methods=["POST"]),
    Route("/api/markets/{market_id}", master.update_market, methods=["PATCH"]),
    Route("/api/boms", boms.list_boms, methods=["GET"]),
    Route("/api/items/{item_id}/boms", boms.create_bom, methods=["POST"]),
    Route("/api/boms/{bom_id}", boms.get_bom, methods=["GET"]),
    Route("/api/boms/{bom_id}", boms.update_bom, methods=["PATCH"]),
    Route("/api/boms/{bom_id}", boms.discard_bom, methods=["DELETE"]),
    Route("/api/boms/{bom_id}/lines", boms.set_lines, methods=["PUT"]),
    Route("/api/boms/{bom_id}/activate", boms.activate_bom, methods=["POST"]),
    Route("/api/boms/{bom_id}/explode", boms.explode_bom, methods=["GET"]),
    # Master data: per site
    Route("/api/sites/{site_id}/resources", production.list_resources, methods=["GET"]),
    Route("/api/sites/{site_id}/resources", production.create_resource, methods=["POST"]),
    Route("/api/resources/{resource_id}", production.update_resource, methods=["PATCH"]),
    Route("/api/sites/{site_id}/downtime", production.list_exceptions, methods=["GET"]),
    Route("/api/sites/{site_id}/downtime", production.create_exception, methods=["POST"]),
    Route("/api/downtime/{exception_id}", production.delete_exception, methods=["DELETE"]),
    Route("/api/sites/{site_id}/routings", production.list_routings, methods=["GET"]),
    Route("/api/sites/{site_id}/routings/{item_id}", production.get_routing, methods=["GET"]),
    Route("/api/sites/{site_id}/routings/{item_id}", production.save_routing, methods=["PUT"]),
    Route("/api/sites/{site_id}/calendar", production.get_calendar, methods=["GET"]),
    Route("/api/sites/{site_id}/calendar/hours", production.calendar_hours, methods=["GET"]),
    Route("/api/sites/{site_id}/calendar/periods", production.create_period, methods=["POST"]),
    Route("/api/calendar/periods/{period_id}", production.delete_period, methods=["DELETE"]),
    Route("/api/sites/{site_id}/calendar/shifts", production.save_shifts, methods=["PUT"]),
    Route("/api/sites/{site_id}/holidays", production.add_holiday, methods=["POST"]),
    Route("/api/sites/{site_id}/holidays/import", production.import_holidays, methods=["POST"]),
    Route("/api/holidays/{holiday_id}", production.update_holiday, methods=["PATCH"]),
    Route("/api/holidays/{holiday_id}", production.delete_holiday, methods=["DELETE"]),
    # Planning rules
    Route("/api/cleaning-groups", rules.list_groups, methods=["GET"]),
    Route("/api/cleaning-groups", rules.create_group, methods=["POST"]),
    Route("/api/cleaning-groups/{group_id}", rules.update_group, methods=["PATCH"]),
    Route("/api/cleaning-groups/{group_id}", rules.delete_group, methods=["DELETE"]),
    Route("/api/sites/{site_id}/changeovers", rules.list_rules, methods=["GET"]),
    Route("/api/sites/{site_id}/changeovers", rules.create_rule, methods=["POST"]),
    Route("/api/sites/{site_id}/changeovers/matrix", rules.changeover_matrix, methods=["GET"]),
    Route("/api/sites/{site_id}/changeovers/resolve", rules.resolve_changeover, methods=["GET"]),
    Route("/api/changeovers/{rule_id}", rules.update_rule, methods=["PATCH"]),
    Route("/api/changeovers/{rule_id}", rules.delete_rule, methods=["DELETE"]),
    Route("/api/sites/{site_id}/campaigns", rules.list_campaigns, methods=["GET"]),
    Route("/api/sites/{site_id}/campaigns", rules.create_campaign, methods=["POST"]),
    Route("/api/campaigns/{campaign_id}", rules.update_campaign, methods=["PATCH"]),
    Route("/api/campaigns/{campaign_id}", rules.delete_campaign, methods=["DELETE"]),
    Route("/api/sites/{site_id}/equipment-holds", rules.list_equipment_holds, methods=["GET"]),
    Route("/api/sites/{site_id}/equipment-holds", rules.save_equipment_holds, methods=["PUT"]),
    Route("/api/item-times", rules.list_item_times, methods=["GET"]),
    Route("/api/item-times", rules.save_item_times, methods=["PUT"]),
    Route("/api/sites/{site_id}/sample-rules", sample.load_sample_rules, methods=["POST"]),
    # Excel and sample data
    Route("/api/master/template", excel.template, methods=["GET"]),
    Route("/api/master/import", excel.import_file, methods=["POST"]),
    Route("/api/master/export", excel.export_master, methods=["GET"]),
    Route("/api/sample-data", sample.load_sample, methods=["POST"]),
    # Audit trail
    Route("/api/audit", audit_trail.list_audit, methods=["GET"]),
    Route("/api/audit/facets", audit_trail.audit_facets, methods=["GET"]),
    Route("/api/audit/export", audit_trail.export_audit, methods=["GET"]),
]


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Content-Security-Policy",
                     "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com;"
                     " font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self';"
                     " frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if settings.cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def _frontend_routes() -> list:
    dist = Path(settings.frontend_dist).resolve()
    index = dist / "index.html"
    if not index.exists():
        log.warning("Web app build not found at %s; serving the API only.", dist)
        return [Route("/{path:path}", lambda r: PlainTextResponse(
            "The web app has not been built. Run the frontend build.", status_code=503))]

    async def spa(request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "Unknown API endpoint."}}, status_code=404)
        candidate = (dist / request.path_params.get("path", "")).resolve()
        if candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    routes = []
    if (dist / "assets").exists():
        routes.append(Mount("/assets", StaticFiles(directory=dist / "assets"), name="assets"))
    routes.append(Route("/{path:path}", spa))
    return routes


@asynccontextmanager
async def lifespan(app):
    if settings.run_migrations:
        from .migrate import bootstrap_platform_admin, migrate
        applied = migrate()
        if applied:
            log.info("Applied migrations: %s", ", ".join(applied))
        bootstrap_platform_admin()
    yield


def create_app(run_lifespan: bool = True) -> Starlette:
    return Starlette(routes=API_ROUTES + _frontend_routes(),
                     middleware=[Middleware(SecurityHeaders)],
                     lifespan=lifespan if run_lifespan else None)


app = create_app()
