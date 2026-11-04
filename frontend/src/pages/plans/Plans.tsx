import { useState, type CSSProperties, type ReactElement } from "react";
import { LuChartGantt, LuCheck, LuClock, LuColumns3, LuGauge, LuPlay, LuPlus, LuTarget, LuWallet } from "react-icons/lu";
import { Badge, Button, Empty, Field, LoadError, Notice, PageHead, Sheet, Switch, TextField, errorText, useLoad, useToast } from "../../components/ui";
import { NumberField } from "../../components/master";
import { useFeature } from "../../components/rules";
import { get, post } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Link, navigate } from "../../lib/router";
import { usePerms } from "../../lib/session";

export type Objective = "on_time" | "sales_value" | "utilization";
export interface PlanRow {
  id: string; site_id: string; name: string; status: "draft" | "released" | "archived"; locks: unknown[];
  released_at: string | null; released_by_name: string | null; replanned_at: string | null; objective: Objective; horizon_start: string; horizon_end: string;
  plan_date: string; starts_at: string; options: Record<string, unknown>; notes: string | null; created_at: string; created_by_name: string | null;
  kpis: null | {
    batches: number; scheduled: number; unscheduled: number; demand_lines: number; on_time: number; late: number; unfilled: number;
    on_time_pct: number | null; changeover_hours: number; changeovers: number; finish: string | null; runtime_ms: number; runs: number;
    value: { currency: string; requested: number; on_time: number }[]; warnings: Warning[]; rounded?: number;
    cost?: { currency: string; materials: number; deliveries: number; margin: number; missing: string[] } | null;
    utilization: { machine_id: string; code: string; available_hours: number; busy_hours: number; changeover_hours: number; utilization: number | null }[];
  };
}
export type Warning = Record<string, unknown> & { kind: string };

export const OBJ_ICON: Record<Objective, ReactElement> = { on_time: <LuClock />, sales_value: <LuWallet />, utilization: <LuGauge /> };

type Preset = "next30" | "thisMonth" | "nextMonth" | "next3" | "custom";
const iso = (d: Date) => d.toISOString().slice(0, 10);
function presetRange(p: Preset): [string, string] {
  const n = new Date();
  const t0 = new Date(Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()));
  const first = (k: number) => new Date(Date.UTC(t0.getUTCFullYear(), t0.getUTCMonth() + k, 1));
  const last = (d: Date) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
  if (p === "thisMonth") return [iso(t0), iso(last(first(0)))];
  if (p === "nextMonth") return [iso(first(1)), iso(last(first(1)))];
  if (p === "next3") return [iso(t0), iso(last(first(2)))];
  return [iso(t0), iso(new Date(t0.getTime() + 29 * 86400000))];
}

function NewPlanSheet({ siteId, onClose }: { siteId: string; onClose: () => void }) {
  const { t, date } = useI18n();
  const toast = useToast();
  const feature = useFeature();
  const [preset, setPreset] = useState<Preset>("next30");
  const [custom, setCustom] = useState<[string, string]>(presetRange("next30"));
  const [f, setF] = useState({ name: "", objective: "on_time" as Objective, include_quarantine: false, release_at_risk: false,
    cap_to_limit: true, material_constraints: true, full_shippers: true, max_early_days: "14", notes: "" });
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [start, end] = preset === "custom" ? custom : presetRange(preset);
  const presets: Preset[] = ["next30", "thisMonth", "nextMonth", "next3", "custom"];
  const plabel = { next30: "req.next30", thisMonth: "req.thisMonth", nextMonth: "req.nextMonth", next3: "req.next3", custom: "req.custom" } as const;
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      const p = await post<PlanRow>(`/api/sites/${siteId}/plans`, {
        name: f.name.trim() || `${t(`obj.${f.objective}` as never)} · ${date(start, "UTC")} – ${date(end, "UTC")}`, objective: f.objective, horizon_start: start, horizon_end: end, include_quarantine: f.include_quarantine,
        release_at_risk: f.release_at_risk, cap_to_limit: f.cap_to_limit, material_constraints: f.material_constraints, full_shippers: f.full_shippers,
        max_early_days: f.max_early_days.trim() === "" ? null : Number(f.max_early_days), notes: f.notes || null,
      });
      toast(t("np.done")); navigate(`/plans/${p.id}`);
    } catch (e) {
      setErrs((e as { fields?: Record<string, string> }).fields ?? {}); setGeneral(errorText(e, t)); setBusy(false);
    }
  };
  const opt = (key: "include_quarantine" | "release_at_risk" | "cap_to_limit" | "material_constraints" | "full_shippers", label: string, hint: string) => (
    <div className="feature" style={{ padding: "8px 0", border: 0 }}>
      <div className="text"><strong>{t(label as never)}</strong><span>{t(hint as never)}</span></div>
      <Switch label={t(label as never)} checked={f[key]} onChange={(v) => setF({ ...f, [key]: v })} />
    </div>
  );
  return (
    <Sheet wide title={t("np.title")} lead={t("np.lead")} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose} disabled={busy}>{t("common.cancel")}</Button>
        <Button type="submit" variant="primary" icon={<LuPlay />} busy={busy}>{busy ? t("np.running") : t("np.run")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <Field label={t("np.objective")}>{() => (
        <div className="obj-cards" role="radiogroup" aria-label={t("np.objective")}>
          {(["on_time", "sales_value", "utilization"] as Objective[]).map((o) => (
            <button key={o} type="button" role="radio" aria-checked={f.objective === o} className="obj-card" onClick={() => setF({ ...f, objective: o })}>
              <span className="icon">{OBJ_ICON[o]}</span>
              <strong>{t(`obj.${o}` as never)}</strong>
              <span className="small muted">{t(`obj.${o}.d` as never)}</span>
            </button>
          ))}
        </div>
      )}</Field>
      <Field label={t("np.horizon")} error={errs.horizon_end}>{() => (
        <div className="stack" style={{ gap: 8 }}>
          <div className="seg" role="group" style={{ flexWrap: "wrap" }}>
            {presets.map((p) => <button key={p} type="button" aria-pressed={preset === p} onClick={() => { if (p === "custom") setCustom([start, end]); setPreset(p); }}>{t(plabel[p])}</button>)}
          </div>
          {preset === "custom" && <div className="grid-2">
            <TextField label={t("req.from")} type="date" value={custom[0]} onChange={(v) => v && setCustom([v, custom[1]])} />
            <TextField label={t("req.to")} type="date" value={custom[1]} onChange={(v) => v && setCustom([custom[0], v])} />
          </div>}
        </div>
      )}</Field>
      <div className="grid-2">
        <TextField label={t("np.name")} placeholder={t("np.namePh")} value={f.name} maxLength={120} onChange={(v) => setF({ ...f, name: v })} />
        <NumberField label={t("np.early")} hint={t("np.earlyHint")} value={f.max_early_days} min={0} step="1"
          onChange={(v) => setF({ ...f, max_early_days: v })} error={errs.max_early_days} />
      </div>
      <h3 className="sheet-section">{t("np.options")}</h3>
      {opt("material_constraints", "np.materials", "np.materialsHint")}
      {opt("include_quarantine", "np.quarantine", "np.quarantineHint")}
      {feature("release_at_risk") && opt("release_at_risk", "np.atRisk", "np.atRiskHint")}
      {opt("cap_to_limit", "np.cap", "np.capHint")}
      {opt("full_shippers", "np.shippers", "np.shippersHint")}
      <TextField label={t("np.notes")} value={f.notes} maxLength={500} onChange={(v) => setF({ ...f, notes: v })} />
    </Sheet>
  );
}

export function Plans() {
  const { t, qty, dateTime, date } = useI18n();
  const { planSite, site, siteId } = usePerms();
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (id: string) => setPicked((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 3 ? s : [...s, id]));
  const data = useLoad(() => (siteId ? get<{ items: PlanRow[] }>(`/api/sites/${siteId}/plans`) : Promise.resolve(null)), [siteId]);
  if (!siteId) return <><PageHead title={t("plans.title")} /><Notice>{t("common.noSite")}</Notice></>;
  const canEdit = planSite(siteId);
  const all = data.data?.items ?? [];
  const rows = all.filter((p) => showArchived || p.status !== "archived");
  const archived = all.filter((p) => p.status === "archived").length;
  return (
    <>
      <PageHead title={t("plans.title")} lead={t("plans.lead", { site: site?.name ?? "" })}
        actions={<>
          {picked.length >= 2 && <Button icon={<LuColumns3 />} onClick={() => navigate(`/plans/compare?ids=${picked.join(",")}`)}>{t("cmp.compare", { n: picked.length })}</Button>}
          {canEdit && <Button variant="primary" icon={<LuPlus />} onClick={() => setCreating(true)}>{t("plans.new")}</Button>}
        </>} />
      {!canEdit && <Notice>{t("plans.readOnly")}</Notice>}
      {data.error ? <LoadError error={data.error} onRetry={data.reload} /> : data.data && all.length === 0 ? (
        <div className="panel"><Empty icon={<LuChartGantt />} title={t("plans.empty")} body={t("plans.emptyBody")}
          action={canEdit && <Button variant="primary" icon={<LuPlus />} onClick={() => setCreating(true)}>{t("plans.new")}</Button>} /></div>
      ) : (
        <>
          {archived > 0 && <div className="row" style={{ justifyContent: "flex-end", marginBottom: 10, gap: 8 }}>
            <span className="small muted">{t("plans.showArchived")} ({archived})</span>
            <Switch label={t("plans.showArchived")} checked={showArchived} onChange={setShowArchived} />
          </div>}
          <div className="plan-list">
            {!data.data ? [0, 1, 2].map((i) => <div key={i} className="plan-card"><div className="skeleton" style={{ height: 70 }} /></div>) : rows.map((p) => {
              const k = p.kpis;
              const pct = k?.on_time_pct ?? null;
              return (
                <Link key={p.id} to={`/plans/${p.id}`} className={`plan-card ${p.status === "archived" ? "archived" : ""}`}>
                  <div className="top">
                    <span className={`obj obj-${p.objective}`}>{OBJ_ICON[p.objective]}</span>
                    <div className="titles">
                      <strong>{p.name}</strong>
                      <span className="small muted">{t(`obj.${p.objective}` as never)} · {date(p.horizon_start, "UTC")} – {date(p.horizon_end, "UTC")}</span>
                    </div>
                    {p.status === "archived" && <Badge>{t("plans.archived")}</Badge>}
                    {p.status === "released" && <Badge tone="ok" dot>{t("pv.st.released")}</Badge>}
                    {all.length > 1 && <span className={`pick ${picked.includes(p.id) ? "on" : ""}`} role="checkbox" aria-checked={picked.includes(p.id)}
                      aria-label={t("cmp.select")} title={t("cmp.select")} tabIndex={0}
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggle(p.id); }}
                      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); e.stopPropagation(); toggle(p.id); } }}>
                      <LuCheck aria-hidden /></span>}
                  </div>
                  {k && <div className="stats">
                    <span className={`ring ${pct === null ? "" : pct >= 95 ? "good" : pct >= 75 ? "mid" : "bad"}`} style={{ "--p": `${pct ?? 0}` } as CSSProperties}>
                      <span>{pct === null ? "—" : `${Math.round(pct)}%`}</span>
                    </span>
                    <div className="small">
                      <div><LuTarget className="i" /> {t("plans.onTime", { n: k.on_time, total: k.demand_lines })}</div>
                      <div><LuChartGantt className="i" /> {t("plans.batches", { n: k.scheduled })}{k.unscheduled > 0 && <Badge tone="danger"> {k.unscheduled}</Badge>}</div>
                      <div><LuClock className="i" /> {t("plans.coHours", { n: qty(k.changeover_hours, 0) })}</div>
                    </div>
                  </div>}
                  <div className="small subtle foot">{t("plans.by", { name: p.created_by_name ?? "—", when: dateTime(p.created_at, site?.timezone) })}</div>
                </Link>
              );
            })}
          </div>
        </>
      )}
      {creating && <NewPlanSheet siteId={siteId} onClose={() => setCreating(false)} />}
    </>
  );
}
