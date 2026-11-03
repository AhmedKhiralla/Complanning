import { useEffect, useMemo, useState } from "react";
import { LuRotateCcw, LuSave, LuSearch, LuTimer } from "react-icons/lu";
import { Button, Empty, LoadError, LoadingRows, Notice, PageHead, Switch, errorText, fieldErrors, useLoad, useToast } from "../../components/ui";
import { ReadOnlyNote, TypeBadge, numOrNull, str } from "../../components/master";
import { useFeature, type CleaningGroup, type ItemTimes } from "../../components/rules";
import { get, put } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import { nameOf } from "../../lib/types";

interface Row { cleaning_group: string; min: string; max: string; qc: string; atRisk: boolean; testSale: boolean; }
const toRow = (i: ItemTimes): Row => ({ cleaning_group: i.cleaning_group ?? "", min: str(i.hold_min_hours), max: str(i.hold_max_hours),
  qc: str(i.release_lead_days), atRisk: i.release_at_risk_allowed, testSale: i.test_before_sale });
const same = (a: Row, b: Row) => (Object.keys(a) as (keyof Row)[]).every((k) => a[k] === b[k]);

export function ItemTimesPage() {
  const { t, lang } = useI18n();
  const { editCompany } = usePerms();
  const toast = useToast();
  const feature = useFeature();
  const data = useLoad(() => get<{ items: ItemTimes[] }>("/api/item-times"));
  const groupsL = useLoad(() => get<{ items: CleaningGroup[] }>("/api/cleaning-groups"));
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [rowErrs, setRowErrs] = useState<Record<string, string>>({});
  useEffect(() => { if (data.data) setRows(Object.fromEntries(data.data.items.map((i) => [i.id, toRow(i)]))); }, [data.data]);
  const items = data.data?.items ?? [];
  const groups = groupsL.data?.items ?? [];
  const changed = useMemo(() => items.filter((i) => rows[i.id] && !same(rows[i.id], toRow(i))), [items, rows]);
  const shown = items.filter((i) => !q.trim() || [i.code, i.name_en, i.name_ar ?? "", i.cleaning_group ?? ""].some((s) => s.toLowerCase().includes(q.trim().toLowerCase())));
  const ro = !editCompany;
  const show = { hold: feature("holding_times"), qc: feature("qc_lead_times"), risk: feature("release_at_risk") };
  const set = (id: string, patch: Partial<Row>) => setRows((s) => ({ ...s, [id]: { ...s[id], ...patch } }));

  const save = async () => {
    setBusy(true); setErr(null); setRowErrs({});
    try {
      const body = { rows: changed.map((i) => { const r = rows[i.id]; return {
        item_id: i.id, cleaning_group: r.cleaning_group || null, hold_min_hours: numOrNull(r.min), hold_max_hours: numOrNull(r.max),
        release_lead_days: numOrNull(r.qc), release_at_risk_allowed: r.atRisk, test_before_sale: r.testSale,
      }; }) };
      const res = await put<{ items: ItemTimes[] }>("/api/item-times", body);
      data.setData(res); toast(t("times.savedToast"));
    } catch (e) {
      const fe = fieldErrors(e);
      const byItem: Record<string, string> = {};
      Object.entries(fe).forEach(([k, v]) => { const n = Number(k.split(".")[1]); if (changed[n]) byItem[changed[n].id] = v; });
      setRowErrs(byItem); setErr(errorText(e, t));
    }
    setBusy(false);
  };

  return (
    <>
      <PageHead title={t("times.title")} lead={t("times.lead")} actions={editCompany && <>
        <Button icon={<LuRotateCcw />} disabled={!changed.length} onClick={() => { setRows(Object.fromEntries(items.map((i) => [i.id, toRow(i)]))); setRowErrs({}); setErr(null); }}>{t("common.cancel")}</Button>
        <Button variant="primary" icon={<LuSave />} disabled={!changed.length} busy={busy} onClick={save}>{t("times.save")}{changed.length ? ` (${changed.length})` : ""}</Button>
      </>} />
      <ReadOnlyNote show={ro} />
      {err && <Notice tone="danger">{err}</Notice>}
      <div className="panel">
        <div className="toolbar">
          <div className="search"><LuSearch aria-hidden />
            <input className="input" type="search" placeholder={t("common.search")} aria-label={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <span className="spacer" />
        </div>
        {data.error ? <LoadError error={data.error} onRetry={data.reload} /> : data.data && items.length === 0 ? (
          <Empty icon={<LuTimer />} title={t("times.none")} />
        ) : (
          <div className="table-wrap">
            <table className="table edit-table">
              <thead><tr>
                <th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("times.group")}</th>
                {show.hold && <><th className="num">{t("times.minWait")}</th><th className="num">{t("times.maxHold")}</th></>}
                {show.qc && <th className="num">{t("times.qc")}</th>}
                {show.risk && <th className="center">{t("times.atRisk")}</th>}
                <th className="center">{t("times.testSale")}</th>
              </tr></thead>
              {!data.data ? <LoadingRows cols={8} rows={8} /> : (
                <tbody>
                  {shown.map((i) => {
                    const r = rows[i.id]; if (!r) return null;
                    const dirty = !same(r, toRow(i));
                    const bad = rowErrs[i.id];
                    return [
                      <tr key={i.id} className={`${dirty ? "row-dirty" : ""} ${bad ? "row-error" : ""}`}>
                        <td className="mono-id cell-main" dir="ltr" style={{ textAlign: "start" }}>{i.code}</td>
                        <td><span className="row" style={{ gap: 6 }}><span className="ellipsis">{nameOf(i, lang)}</span><TypeBadge type={i.type} /></span></td>
                        <td>
                          <select className="select cell-input" value={r.cleaning_group} disabled={ro} aria-label={`${i.code} ${t("times.group")}`} onChange={(e) => set(i.id, { cleaning_group: e.target.value })}>
                            <option value="">—</option>
                            {groups.map((g) => <option key={g.code} value={g.code}>{g.code}</option>)}
                            {r.cleaning_group && !groups.some((g) => g.code === r.cleaning_group) && <option value={r.cleaning_group}>{r.cleaning_group}</option>}
                          </select>
                        </td>
                        {show.hold && <>
                          <td className="num"><input className="input num cell-input" type="number" min={0} step="any" disabled={ro} aria-label={`${i.code} ${t("times.minWait")}`} value={r.min} onChange={(e) => set(i.id, { min: e.target.value })} /></td>
                          <td className="num"><input className="input num cell-input" type="number" min={0} step="any" disabled={ro} aria-label={`${i.code} ${t("times.maxHold")}`} value={r.max} onChange={(e) => set(i.id, { max: e.target.value })} /></td>
                        </>}
                        {show.qc && <td className="num"><input className="input num cell-input" type="number" min={0} step="any" disabled={ro} aria-label={`${i.code} ${t("times.qc")}`} value={r.qc} onChange={(e) => set(i.id, { qc: e.target.value })} /></td>}
                        {show.risk && <td className="center"><Switch label={`${i.code} ${t("times.atRisk")}`} checked={r.atRisk} disabled={ro} onChange={(v) => set(i.id, { atRisk: v })} /></td>}
                        <td className="center">{i.type === "finished" ? <Switch label={`${i.code} ${t("times.testSale")}`} checked={r.testSale} disabled={ro} onChange={(v) => set(i.id, { testSale: v })} /> : <span className="subtle">—</span>}</td>
                      </tr>,
                      bad && <tr key={i.id + "-e"} className="row-error-msg"><td colSpan={8} className="small">{bad}</td></tr>,
                    ];
                  })}
                </tbody>
              )}
            </table>
          </div>
        )}
        <div className="panel-body small muted" style={{ borderTop: "1px solid var(--line)" }}>{t("times.hint")}</div>
      </div>
    </>
  );
}
