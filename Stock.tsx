import { Fragment, useEffect, useState } from "react";
import { LuPackage, LuPlus, LuSearch, LuSparkles, LuTrash2 } from "react-icons/lu";
import {
  Badge, Button, Confirm, Empty, Field, LoadError, LoadingRows, Notice, PageHead, SelectField, Sheet, TextField,
  errorText, fieldErrors, useLoad, useToast,
} from "../../components/ui";
import { ExcelMenu, NumberField, TypeBadge, numOrNull, str } from "../../components/master";
import { useFeature } from "../../components/rules";
import { del, get, post, put } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import { ITEM_TYPES, nameOf, type ItemRow, type ItemType } from "../../lib/types";

type Status = "released" | "quarantine" | "rejected";
interface Lot {
  id: string; item_id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; uom: string;
  lot_no: string | null; status: Status; quantity: number; manufactured_on: string | null; expires_on: string | null;
  assay_pct: number | null; lod_pct: number | null; notes: string | null;
}
const STATUSES: Status[] = ["released", "quarantine", "rejected"];
const TONE: Record<Status, "ok" | "warn" | "danger"> = { released: "ok", quarantine: "warn", rejected: "danger" };
const today = () => new Date().toISOString().slice(0, 10);
const daysTo = (d: string) => Math.floor((Date.parse(d + "T00:00:00Z") - Date.parse(today() + "T00:00:00Z")) / 86400000);

function StockSheet({ siteId, lot, items, onClose, onSaved }: { siteId: string; lot: Lot | null; items: ItemRow[]; onClose: () => void; onSaved: () => void }) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const lots = useFeature()("lot_stock");
  const [f, setF] = useState({
    item_id: lot?.item_id ?? "", lot_no: lot?.lot_no ?? "", status: (lot?.status ?? "released") as Status, quantity: str(lot?.quantity),
    manufactured_on: lot?.manufactured_on ?? "", expires_on: lot?.expires_on ?? "", assay_pct: str(lot?.assay_pct), lod_pct: str(lot?.lod_pct), notes: lot?.notes ?? "",
  });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const item = items.find((i) => i.id === f.item_id);
  const isRaw = item?.type === "raw_material";
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    const body = { lot_no: f.lot_no || null, status: f.status, quantity: numOrNull(f.quantity) ?? 0, manufactured_on: f.manufactured_on || null,
      expires_on: f.expires_on || null, assay_pct: numOrNull(f.assay_pct), lod_pct: numOrNull(f.lod_pct), notes: f.notes || null };
    try {
      if (lot) await put(`/api/stock/${lot.id}`, body);
      else await post(`/api/sites/${siteId}/stock`, { ...body, item_id: f.item_id });
      toast(t("stock.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={lot ? t("stock.form.edit") : t("stock.form.new")} lead={lot ? `${lot.code}${lot.lot_no ? " · " + lot.lot_no : ""}` : undefined} onClose={onClose} onSubmit={submit}
      footer={<>
        {lot && <Button variant="ghost" icon={<LuTrash2 />} onClick={() => setRemoving(true)} style={{ marginInlineEnd: "auto" }}>{t("common.remove")}</Button>}
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button type="submit" variant="primary" busy={busy} disabled={!f.item_id}>{lot ? t("common.save") : t("common.create")}</Button>
      </>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <SelectField label={t("stock.item")} value={f.item_id} disabled={!!lot} onChange={(v) => setF({ ...f, item_id: v })} error={errs.item_id}
        options={[{ value: "", label: "—" }, ...ITEM_TYPES.flatMap((ty) => items.filter((i) => i.type === ty && i.active)
          .map((i) => ({ value: i.id, label: `${i.code} · ${nameOf(i, lang)}` })))]} />
      <div className="grid-2">
        {lots && <TextField label={t("stock.lot")} value={f.lot_no} maxLength={40} dir="ltr" onChange={(v) => setF({ ...f, lot_no: v })} error={errs.lot_no} />}
        <NumberField label={t("stock.qty")} value={f.quantity} min={0} suffix={item?.stock_uom} onChange={(v) => setF({ ...f, quantity: v })} error={errs.quantity} required />
      </div>
      <Field label={t("stock.status")} hint={f.status === "quarantine" ? t("stock.st.quarantineHint") : undefined}>{() => (
        <div className="seg" role="group" aria-label={t("stock.status")}>
          {STATUSES.map((s) => <button key={s} type="button" aria-pressed={f.status === s} onClick={() => setF({ ...f, status: s })}>{t(`stock.st.${s}` as never)}</button>)}
        </div>
      )}</Field>
      {lots && <div className="grid-2">
        <TextField label={t("stock.made")} type="date" value={f.manufactured_on} onChange={(v) => setF({ ...f, manufactured_on: v })} />
        <TextField label={t("stock.expires")} type="date" value={f.expires_on} onChange={(v) => setF({ ...f, expires_on: v })} error={errs.expires_on} />
      </div>}
      {lots && isRaw && <div className="grid-2">
        <NumberField label={t("stock.assay")} value={f.assay_pct} min={0} onChange={(v) => setF({ ...f, assay_pct: v })} error={errs.assay_pct} />
        <NumberField label={t("stock.lod")} value={f.lod_pct} min={0} onChange={(v) => setF({ ...f, lod_pct: v })} error={errs.lod_pct} />
      </div>}
      <TextField label={t("stock.notes")} value={f.notes} maxLength={300} onChange={(v) => setF({ ...f, notes: v })} />
      {removing && lot && <Confirm danger title={t("stock.removeTitle")} body={t("stock.removeBody")} confirmLabel={t("common.remove")} onClose={() => setRemoving(false)}
        onConfirm={async () => { await del(`/api/stock/${lot.id}`); toast(t("stock.removedToast")); onSaved(); onClose(); }} />}
    </Sheet>
  );
}

export function StockPage() {
  const { t, lang, qty, date, number } = useI18n();
  const { planSite, site, siteId, admin } = usePerms();
  const toast = useToast();
  const lots = useFeature()("lot_stock");
  const data = useLoad(() => (siteId ? get<{ as_of: string | null; items: Lot[] }>(`/api/sites/${siteId}/stock`) : Promise.resolve(null)), [siteId]);
  const items = useLoad(() => get<{ items: ItemRow[] }>("/api/items"));
  const [q, setQ] = useState("");
  const [type, setType] = useState<ItemType | "">("");
  const [status, setStatus] = useState<Status | "">("");
  const [open, setOpen] = useState<Lot | "new" | null>(null);
  const [asOf, setAsOf] = useState("");
  const [sampling, setSampling] = useState(false);
  useEffect(() => { setAsOf(data.data?.as_of ?? ""); }, [data.data?.as_of]);
  if (!siteId) return <><PageHead title={t("stock.title")} /><Notice>{t("common.noSite")}</Notice></>;
  const canEdit = planSite(siteId);
  const all = data.data?.items ?? [];
  const rows = all.filter((l) => (!type || l.type === type) && (!status || l.status === status) &&
    (!q.trim() || [l.code, l.name_en, l.name_ar ?? "", l.lot_no ?? ""].some((s) => s.toLowerCase().includes(q.trim().toLowerCase()))));
  const groups = Array.from(new Set(rows.map((l) => l.item_id)));
  const usable = all.filter((l) => l.status !== "rejected" && l.expires_on);
  const expired = usable.filter((l) => daysTo(l.expires_on!) < 0).length;
  const soon = usable.filter((l) => { const d = daysTo(l.expires_on!); return d >= 0 && d <= 90; }).length;
  const saveAsOf = async (v: string) => {
    setAsOf(v);
    try { await put(`/api/sites/${siteId}/stock-date`, { stock_as_of: v || null }); toast(t("stock.asOfSaved")); } catch { data.reload(); }
  };

  return (
    <>
      <PageHead title={t("stock.title")} lead={t("stock.lead", { site: site?.name ?? "" })} actions={<>
        <ExcelMenu entity="stock" siteId={siteId} canEdit={canEdit} onImported={data.reload} />
        {canEdit && <Button variant="primary" icon={<LuPlus />} onClick={() => setOpen("new")}>{t("stock.new")}</Button>}
      </>} />
      {!canEdit && <Notice>{t("stock.readOnly")}</Notice>}
      <div className="stock-bar">
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor="stock-asof">{t("stock.asOf")}</label>
          <input id="stock-asof" className="input" type="date" value={asOf} disabled={!canEdit} onChange={(e) => saveAsOf(e.target.value)} />
        </div>
        <span className="small subtle grow">{t("stock.asOfHint")}</span>
        <div className="chip-row">
          <Badge tone="ok">{t("stock.chip.released", { n: number(all.filter((l) => l.status === "released").length) })}</Badge>
          <Badge tone="warn">{t("stock.chip.quarantine", { n: number(all.filter((l) => l.status === "quarantine").length) })}</Badge>
          {soon > 0 && <Badge tone="warn">{t("stock.chip.soon", { n: number(soon) })}</Badge>}
          {expired > 0 && <Badge tone="danger">{t("stock.chip.expired", { n: number(expired) })}</Badge>}
        </div>
      </div>
      <div className="panel">
        <div className="toolbar">
          <div className="search"><LuSearch aria-hidden />
            <input className="input" type="search" placeholder={t("common.search")} aria-label={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <select className="select" value={type} onChange={(e) => setType(e.target.value as ItemType | "")} aria-label={t("stock.allTypes")}>
            <option value="">{t("stock.allTypes")}</option>
            {ITEM_TYPES.map((x) => <option key={x} value={x}>{t(`type.${x}` as never)}</option>)}
          </select>
          <select className="select" value={status} onChange={(e) => setStatus(e.target.value as Status | "")} aria-label={t("stock.allStatus")}>
            <option value="">{t("stock.allStatus")}</option>
            {STATUSES.map((x) => <option key={x} value={x}>{t(`stock.st.${x}` as never)}</option>)}
          </select>
          <span className="spacer" /><span className="small muted">{t("stock.lines", { n: number(rows.length) })}</span>
        </div>
        {data.error ? <LoadError error={data.error} onRetry={data.reload} /> : data.data && all.length === 0 ? (
          <Empty icon={<LuPackage />} title={t("stock.empty")} body={t("stock.emptyBody")} action={<div className="row wrap" style={{ justifyContent: "center" }}>
            {canEdit && <Button variant="primary" icon={<LuPlus />} onClick={() => setOpen("new")}>{t("stock.new")}</Button>}
            {admin && <Button icon={<LuSparkles />} onClick={() => setSampling(true)}>{t("sd.load")}</Button>}
          </div>} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                {lots && <th>{t("stock.lot")}</th>}<th>{t("stock.status")}</th><th className="num">{t("stock.qty")}</th>
                {lots && <><th>{t("stock.made")}</th><th>{t("stock.expires")}</th><th className="num">{t("stock.assay")}</th></>}
                <th>{t("stock.notes")}</th>
              </tr></thead>
              {!data.data ? <LoadingRows cols={7} rows={8} /> : (
                <tbody>
                  {groups.map((iid) => {
                    const ls = rows.filter((l) => l.item_id === iid);
                    const it = ls[0];
                    const sum = (s: Status) => ls.filter((l) => l.status === s).reduce((a, l) => a + Number(l.quantity), 0);
                    return (
                      <Fragment key={iid}>
                        <tr className="group-row"><td colSpan={lots ? 7 : 4}>
                          <div className="row wrap" style={{ gap: 8 }}>
                            <span className="mono-id cell-main">{it.code}</span><span className="muted small">{nameOf(it, lang)}</span><TypeBadge type={it.type} />
                            <span className="spacer" />
                            <span className="small"><strong>{qty(sum("released"))}</strong> <span className="subtle">{it.uom} {t("stock.st.released").toLowerCase()}</span></span>
                            {sum("quarantine") > 0 && <span className="small"><strong>{qty(sum("quarantine"))}</strong> <span className="subtle">{t("stock.st.quarantine").toLowerCase()}</span></span>}
                          </div>
                        </td></tr>
                        {ls.map((l) => {
                          const d = l.expires_on && l.status !== "rejected" ? daysTo(l.expires_on) : null;
                          return (
                            <tr key={l.id} className={canEdit ? "clickable" : ""} onClick={() => canEdit && setOpen(l)}>
                              {lots && <td className="mono-id" dir="ltr" style={{ textAlign: "start" }}>{l.lot_no ?? <span className="subtle">—</span>}</td>}
                              <td><Badge tone={TONE[l.status]} dot>{t(`stock.st.${l.status}` as never)}</Badge></td>
                              <td className="num cell-main">{qty(l.quantity)} <span className="subtle small">{l.uom}</span></td>
                              {lots && <>
                                <td className="small num">{date(l.manufactured_on, "UTC")}</td>
                                <td className="small num">
                                  {date(l.expires_on, "UTC")}
                                  {d !== null && d < 0 && <> <Badge tone="danger">{t("stock.expired")}</Badge></>}
                                  {d !== null && d >= 0 && d <= 90 && <> <Badge tone="warn">{t("stock.expiresSoon")}</Badge></>}
                                </td>
                                <td className="num small">{l.assay_pct !== null ? qty(l.assay_pct, 2) : ""}{l.lod_pct !== null ? <span className="subtle"> · LOD {qty(l.lod_pct, 2)}</span> : ""}</td>
                              </>}
                              <td className="small muted">{l.notes}</td>
                            </tr>
                          );
                        })}
                      </Fragment>
                    );
                  })}
                </tbody>
              )}
            </table>
          </div>
        )}
      </div>
      {open && <StockSheet siteId={siteId} lot={open === "new" ? null : open} items={items.data?.items ?? []} onClose={() => setOpen(null)} onSaved={data.reload} />}
      {sampling && <Confirm title={t("sd.title")} body={t("sd.body")} confirmLabel={t("sd.load")} onClose={() => setSampling(false)}
        onConfirm={async () => { await post(`/api/sites/${siteId}/sample-demand`); toast(t("sd.done")); data.reload(); }} />}
    </>
  );
}
