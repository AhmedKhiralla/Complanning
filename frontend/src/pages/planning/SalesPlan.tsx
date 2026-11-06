import { Fragment, useEffect, useMemo, useState } from "react";
import { LuCalendarClock, LuChevronLeft, LuChevronRight, LuClipboardList, LuRotateCcw, LuSave, LuSearch, LuSparkles, LuTriangleAlert } from "react-icons/lu";
import {
  Badge, Button, Confirm, Dialog, Empty, LoadError, Notice, PageHead, TextField, errorText, useLoad, useToast,
} from "../../components/ui";
import { ExcelMenu, NumberField } from "../../components/master";
import { get, post, put, qs } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import { useFeature } from "../../components/rules";
import { NumInput } from "../../components/numinput";

interface Cell { id: string; quantity: number; due_date: string | null; notes: string | null; }
interface Row {
  item_id: string; market_id: string; code: string; name_en: string; name_ar: string | null; uom: string;
  market: string; market_name_en: string; market_name_ar: string | null; currency: string;
  max_qty: number | null; price: number | null; cells: Record<string, Cell>;
}
interface Grid { start: string; months: string[]; today: string; rows: Row[]; lines: number; }
interface Edit { quantity: string; due_date: string | null; notes: string | null; }

const keyOf = (r: { item_id: string; market_id: string }, m: string) => `${r.item_id}|${r.market_id}|${m}`;
const addMonths = (ym: string, n: number) => {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
};
const thisMonth = () => new Date().toISOString().slice(0, 7);

function DetailsDialog({ row, month, value, onClose, onApply }: {
  row: Row; month: string; value: Edit; onClose: () => void; onApply: (v: Edit) => void;
}) {
  const { t, month: fmtMonth } = useI18n();
  const [v, setV] = useState(value);
  const [y, m] = month.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
  return (
    <Dialog title={t("sales.details")} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant="primary" onClick={() => { onApply(v); onClose(); }}>{t("sales.apply")}</Button>
    </>}>
      <p className="muted small">{t("sales.detailsLead", { code: row.code, market: row.market, month: fmtMonth(month, true) })}</p>
      <NumberField label={t("sales.qty")} value={v.quantity} min={0} suffix={row.uom} onChange={(q) => setV({ ...v, quantity: q })} />
      <TextField label={t("sales.due")} hint={t("sales.dueHint")} type="date" value={v.due_date ?? ""} min={`${month}-01`} max={last}
        onChange={(d) => setV({ ...v, due_date: d || null })} />
      <TextField label={t("sales.notes")} value={v.notes ?? ""} maxLength={300} onChange={(n) => setV({ ...v, notes: n || null })} />
    </Dialog>
  );
}

export function SalesPlan() {
  const { t, lang, qty, month: fmtMonth, date } = useI18n();
  const { planSite, site, siteId, admin } = usePerms();
  const toast = useToast();
  const feature = useFeature();
  const [start, setStart] = useState(thisMonth());
  const [count, setCount] = useState(6);
  const [market, setMarket] = useState("");
  const [q, setQ] = useState("");
  const grid = useLoad(() => (siteId ? get<Grid>(`/api/sites/${siteId}/demand` + qs({ start, months: count })) : Promise.resolve(null)), [siteId, start, count]);
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [cellErr, setCellErr] = useState<Set<string>>(new Set());
  const [details, setDetails] = useState<{ row: Row; month: string } | null>(null);
  const [sampling, setSampling] = useState(false);
  useEffect(() => { setEdits({}); setErr(null); setCellErr(new Set()); }, [siteId]);

  const rows = grid.data?.rows ?? [];
  const months = grid.data?.months ?? [];
  const canEdit = planSite(siteId);
  const original = (r: Row, m: string): Edit => {
    const c = r.cells[m];
    return { quantity: c ? String(c.quantity) : "", due_date: c?.due_date ?? null, notes: c?.notes ?? null };
  };
  const current = (r: Row, m: string) => edits[keyOf(r, m)] ?? original(r, m);
  const num = (s: string) => (s.trim() === "" ? 0 : Number(s));
  const isDirty = (k: string, r: Row, m: string) => {
    const e = edits[k];
    if (!e) return false;
    const o = original(r, m);
    return num(e.quantity) !== num(o.quantity) || (e.due_date ?? null) !== (o.due_date ?? null) || (e.notes ?? null) !== (o.notes ?? null);
  };
  const dirtyKeys = useMemo(() => {
    const byKey = new Map(rows.flatMap((r) => months.map((m) => [keyOf(r, m), { r, m }] as const)));
    return Object.keys(edits).filter((k) => { const x = byKey.get(k); return x ? isDirty(k, x.r, x.m) : true; });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edits, rows, months]);

  const markets = Array.from(new Map(rows.map((r) => [r.market_id, r])).values()).sort((a, b) => a.market.localeCompare(b.market));
  const shown = rows.filter((r) => (!market || r.market_id === market) &&
    (!q.trim() || [r.code, r.name_en, r.name_ar ?? "", r.market].some((s) => s.toLowerCase().includes(q.trim().toLowerCase()))));
  const products = Array.from(new Set(shown.map((r) => r.item_id)));

  const set = (r: Row, m: string, patch: Partial<Edit>) => setEdits((s) => ({ ...s, [keyOf(r, m)]: { ...current(r, m), ...patch } }));
  const save = async () => {
    setBusy(true); setErr(null); setCellErr(new Set());
    const lines = dirtyKeys.map((k) => {
      const [item_id, market_id, month] = k.split("|");
      const e = edits[k];
      return { item_id, market_id, month, quantity: e.quantity.trim() === "" ? null : Number(e.quantity), due_date: e.due_date || null, notes: e.notes || null };
    });
    try {
      await put(`/api/sites/${siteId}/demand`, { lines });
      setEdits({}); toast(t("sales.savedToast")); grid.reload();
    } catch (e) {
      setErr(errorText(e, t));
      const fields = (e as { fields?: Record<string, string> }).fields ?? {};
      setCellErr(new Set(Object.keys(fields).map((f) => dirtyKeys[Number(f.split(".")[1])]).filter(Boolean)));
    }
    setBusy(false);
  };

  // Totals per month: quantity per product unit is not additive across products, so totals are values per currency.
  const currencies = Array.from(new Set(shown.map((r) => r.currency))).sort();
  const value = (r: Row, m: string) => (r.price ? num(current(r, m).quantity) * r.price : 0);
  const money = (n: number) => qty(n, 0);

  if (!siteId) return <><PageHead title={t("sales.title")} /><Notice>{t("common.noSite")}</Notice></>;
  return (
    <>
      <PageHead title={t("sales.title")} lead={t("sales.lead", { site: site?.name ?? "" })} actions={<>
        <ExcelMenu entity="demand" siteId={siteId} canEdit={canEdit} onImported={() => { setEdits({}); grid.reload(); }} />
        {canEdit && <>
          <Button icon={<LuRotateCcw />} disabled={!dirtyKeys.length} onClick={() => { setEdits({}); setErr(null); setCellErr(new Set()); }}>{t("sales.discard")}</Button>
          <Button variant="primary" icon={<LuSave />} disabled={!dirtyKeys.length} busy={busy} onClick={save}>
            {t("sales.save")}{dirtyKeys.length ? ` (${dirtyKeys.length})` : ""}</Button>
        </>}
      </>} />
      {!feature("sales_plan") && <Notice tone="warn">{t("sales.off")}</Notice>}
      {!canEdit && <Notice>{t("sales.readOnly")}</Notice>}
      {err && <Notice tone="danger">{err}</Notice>}
      <div className="panel">
        <div className="toolbar">
          <div className="month-nav">
            <Button size="sm" variant="ghost" iconOnly aria-label={t("sales.prev")} icon={<LuChevronLeft className="flip-rtl" />} onClick={() => setStart(addMonths(start, -count))} />
            <span className="label">{months.length ? `${fmtMonth(months[0])} – ${fmtMonth(months[months.length - 1])}` : fmtMonth(start)}</span>
            <Button size="sm" variant="ghost" iconOnly aria-label={t("sales.next")} icon={<LuChevronRight className="flip-rtl" />} onClick={() => setStart(addMonths(start, count))} />
            {start !== thisMonth() && <Button size="sm" variant="ghost" onClick={() => setStart(thisMonth())}>{t("sales.thisMonth")}</Button>}
          </div>
          <div className="seg" role="group">
            {[3, 6, 12].map((n) => <button key={n} type="button" aria-pressed={count === n} onClick={() => setCount(n)}>{t("sales.months", { n })}</button>)}
          </div>
          <select className="select" value={market} onChange={(e) => setMarket(e.target.value)} aria-label={t("sales.allMarkets")}>
            <option value="">{t("sales.allMarkets")}</option>
            {markets.map((m) => <option key={m.market_id} value={m.market_id}>{m.market} · {lang === "ar" && m.market_name_ar ? m.market_name_ar : m.market_name_en}</option>)}
          </select>
          <div className="search"><LuSearch aria-hidden />
            <input className="input" type="search" placeholder={t("common.search")} aria-label={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <span className="spacer" />
          {dirtyKeys.length > 0 && <Badge tone="warn" dot>{t("sales.unsaved", { n: dirtyKeys.length })}</Badge>}
        </div>
        {grid.error ? <LoadError error={grid.error} onRetry={grid.reload} /> : grid.data && rows.length === 0 ? (
          <Empty icon={<LuClipboardList />} title={t("sales.empty")} body={t("sales.emptyBody")} />
        ) : (
          <div className="table-wrap">
            <table className="table plan-grid">
              <thead>
                <tr>
                  <th className="sticky-col">{t("sales.product")}</th>
                  {months.map((m) => <th key={m} className="num">{fmtMonth(m)}</th>)}
                  <th className="num">{t("sales.total")}</th>
                  <th className="num">{t("sales.value")}</th>
                </tr>
              </thead>
              <tbody>
                {!grid.data ? (
                  <tr><td colSpan={months.length + 3}><div className="skeleton" style={{ height: 120 }} /></td></tr>
                ) : products.map((pid) => {
                  const group = shown.filter((r) => r.item_id === pid);
                  const p = group[0];
                  return (
                    <Fragment key={pid}>
                      <tr className="group-row"><td colSpan={months.length + 3}>
                        <span className="mono-id cell-main">{p.code}</span> <span className="muted small">{lang === "ar" && p.name_ar ? p.name_ar : p.name_en}</span>
                      </td></tr>
                      {group.map((r) => {
                        const total = months.reduce((s, m) => s + num(current(r, m).quantity), 0);
                        const val = months.reduce((s, m) => s + value(r, m), 0);
                        return (
                          <tr key={r.market_id}>
                            <th scope="row" className="sticky-col">
                              <div className="mkt">
                                <Badge tone="brand">{r.market}</Badge>
                                <span className="small muted">{r.max_qty !== null ? t("sales.limit", { n: qty(r.max_qty, 0) }) : t("sales.noLimit")}</span>
                              </div>
                            </th>
                            {months.map((m) => {
                              const k = keyOf(r, m);
                              const c = current(r, m);
                              const over = r.max_qty !== null && num(c.quantity) > r.max_qty;
                              const dirty = isDirty(k, r, m);
                              return (
                                <td key={m} className={`pcell ${dirty ? "dirty" : ""} ${over ? "over" : ""} ${cellErr.has(k) ? "bad" : ""}`}>
                                  <div className="pcell-in">
                                    <NumInput className="input num" disabled={!canEdit}
                                      value={c.quantity} placeholder="–" aria-label={`${r.code} ${r.market} ${fmtMonth(m)}`}
                                      title={over ? t("sales.overLimit", { n: qty(r.max_qty, 0) }) : c.due_date ? t("sales.dueOn", { date: date(c.due_date, "UTC") }) : undefined}
                                      onChange={(e) => set(r, m, { quantity: e.target.value })} />
                                    <button type="button" className={`due-btn ${c.due_date ? "has" : ""}`} disabled={!canEdit && !c.due_date}
                                      aria-label={t("sales.details")} title={c.due_date ? t("sales.dueOn", { date: date(c.due_date, "UTC") }) : t("sales.details")}
                                      onClick={() => setDetails({ row: r, month: m })}><LuCalendarClock /></button>
                                  </div>
                                  {over && <LuTriangleAlert className="over-icon" aria-label={t("sales.overLimit", { n: qty(r.max_qty, 0) })} />}
                                </td>
                              );
                            })}
                            <td className="num cell-main">{qty(total, 0)} <span className="subtle small">{r.uom}</span></td>
                            <td className="num">{r.price ? <>{money(val)} <span className="subtle small">{r.currency}</span></> : <span className="subtle small">{t("sales.noPrice")}</span>}</td>
                          </tr>
                        );
                      })}
                    </Fragment>
                  );
                })}
              </tbody>
              {grid.data && shown.length > 0 && <tfoot>
                {currencies.map((cur) => {
                  const rs = shown.filter((r) => r.currency === cur);
                  const sum = (m?: string) => rs.reduce((s, r) => s + (m ? value(r, m) : months.reduce((a, mm) => a + value(r, mm), 0)), 0);
                  return (
                    <tr key={cur}>
                      <th scope="row" className="sticky-col">{t("sales.valueRow", { cur })}</th>
                      {months.map((m) => <td key={m} className="num">{money(sum(m))}</td>)}
                      <td />
                      <td className="num cell-main">{money(sum())} <span className="subtle small">{cur}</span></td>
                    </tr>
                  );
                })}
              </tfoot>}
            </table>
          </div>
        )}
      </div>
      {admin && grid.data && grid.data.lines === 0 && rows.length > 0 && (
        <div className="row" style={{ marginTop: 12 }}><Button icon={<LuSparkles />} onClick={() => setSampling(true)}>{t("sd.load")}</Button></div>
      )}
      {details && <DetailsDialog row={details.row} month={details.month} value={current(details.row, details.month)}
        onClose={() => setDetails(null)} onApply={(v) => canEdit && set(details.row, details.month, v)} />}
      {sampling && <Confirm title={t("sd.title")} body={t("sd.body")} confirmLabel={t("sd.load")} onClose={() => setSampling(false)}
        onConfirm={async () => { await post(`/api/sites/${siteId}/sample-demand`); toast(t("sd.done")); setEdits({}); grid.reload(); }} />}
    </>
  );
}
