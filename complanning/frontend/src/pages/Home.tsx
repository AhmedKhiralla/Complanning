import { LuBuilding2, LuCheck, LuPlus } from "react-icons/lu";
import { Button, LoadError, useLoad } from "../components/ui";
import { get } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Link, navigate } from "../lib/router";
import { useSession } from "../lib/session";
import type { StringKey } from "../lib/strings";

function firstName(name: string) {
  return name.trim().split(/\s+/)[0] ?? name;
}

function Roadmap() {
  const { t } = useI18n();
  const phases: [StringKey, StringKey][] = [
    ["home.phase1", "home.phase1d"], ["home.phase2", "home.phase2d"], ["home.phase3", "home.phase3d"],
    ["home.phase4", "home.phase4d"], ["home.phase5", "home.phase5d"], ["home.phase6", "home.phase6d"],
  ];
  return (
    <section className="panel" aria-labelledby="roadmap-h">
      <div className="panel-head"><h2 id="roadmap-h">{t("home.roadmap")}</h2></div>
      <div className="panel-body" style={{ paddingBottom: 0 }}><p className="muted small">{t("home.roadmapLead")}</p></div>
      <ol className="roadmap">
        {phases.map(([name, desc], i) => (
          <li key={name} className={i === 0 ? "done" : i === 1 ? "now" : ""}>
            <span className="pin" aria-hidden />
            <span className="what">
              <strong>{t("nav.phase", { n: i + 1 })} · {t(name)}{i === 0 ? ` — ${t("home.released")}` : i === 1 ? ` — ${t("home.next")}` : ""}</strong>
              <span>{t(desc)}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function AdminSetup() {
  const { t } = useI18n();
  const { data, error, reload } = useLoad(async () => {
    const [sites, users, audit] = await Promise.all([
      get<{ items: unknown[] }>("/api/sites"),
      get<{ items: unknown[] }>("/api/users"),
      get<{ items: { new_values: Record<string, unknown> | null }[] }>("/api/audit?entity=tenants&action=UPDATE&page_size=200"),
    ]);
    const changed = (k: string) => audit.items.some((e) => e.new_values && k in e.new_values);
    return { sites: sites.items.length, users: users.items.length, features: changed("features"), security: changed("security") };
  });
  const steps: { done: boolean; title: StringKey; hint: StringKey; to: string }[] = data ? [
    { done: data.sites > 0, title: "home.step.sites", hint: "home.step.sitesHint", to: "/sites" },
    { done: data.users > 1, title: "home.step.users", hint: "home.step.usersHint", to: "/users" },
    { done: data.features, title: "home.step.features", hint: "home.step.featuresHint", to: "/settings?tab=features" },
    { done: data.security, title: "home.step.security", hint: "home.step.securityHint", to: "/settings?tab=security" },
  ] : [];
  return (
    <section className="panel" aria-labelledby="setup-h">
      <div className="panel-head"><h2 id="setup-h">{t("home.setup")}</h2>
        {data && <span className="spacer" />}
        {data && <span className="small muted num">{steps.filter((s) => s.done).length} / {steps.length}</span>}
      </div>
      {error ? <LoadError error={error} onRetry={reload} /> : (
        <ol className="steps">
          {(data ? steps : Array.from({ length: 4 }).map(() => null)).map((s, i) => s ? (
            <li key={s.title} className={s.done ? "done" : ""}>
              <span className="tick" aria-hidden><LuCheck /></span>
              <span className="text"><strong>{t(s.title)}</strong><span>{t(s.hint)}</span></span>
              {!s.done && <Link to={s.to} className="btn sm">{t("home.step.open")}</Link>}
            </li>
          ) : <li key={i}><div className="skeleton" style={{ width: "60%" }} /></li>)}
        </ol>
      )}
    </section>
  );
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
        <div className="home-grid">
          {u.is_tenant_admin ? <AdminSetup /> : (
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
          <Roadmap />
        </div>
      )}
    </>
  );
}
