/* Getting-started help: the setup checklist on Home and short tours of each main page. */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { LuCheck, LuChevronRight, LuCircleHelp, LuEyeOff, LuListChecks, LuX } from "react-icons/lu";
import { Button, LoadError, useLoad } from "./ui";
import { get, patch } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Link, usePath } from "../lib/router";
import { useSession } from "../lib/session";
import type { StringKey } from "../lib/strings";

// ------------------------------------------------------------------ preferences
export function useGuidePrefs() {
  const { me, setMe } = useSession();
  const guide = me?.user.guide ?? {};
  const save = useCallback(async (body: { checklist_hidden?: boolean; tour_seen?: string; tours_reset?: boolean }) => {
    if (!me) return;
    // Optimistic: update the session copy first so the screen reacts at once.
    const next = { ...(me.user.guide ?? {}) };
    if (body.checklist_hidden !== undefined) next.checklist_hidden = body.checklist_hidden;
    const tours = body.tours_reset ? [] : [...(next.tours ?? [])];
    if (body.tour_seen && !tours.includes(body.tour_seen)) tours.push(body.tour_seen);
    next.tours = tours;
    setMe({ ...me, user: { ...me.user, guide: next } });
    try { await patch("/api/auth/preferences", body); } catch { /* kept for this session */ }
  }, [me, setMe]);
  return { hidden: !!guide.checklist_hidden, seen: guide.tours ?? [], save };
}

// ------------------------------------------------------------------ checklist
interface Step { key: string; done: boolean; to: string; have: number | null; total: number | null }
interface Progress { steps: Step[]; done: number; total: number; complete: boolean }

export function GetStarted() {
  const { t, qty } = useI18n();
  const { siteId } = useSession();
  const { save } = useGuidePrefs();
  const data = useLoad(() => get<Progress>("/api/setup-progress" + (siteId ? `?site_id=${siteId}` : "")), [siteId]);
  const p = data.data;
  const firstOpen = p?.steps.find((s) => !s.done)?.key;
  return (
    <section className="panel getstarted" id="getstarted" aria-labelledby="gs-h">
      <div className="panel-head">
        <LuListChecks aria-hidden className="muted" />
        <div className="grow"><h2 id="gs-h">{t("gs.title")}</h2><p className="small muted">{t("gs.lead")}</p></div>
        {p && <span className="small muted num nowrap">{t("gs.progress", { n: p.done, total: p.total })}</span>}
        <Button size="sm" variant="ghost" icon={<LuEyeOff />} onClick={() => save({ checklist_hidden: true })}>{t("gs.hide")}</Button>
      </div>
      {p && <div className="gs-bar" role="progressbar" aria-valuemin={0} aria-valuemax={p.total} aria-valuenow={p.done}
        aria-label={t("gs.progress", { n: p.done, total: p.total })}><span style={{ width: `${(p.done / p.total) * 100}%` }} /></div>}
      {data.error ? <LoadError error={data.error} onRetry={data.reload} /> : !p ? (
        <div className="panel-body"><div className="skeleton" style={{ height: 120 }} /></div>
      ) : <>
        {p.complete && <div className="panel-body gs-complete"><LuCheck aria-hidden /> {t("gs.complete")}</div>}
        <ol className="gs-steps">
          {p.steps.map((s, i) => (
            <li key={s.key} className={`${s.done ? "done" : ""} ${s.key === firstOpen ? "next" : ""}`}>
              <span className="n" aria-hidden>{s.done ? <LuCheck /> : i + 1}</span>
              <span className="text">
                <strong>{t(`gs.s.${s.key}` as StringKey)}</strong>
                <span>{t(`gs.s.${s.key}.d` as StringKey)}</span>
                {s.total ? <span className="subtle small">{t("gs.haveOf", { n: qty(s.have ?? 0, 0), total: qty(s.total, 0) })}</span> : null}
              </span>
              <Link to={s.to} className={`btn sm ${s.key === firstOpen ? "primary" : ""}`}>{t("gs.open")}<LuChevronRight className="flip-rtl" aria-hidden /></Link>
            </li>
          ))}
        </ol>
        {!siteId && <p className="small subtle panel-body">{t("gs.noSite")}</p>}
      </>}
    </section>
  );
}

// ------------------------------------------------------------------ tours
type Target = { sel?: string; label?: StringKey | StringKey[]; page?: boolean };
interface TourStep { target: Target; body: StringKey }
interface Tour { id: string; match: (path: string) => boolean; steps: TourStep[] }

const is = (p: string) => (path: string) => path === p;
const under = (p: string) => (path: string) => path.startsWith(p + "/") && path.split("/").length === p.split("/").length + 1;

const TOURS: Tour[] = [
  { id: "home", match: is("/"), steps: [
    { target: { sel: "#getstarted", page: true }, body: "tour.home.1" },
    { target: { sel: ".site-switch", page: true }, body: "tour.home.2" },
    { target: { sel: ".user-btn", page: true }, body: "tour.home.3" },
  ] },
  { id: "items", match: is("/master/items"), steps: [
    { target: { sel: "button", label: "items.new" }, body: "tour.items.1" },
    { target: { sel: ".page-head button", label: "Excel" as StringKey }, body: "tour.items.2" },
    { target: { sel: "button", label: "sample.load" }, body: "tour.items.3" },
    { target: { sel: "tbody tr" }, body: "tour.items.4" },
  ] },
  { id: "units", match: is("/master/units"), steps: [
    { target: { sel: "h2", label: "units.units" }, body: "tour.units.1" },
    { target: { sel: "h2", label: "markets.title" }, body: "tour.units.2" },
  ] },
  { id: "boms", match: is("/master/boms"), steps: [
    { target: { sel: ".page-head" }, body: "tour.boms.1" },
  ] },
  { id: "bom", match: under("/master/boms"), steps: [
    { target: { sel: "h2", label: "boms.header" }, body: "tour.bom.1" },
    { target: { sel: "h2", label: "boms.lines" }, body: "tour.bom.2" },
    { target: { sel: "h2", label: "boms.structure" }, body: "tour.bom.3" },
    { target: { sel: "button", label: ["boms.activate", "boms.newVersion"] }, body: "tour.bom.4" },
  ] },
  { id: "machines", match: is("/master/machines"), steps: [
    { target: { sel: "button", label: "machines.new" }, body: "tour.machines.1" },
    { target: { sel: "h2, h3", label: "downtime.title" }, body: "tour.machines.2" },
  ] },
  { id: "routings", match: is("/master/routings"), steps: [
    { target: { sel: ".page-head" }, body: "tour.routings.1" },
  ] },
  { id: "routing", match: under("/master/routings"), steps: [
    { target: { sel: "button", label: "routings.addStep" }, body: "tour.routing.1" },
    { target: { sel: ".palette" }, body: "tour.routing.2" },
    { target: { sel: ".no-pause" }, body: "tour.routing.3" },
  ] },
  { id: "calendar", match: is("/master/calendar"), steps: [
    { target: { sel: "h2, h3", label: "calendar.weekly" }, body: "tour.calendar.1" },
    { target: { sel: "h2, h3", label: "calendar.periods" }, body: "tour.calendar.2" },
    { target: { sel: "button", label: "calendar.addDayOff" }, body: "tour.calendar.3" },
  ] },
  { id: "changeovers", match: is("/rules/changeovers"), steps: [
    { target: { sel: "h2, h3", label: "groups.title" }, body: "tour.changeovers.1" },
    { target: { sel: "h2, h3", label: "co.general" }, body: "tour.changeovers.2" },
    { target: { sel: "h2, h3", label: "co.matrix" }, body: "tour.changeovers.3" },
    { target: { sel: "h2, h3", label: "co.check" }, body: "tour.changeovers.4" },
  ] },
  { id: "campaigns", match: is("/rules/campaigns"), steps: [
    { target: { sel: "h2, h3", label: "camp.campaigns" }, body: "tour.campaigns.1" },
    { target: { sel: "h2, h3", label: "holds.title" }, body: "tour.campaigns.2" },
  ] },
  { id: "times", match: is("/rules/times"), steps: [
    { target: { sel: "#main table" }, body: "tour.times.1" },
  ] },
  { id: "sales", match: is("/planning/sales"), steps: [
    { target: { sel: "#main tbody input" }, body: "tour.sales.1" },
    { target: { sel: "button", label: "sales.save" }, body: "tour.sales.2" },
  ] },
  { id: "stock", match: is("/planning/stock"), steps: [
    { target: { sel: "label", label: "stock.asOf" }, body: "tour.stock.1" },
    { target: { sel: "button", label: "stock.new" }, body: "tour.stock.2" },
  ] },
  { id: "requirements", match: is("/planning/requirements"), steps: [
    { target: { sel: ".horizon" }, body: "tour.req.1" },
    { target: { sel: "h2", label: "req.make" }, body: "tour.req.2" },
    { target: { sel: "h2", label: "req.materials" }, body: "tour.req.3" },
  ] },
  { id: "plans", match: is("/plans"), steps: [
    { target: { sel: "button", label: "plans.new" }, body: "tour.plans.1" },
    { target: { sel: ".pick" }, body: "tour.plans.2" },
  ] },
  { id: "plan", match: (p) => under("/plans")(p) && p !== "/plans/compare", steps: [
    { target: { sel: ".kpis" }, body: "tour.plan.1" },
    { target: { sel: ".tabs" }, body: "tour.plan.2" },
    { target: { sel: ".gantt-panel" }, body: "tour.plan.3" },
    { target: { sel: ".page-head button", label: ["pv.release", "pv.reopen"] }, body: "tour.plan.4" },
  ] },
  { id: "settings", match: is("/settings"), steps: [
    { target: { sel: ".tabs" }, body: "tour.settings.1" },
  ] },
  { id: "users", match: is("/users"), steps: [
    { target: { sel: "button", label: "users.new" }, body: "tour.users.1" },
  ] },
  { id: "sites", match: is("/sites"), steps: [
    { target: { sel: "button", label: "sites.new" }, body: "tour.sites.1" },
  ] },
];

function visible(el: Element) {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

function findTarget(target: Target, t: (k: StringKey) => string): HTMLElement | null {
  const root: ParentNode = target.page ? document : (document.getElementById("main") ?? document);
  const els = Array.from(root.querySelectorAll<HTMLElement>(target.sel ?? "button, a, h2, h3, label"));
  if (!target.label) return els.find(visible) ?? null;
  const labels = (Array.isArray(target.label) ? target.label : [target.label]).map((k) => {
    const s = t(k);
    return s === k ? k : s;            // literal text such as "Excel"
  });
  for (const text of labels) {
    const hit = els.find((el) => visible(el) && (el.textContent ?? "").trim().startsWith(text));
    if (hit) return hit;
  }
  return null;
}

interface TourCtx { available: boolean; start: () => void }
const Ctx = createContext<TourCtx>({ available: false, start: () => {} });
export const useTour = () => useContext(Ctx);

export function TourProvider({ children }: { children: ReactNode }) {
  const path = usePath();
  const { me } = useSession();
  const { t } = useI18n();
  const { seen, save } = useGuidePrefs();
  const tour = useMemo(() => TOURS.find((x) => x.match(path)) ?? null, [path]);
  const [running, setRunning] = useState<{ tour: Tour; steps: { el: HTMLElement; body: StringKey }[] } | null>(null);
  const enabled = !!me && !me.user.is_platform_admin && !me.user.must_change_password;

  const start = useCallback((auto = false) => {
    if (!tour) return;
    const steps = tour.steps.map((s) => ({ el: findTarget(s.target, t as (k: StringKey) => string), body: s.body }))
      .filter((s): s is { el: HTMLElement; body: StringKey } => !!s.el);
    if (!steps.length) return;
    if (auto && document.querySelector(".sheet, .dialog")) return;       // never cover a form the user opened
    setRunning({ tour, steps });
  }, [tour, t]);

  // Start automatically the first time a page is opened, once its content has rendered.
  const seenKey = seen.join(",");
  useEffect(() => {
    setRunning(null);
    if (!enabled || !tour || seenKey.split(",").includes(tour.id)) return;
    const timer = window.setTimeout(() => start(true), 900);
    return () => window.clearTimeout(timer);
  }, [path, tour, enabled, seenKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const finish = () => {
    if (running) save({ tour_seen: running.tour.id });
    setRunning(null);
  };
  return (
    <Ctx.Provider value={{ available: enabled && !!tour, start: () => start(false) }}>
      {children}
      {running && <TourOverlay steps={running.steps} onClose={finish} />}
    </Ctx.Provider>
  );
}

function TourOverlay({ steps, onClose }: { steps: { el: HTMLElement; body: StringKey }[]; onClose: () => void }) {
  const { t } = useI18n();
  const [i, setI] = useState(0);
  const [box, setBox] = useState<DOMRect | null>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const [bubbleH, setBubbleH] = useState(160);
  const step = steps[i];
  const last = i === steps.length - 1;

  useLayoutEffect(() => {
    step.el.scrollIntoView({ block: "center", inline: "nearest" });
    const measure = () => setBox(step.el.getBoundingClientRect());
    measure();
    const late = window.setTimeout(measure, 350);          // after smooth scrolling settles
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => { window.clearTimeout(late); window.removeEventListener("resize", measure); window.removeEventListener("scroll", measure, true); };
  }, [step]);
  useLayoutEffect(() => { if (bubble.current) setBubbleH(bubble.current.offsetHeight); }, [i, box]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "Enter") { if (last) onClose(); else setI((n) => n + 1); }
    };
    window.addEventListener("keydown", onKey);
    bubble.current?.querySelector<HTMLButtonElement>(".tour-actions .primary")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [i, last, onClose]);

  if (!box) return null;
  const pad = 6;
  const vw = window.innerWidth, vh = window.innerHeight;
  const width = Math.min(340, vw - 24);
  const below = box.bottom + 12 + bubbleH < vh || box.top < bubbleH + 24;
  const top = below ? Math.min(box.bottom + 12, vh - bubbleH - 12) : box.top - bubbleH - 12;
  const left = Math.max(12, Math.min(box.left + box.width / 2 - width / 2, vw - width - 12));
  return (
    <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-text">
      <div className="tour-shield" onClick={onClose} />
      <div className="tour-spot" style={{ top: box.top - pad, left: box.left - pad, width: box.width + pad * 2, height: box.height + pad * 2 }} />
      <div className="tour-bubble" ref={bubble} style={{ top: Math.max(12, top), left, width }}>
        <div className="tour-head">
          <span className="small muted num">{t("tour.count", { n: i + 1, total: steps.length })}</span>
          <span className="spacer" />
          <button type="button" className="icon-btn" aria-label={t("tour.skip")} onClick={onClose}><LuX /></button>
        </div>
        <p id="tour-text">{t(step.body)}</p>
        <div className="tour-actions">
          {!last && <button type="button" className="btn ghost sm" onClick={onClose}>{t("tour.skip")}</button>}
          <span className="spacer" />
          {i > 0 && <button type="button" className="btn sm" onClick={() => setI(i - 1)}>{t("tour.back")}</button>}
          <button type="button" className="btn primary sm" onClick={() => (last ? onClose() : setI(i + 1))}>{last ? t("tour.done") : t("tour.next")}</button>
        </div>
      </div>
    </div>
  );
}

/** The "?" next to a page title: replays that page's tour. */
export function TourButton() {
  const { t } = useI18n();
  const { available, start } = useTour();
  if (!available) return null;
  return <button type="button" className="tour-help" onClick={start} aria-label={t("tour.help")} title={t("tour.help")}><LuCircleHelp /></button>;
}
