import { LuBuilding2, LuListChecks, LuPlus } from "react-icons/lu";
import { GetStarted, useGuidePrefs } from "../components/guide";
import { Button, LoadError, useLoad } from "../components/ui";
import { get } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Link, navigate } from "../lib/router";
import { useSession } from "../lib/session";

function firstName(name: string) {
  return name.trim().split(/\s+/)[0] ?? name;
}

function PlatformHome() {
  const { t, number } = useI18n();
  const { data, error, reload } = useLoad(() => get<{ items: { status: string; user_count: number; site_count: number }[] }>("/api/platform/tenants"));
  const items = data?.items ?? [];
  return (
    <div className="home-grid">
      <section className="panel" aria-labelledby="co-h">
        <div className="panel-head">
          <h2 id="co-h">{t("home.companies")}</h2><span className="spacer" />
          <Button size="sm" variant="primary" icon={<LuPlus />} onClick={() => navigate("/companies?new=1")}>{t("home.newCompany")}</Button>
        </div>
        {error ? <LoadError error={error} onRetry={reload} /> : (
          <div className="stat-line">
            <div><strong>{data ? number(items.filter((x) => x.status === "active").length) : "–"}</strong><span>{t("home.activeCompanies")}</span></div>
            <div><strong>{data ? number(items.reduce((a, x) => a + x.site_count, 0)) : "–"}</strong><span>{t("home.totalSites")}</span></div>
            <div><strong>{data ? number(items.reduce((a, x) => a + x.user_count, 0)) : "–"}</strong><span>{t("home.totalUsers")}</span></div>
          </div>
        )}
        <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}>
          <Link to="/companies" className="row"><LuBuilding2 aria-hidden />{t("companies.title")}</Link>
        </div>
      </section>
    </div>
  );
}

export function Home() {
  const { t, tx } = useI18n();
  const { me } = useSession();
  const guide = useGuidePrefs();
  if (!me) return null;
  const u = me.user;
  let lead: string;
  if (u.is_platform_admin) lead = t("home.leadPlatform");
  else if (u.is_tenant_admin) lead = t("home.leadAdmin", { company: me.tenant?.name ?? "" });
  else lead = t("home.leadUser", { sites: me.sites.map((s) => s.name).join(", ") || "—" });

  return (
    <>
      <div className="home-hello">
        <h1>{t("home.hello", { name: firstName(u.full_name) })}</h1>
        <p className="muted">{lead}</p>
      </div>
      {u.is_platform_admin ? <PlatformHome /> : (
        <div className="stack">
          {!guide.hidden && <GetStarted />}
          {!u.is_tenant_admin && (
            <section className="panel" aria-labelledby="mysites-h">
              <div className="panel-head"><h2 id="mysites-h">{t("nav.sites")}</h2></div>
              <ul className="steps">
                {me.sites.map((s) => (
                  <li key={s.id}>
                    <span className="text"><strong>{s.code} · {s.name}</strong>
                      <span>{s.roles.map((r) => tx(`role.${r}`, r)).join(", ")}</span></span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {guide.hidden && <div><Button size="sm" variant="ghost" icon={<LuListChecks />} onClick={() => guide.save({ checklist_hidden: false })}>{t("gs.show")}</Button></div>}
        </div>
      )}
    </>
  );
}
