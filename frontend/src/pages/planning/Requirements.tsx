import { useState } from "react";
import { LuBoxes, LuCalendarRange, LuCircleCheck, LuClockAlert, LuFactory, LuPackageX, LuWallet } from "react-icons/lu";
import { Badge, Empty, LoadError, Notice, PageHead, Switch, useLoad } from "../../components/ui";
import { TypeBadge } from "../../components/master";
import { get, qs } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import { nameOf, type ItemType } from "../../lib/types";

interface UsedBy { code: string; quantity: number; batches: number; }
interface Produced {
  item_id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; uom: string; level: number;
  demand: number; dependent: number; safety: number; released: number; quarantine: number; stock_counted: boolean; usable: number;
  stock_used: number; net: number; used_by: UsedBy[]; batches: number; batch_sizes: number[]; batch_output: number | null;
  batch_mode: "fixed" | "partial" | null; planned: number; surplus: number; bom_version: number | null; no_bom: boolean;
}
interface Material {
  item_id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; uom: string; required: number;
  released: number; quarantine: number; available: number; shortage: number; after: number; safety: number; below_safety: boolean;
  not_stock_controlled: boolean; lead_time_days: number; qc_release_days: number; earliest_arrival: string | null; late: boolean;
  used_by: UsedBy[]; quarantine_would_cover: boolean;
}
interface Result {
  horizon: { start: string; end: string; days: number };
  options: { include_quarantine: boolean; use_stock: Record<string, boolean> };
  produced: Produced[]; materials: Material[];
  over_limit: { code: string; market: string; month: string; quantity: number; limit: number }[];
  sales_value: { currency: string; value: number }[];
  totals: { batches: number; shortages: number; late: number; no_bom: number; demand_lines: number };
}
type Preset = "next30" | "thisMonth" | "nextMonth" | "next3" | "custom";

const iso = (d: Date) => d.toISOString().slice(0, 10);
function range(p: Preset): [string, string] {
  const now = new Date();
  const t0 = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  const m = (n: number) => new Date(Date.UTC(t0.getUTCFullYear(), t0.getUTCMonth() + n, 1));
  const lastOf = (d: Date) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
  if (p === "thisMonth") return [iso(m(0)), iso(lastOf(m(0)))];
  if (p === "nextMonth") return [iso(m(1)), iso(lastOf(m(1)))];
  if (p === "next3") return [iso(t0), iso(lastOf(m(2)))];
  return [iso(t0), iso(new Date(t0.getTime() + 29 * 86400000))];
}

function Coverage({ m }: { m: Material }) {
  const pct = m.required > 0 ? Math.min(100, (m.available / m.required) * 100) : 100;
  return <div className={`cover ${m.shortage > 0 ? "short" : ""}`} aria-hidden><span style={{ width: `${pct}%` }} /></div>;
}

export function Requirements() {
  const { t, lang, qty, date } = useI18n();
  const { site, siteId } = usePerms();
  const [preset, setPreset] = useState<Preset>("next30");
  const [custom, setCustom] = useState<[string, string]>(range("next30"));
  const [quarantine, setQuarantine] = useState(false);
  const [shortOnly, setShortOnly] = useState(false);
  const [start, end] = preset === "custom" ? custom : range(preset);
  const data = useLoad(() => (siteId ? get<Result>(`/api/sites/${siteId}/requirements` + qs({ start, end, quarantine: quarantine ? 1 : 0 }))
    : Promise.resolve(null)), [siteId, start, end, quarantine]);
  if (!siteId) return <><PageHead title={t("req.title")} /><Notice>{t("common.noSite")}</Notice></>;
  const r = data.data;
  const yn = (b: boolean | undefined) => (b ? t("req.yes") : t("req.no"));
  const forList = (u: UsedBy[]) => (u.length ? t("req.for", { codes: u.map((x) => x.code).join(", ") }) : "");
  const mats = (r?.materials ?? []).filter((m) => !shortOnly || m.shortage > 0);
  const noBom = (r?.produced ?? []).filter((p) => p.no_bom).map((p) => p.code);
  const presets: Preset[] = ["next30", "thisMonth", "nextMonth", "next3", "custom"];
  const presetLabel = { next30: "req.next30", thisMonth: "req.thisMonth", nextMonth: "req.nextMonth", next3: "req.next3", custom: "req.custom" } as const;

  return (
    <>
      <PageHead title={t("req.title")} lead={t("req.lead", { site: site?.name ?? "" })} />
      <div className="panel horizon">
        <div className="horizon-row">
          <span className="small muted label"><LuCalendarRange /> {t("req.horizon")}</span>
          <div className="seg" role="group" aria-label={t("req.horizon")}>
            {presets.map((p) => <button key={p} type="button" aria-pressed={preset === p} onClick={() => { if (p === "custom") setCustom([start, end]); setPreset(p); }}>{t(presetLabel[p])}</button>)}
          </div>
          {preset === "custom" ? (
            <div className="row" style={{ gap: 6 }}>
              <input className="input" type="date" aria-label={t("req.from")} value={custom[0]} onChange={(e) => e.target.value && setCustom([e.target.value, custom[1]])} />
              <span className="subtle">–</span>
              <input className="input" type="date" aria-label={t("req.to")} value={custom[1]} onChange={(e) => e.target.value && setCustom([custom[0], e.target.value])} />
            </div>
          ) : <span className="small"><strong>{date(start, "UTC")}</strong> – <strong>{date(end, "UTC")}</strong></span>}
        </div>
        <div className="horizon-row">
          <div className="row" style={{ gap: 10 }}>
            <Switch label={t("req.quarantine")} checked={quarantine} onChange={setQuarantine} />
            <div><div className="small"><strong>{t("req.quarantine")}</strong></div><div className="small subtle">{t("req.quarantineHint")}</div></div>
          </div>
          {r && <span className="small subtle grow" style={{ textAlign: "end" }}>
            {t("req.stockRules", { fg: yn(r.options.use_stock.finished), semi: yn(r.options.use_stock.semi_finished), wip: yn(r.options.use_stock.wip) })}
          </span>}
        </div>
      </div>

      {data.error ? <LoadError error={data.error} onRetry={data.reload} /> : !r ? (
        <div className="kpis">{[0, 1, 2, 3].map((i) => <div key={i} className="kpi"><div className="skeleton" style={{ height: 48 }} /></div>)}</div>
      ) : r.totals.demand_lines === 0 ? (
        <div className="panel" style={{ marginTop: 16 }}><Empty icon={<LuCalendarRange />} title={t("req.noDemand")} body={t("req.noDemandBody")} /></div>
      ) : <>
        <div className="kpis">
          <div className="kpi"><span className="icon"><LuFactory /></span><span className="k">{t("req.kpi.batches")}</span><strong>{qty(r.totals.batches)}</strong>
            <span className="small subtle">{t("req.kpi.lines", { n: r.totals.demand_lines })}</span></div>
          <div className={`kpi ${r.totals.shortages ? "bad" : "good"}`}><span className="icon"><LuPackageX /></span><span className="k">{t("req.kpi.shortages")}</span><strong>{qty(r.totals.shortages)}</strong></div>
          <div className={`kpi ${r.totals.late ? "bad" : "good"}`}><span className="icon"><LuClockAlert /></span><span className="k">{t("req.kpi.late")}</span><strong>{qty(r.totals.late)}</strong></div>
          <div className="kpi"><span className="icon"><LuWallet /></span><span className="k">{t("req.kpi.value")}</span>
            <div className="money">{r.sales_value.length ? r.sales_value.map((v) => <strong key={v.currency}>{qty(v.value, 0)} <small>{v.currency}</small></strong>) : <strong>—</strong>}</div></div>
        </div>
        {r.over_limit.length > 0 && <Notice tone="warn">
          {t("req.overLimit", { n: r.over_limit.length })}{" "}
          <span className="small">{r.over_limit.map((o) => `${o.code} / ${o.market} / ${o.month}: ${qty(o.quantity, 0)} > ${qty(o.limit, 0)}`).join(" · ")}</span>
        </Notice>}
        {noBom.length > 0 && <Notice tone="danger">{t("req.noBom", { codes: noBom.join(", ") })}</Notice>}

        <div className="section-head">
          <div className="titles"><h2>{t("req.make")}</h2><p>{t("req.makeLead")}</p></div>
        </div>
        <div className="panel">
          <div className="table-wrap">
            <table className="table req-table">
              <thead><tr>
                <th>{t("stock.item")}</th><th className="num">{t("req.demand")}</th><th className="num">{t("req.dependent")}</th>
                <th className="num">{t("req.stockUsed")}</th><th className="num">{t("req.net")}</th><th>{t("req.batches")}</th>
                <th className="num">{t("req.planned")}</th>
              </tr></thead>
              <tbody>
                {r.produced.map((p) => (
                  <tr key={p.item_id} className={p.no_bom ? "row-error" : ""}>
                    <td>
                      <div className="row wrap" style={{ gap: 6 }}><span className="mono-id cell-main">{p.code}</span><TypeBadge type={p.type} /></div>
                      <div className="small muted">{nameOf(p, lang)}</div>
                      {p.used_by.length > 0 && <div className="small subtle">{forList(p.used_by)}</div>}
                    </td>
                    <td className="num">{p.demand > 0 ? qty(p.demand, 0) : <span className="subtle">—</span>}</td>
                    <td className="num">{p.dependent > 0 ? qty(p.dependent, 1) : <span className="subtle">—</span>}</td>
                    <td className="num">
                      {p.stock_counted ? qty(p.stock_used, 1) : <span className="subtle small">{t("req.stockOff")}</span>}
                      {p.safety > 0 && <div className="small subtle">{t("req.safety")}: {qty(p.safety, 0)}</div>}
                    </td>
                    <td className="num cell-main">{qty(p.net, 1)} <span className="subtle small">{p.uom}</span></td>
                    <td>
                      {p.no_bom ? <Badge tone="danger">{t("req.noBomShort")}</Badge> : p.batches === 0 ? <span className="subtle">—</span> : (
                        <div className="batches">
                          <strong>{p.batches} ×</strong>
                          <span className="chip-row">{p.batch_sizes.map((s, i) => (
                            <span key={i} className={`bchip ${p.batch_output && s < p.batch_output - 0.001 ? "partial" : ""}`}
                              title={p.batch_output && s < p.batch_output - 0.001 ? t("req.partial") : undefined}>{qty(s, 0)}</span>
                          ))}</span>
                        </div>
                      )}
                    </td>
                    <td className="num">{p.planned > 0 ? <>{qty(p.planned, 0)} <span className="subtle small">{p.uom}</span></> : <span className="subtle">—</span>}
                      {p.surplus > 0.5 && <div className="small subtle">{t("req.surplus")}: {qty(p.surplus, 0)}</div>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="section-head">
          <div className="titles"><h2>{t("req.materials")}</h2><p>{t("req.materialsLead")}</p></div>
          <div className="actions">
            <div className="seg" role="group">
              <button type="button" aria-pressed={shortOnly} onClick={() => setShortOnly(true)}>{t("req.shortOnly")} ({r.totals.shortages})</button>
              <button type="button" aria-pressed={!shortOnly} onClick={() => setShortOnly(false)}>{t("req.all")} ({r.materials.length})</button>
            </div>
          </div>
        </div>
        <div className="panel">
          {mats.length === 0 ? (
            <div className="panel-body row" style={{ gap: 8 }}><LuCircleCheck style={{ color: "var(--ok)" }} /> {t("req.noShortages")}</div>
          ) : (
            <div className="table-wrap">
              <table className="table req-table">
                <thead><tr>
                  <th>{t("stock.item")}</th><th className="num">{t("req.required")}</th><th className="num">{t("req.released")}</th>
                  <th className="num">{t("req.quarantineCol")}</th><th className="num">{t("req.shortage")}</th><th>{t("req.arrival")}</th>
                </tr></thead>
                <tbody>
                  {mats.map((m) => (
                    <tr key={m.item_id}>
                      <td>
                        <div className="row wrap" style={{ gap: 6 }}><span className="mono-id cell-main">{m.code}</span><TypeBadge type={m.type} /></div>
                        <div className="small muted">{nameOf(m, lang)}</div>
                        <div className="small subtle">{forList(m.used_by)}</div>
                      </td>
                      <td className="num">{qty(m.required, 1)} <span className="subtle small">{m.uom}</span><Coverage m={m} /></td>
                      <td className="num">{m.not_stock_controlled ? <span className="subtle small">{t("req.unlimited")}</span> : qty(m.released, 1)}</td>
                      <td className="num">{m.quarantine > 0 ? qty(m.quarantine, 1) : <span className="subtle">—</span>}</td>
                      <td className="num">
                        {m.shortage > 0 ? <strong className="text-danger">{qty(m.shortage, 1)}</strong> : <span className="subtle">—</span>}
                        {m.quarantine_would_cover && <div><Badge tone="warn">{t("req.qCovers")}</Badge></div>}
                        {m.shortage <= 0 && m.below_safety && <div><Badge tone="warn">{t("req.belowSafety")}</Badge></div>}
                      </td>
                      <td>
                        {m.earliest_arrival ? <>
                          <span className="small num">{date(m.earliest_arrival, "UTC")}</span> {m.late && <Badge tone="danger">{t("req.late")}</Badge>}
                          <div className="small subtle">{t("req.leadDays", { n: m.lead_time_days + m.qc_release_days })}</div>
                        </> : <span className="subtle">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <p className="small subtle" style={{ marginTop: 12, display: "flex", gap: 6, alignItems: "flex-start" }}><LuBoxes style={{ flex: "none", marginTop: 2 }} />{t("req.note")}</p>
      </>}
    </>
  );
}
