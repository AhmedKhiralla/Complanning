import { useEffect, useState } from "react";
import { LuPlus, LuRepeat, LuSave, LuTrash2 } from "react-icons/lu";
import {
  Button, Confirm, Empty, LoadError, LoadingRows, Notice, PageHead, SelectField, Sheet, TextField, errorText, fieldErrors, useLoad, useToast,
} from "../../components/ui";
import { NumberField, ReadOnlyNote, TypeBadge, numOrNull, str } from "../../components/master";
import { useFeature, type ItemTimes, type MachineHold } from "../../components/rules";
import { del, get, patch, post, put } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import { nameOf, type ItemType, type Resource } from "../../lib/types";
import { NumInput } from "../../components/numinput";

interface Campaign {
  id: string; item_id: string; item_code: string; item_name_en: string; item_name_ar: string | null; item_type: ItemType;
  resource_id: string | null; resource_code: string | null; max_batches: number | null; max_days: number | null; min_batches: number | null; notes: string | null;
}

function CampaignSheet({ siteId, c, products, machines, onClose, onSaved }: {
  siteId: string; c: Campaign | null; products: ItemTimes[]; machines: Resource[]; onClose: () => void; onSaved: () => void;
}) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const [f, setF] = useState({ item_id: c?.item_id ?? products[0]?.id ?? "", resource_id: c?.resource_id ?? "", max_batches: str(c?.max_batches),
    max_days: str(c?.max_days), min_batches: str(c?.min_batches), notes: c?.notes ?? "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    const body = { max_batches: numOrNull(f.max_batches), max_days: numOrNull(f.max_days), min_batches: numOrNull(f.min_batches), notes: f.notes || null };
    try {
      if (c) await patch(`/api/campaigns/${c.id}`, body);
      else await post(`/api/sites/${siteId}/campaigns`, { ...body, item_id: f.item_id, resource_id: f.resource_id || null });
      toast(t("camp.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={c ? t("camp.form.edit") : t("camp.form.new")} lead={c ? `${c.item_code} · ${c.resource_code ?? t("camp.allMachines")}` : undefined} onClose={onClose} onSubmit={submit}
      footer={<>
        {c && <Button variant="ghost" icon={<LuTrash2 />} onClick={() => setRemoving(true)} style={{ marginInlineEnd: "auto" }}>{t("common.remove")}</Button>}
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button type="submit" variant="primary" busy={busy}>{c ? t("common.save") : t("common.create")}</Button>
      </>}>
      {general && <Notice tone="danger">{general}</Notice>}
      {!c && <>
        <SelectField label={t("camp.product")} value={f.item_id} onChange={(v) => setF({ ...f, item_id: v })} error={errs.item_id}
          options={products.map((p) => ({ value: p.id, label: `${p.code} · ${nameOf(p, lang)}` }))} />
        <SelectField label={t("camp.machine")} value={f.resource_id} onChange={(v) => setF({ ...f, resource_id: v })} error={errs.resource_id}
          options={[{ value: "", label: t("camp.allMachines") }, ...machines.map((m) => ({ value: m.id, label: `${m.code} · ${nameOf(m, lang)}` }))]} />
      </>}
      <div className="grid-2">
        <NumberField label={t("camp.maxBatches")} value={f.max_batches} min={1} step="1" onChange={(v) => setF({ ...f, max_batches: v })} error={errs.max_batches} />
        <NumberField label={t("camp.maxDays")} value={f.max_days} min={0} onChange={(v) => setF({ ...f, max_days: v })} error={errs.max_days} />
      </div>
      <NumberField label={t("camp.minBatches")} value={f.min_batches} min={1} step="1" onChange={(v) => setF({ ...f, min_batches: v })} error={errs.min_batches} />
      <TextField label={t("co.f.notes")} value={f.notes} onChange={(v) => setF({ ...f, notes: v })} />
      {removing && c && <Confirm danger title={t("camp.removeTitle")} body={t("camp.removeBody")} confirmLabel={t("common.remove")} onClose={() => setRemoving(false)}
        onConfirm={async () => { await del(`/api/campaigns/${c.id}`); onSaved(); onClose(); }} />}
    </Sheet>
  );
}

function EquipmentHolds({ siteId, canEdit }: { siteId: string; canEdit: boolean }) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const holds = useLoad(() => get<{ items: MachineHold[] }>(`/api/sites/${siteId}/equipment-holds`), [siteId]);
  const [rows, setRows] = useState<Record<string, { dirty: string; clean: string }>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (holds.data) setRows(Object.fromEntries(holds.data.items.map((m) => [m.id, { dirty: str(m.dirty_hold_hours), clean: str(m.clean_hold_hours) }])));
  }, [holds.data]);
  const items = holds.data?.items ?? [];
  const dirty = items.some((m) => rows[m.id] && (rows[m.id].dirty !== str(m.dirty_hold_hours) || rows[m.id].clean !== str(m.clean_hold_hours)));
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await put<{ items: MachineHold[] }>(`/api/sites/${siteId}/equipment-holds`, {
        rows: items.map((m) => ({ resource_id: m.id, dirty_hold_hours: numOrNull(rows[m.id]?.dirty ?? ""), clean_hold_hours: numOrNull(rows[m.id]?.clean ?? "") })),
      });
      holds.setData(r); toast(t("holds.savedToast"));
    } catch (e) { setErr(errorText(e, t)); }
    setBusy(false);
  };
  const set = (id: string, k: "dirty" | "clean", v: string) => setRows((s) => ({ ...s, [id]: { ...s[id], [k]: v } }));
  return (
    <>
      <div className="section-head">
        <div className="titles"><h2>{t("holds.title")}</h2><p>{t("holds.lead")}</p></div>
        <div className="actions">{canEdit && <Button variant="primary" icon={<LuSave />} disabled={!dirty} busy={busy} onClick={save}>{t("holds.save")}</Button>}</div>
      </div>
      {err && <Notice tone="danger">{err}</Notice>}
      <div className="panel">
        {holds.error ? <LoadError error={holds.error} onRetry={holds.reload} /> : holds.data && items.length === 0 ? <div className="panel-body small subtle">{t("holds.none")}</div> : (
          <div className="table-wrap">
            <table className="table edit-table">
              <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("machines.f.area")}</th><th className="num">{t("holds.dirty")}</th><th className="num">{t("holds.clean")}</th></tr></thead>
              {!holds.data ? <LoadingRows cols={5} rows={6} /> : (
                <tbody>
                  {items.map((m) => (
                    <tr key={m.id}>
                      <td className="mono-id cell-main" dir="ltr" style={{ textAlign: "start" }}>{m.code}</td>
                      <td>{nameOf(m, lang)}</td>
                      <td className="muted small">{m.area}</td>
                      <td className="num"><NumInput className="input num cell-input" disabled={!canEdit}
                        aria-label={`${m.code} ${t("holds.dirty")}`} value={rows[m.id]?.dirty ?? ""} onChange={(e) => set(m.id, "dirty", e.target.value)} /></td>
                      <td className="num"><NumInput className="input num cell-input" disabled={!canEdit}
                        aria-label={`${m.code} ${t("holds.clean")}`} value={rows[m.id]?.clean ?? ""} onChange={(e) => set(m.id, "clean", e.target.value)} /></td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}
      </div>
    </>
  );
}

export function Campaigns() {
  const { t, lang, qty } = useI18n();
  const { editSite, site, siteId } = usePerms();
  const feature = useFeature();
  const camps = useLoad(() => (siteId ? get<{ items: Campaign[] }>(`/api/sites/${siteId}/campaigns`) : Promise.resolve(null)), [siteId]);
  const machinesL = useLoad(() => (siteId ? get<{ items: Resource[] }>(`/api/sites/${siteId}/resources`) : Promise.resolve(null)), [siteId]);
  const productsL = useLoad(() => get<{ items: ItemTimes[] }>("/api/item-times"));
  const [open, setOpen] = useState<Campaign | "new" | null>(null);
  if (!siteId) return <><PageHead title={t("camp.title")} /><Notice>{t("common.noSite")}</Notice></>;
  const canEdit = editSite(siteId);
  const items = camps.data?.items ?? [];
  const machines = (machinesL.data?.items ?? []).filter((m) => m.active && m.type === "machine");
  const products = productsL.data?.items ?? [];
  const showCampaigns = feature("campaign_limits");
  const showHolds = feature("equipment_hold_times");
  const dash = (v: number | null) => (v === null || v === undefined ? <span className="subtle">—</span> : qty(v, 1));

  return (
    <>
      <PageHead title={t("camp.title")} lead={t("camp.lead", { site: site?.name ?? "" })} />
      <ReadOnlyNote show={!canEdit} />
      {showCampaigns && <>
        <div className="section-head" style={{ marginTop: 8 }}>
          <div className="titles"><h2>{t("camp.campaigns")}</h2><p>{t("camp.campaignsLead")}</p></div>
          <div className="actions">{canEdit && products.length > 0 && <Button variant="primary" icon={<LuPlus />} onClick={() => setOpen("new")}>{t("camp.new")}</Button>}</div>
        </div>
        <div className="panel">
          {camps.error ? <LoadError error={camps.error} onRetry={camps.reload} /> : camps.data && items.length === 0 ? (
            <Empty icon={<LuRepeat />} title={t("camp.none")} body={t("camp.campaignsLead")} />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>{t("camp.product")}</th><th>{t("camp.machine")}</th><th className="num">{t("camp.maxBatches")}</th><th className="num">{t("camp.maxDays")}</th><th className="num">{t("camp.minBatches")}</th><th>{t("co.f.notes")}</th></tr></thead>
                {!camps.data ? <LoadingRows cols={6} rows={4} /> : (
                  <tbody>
                    {items.map((c) => (
                      <tr key={c.id} className={canEdit ? "clickable" : ""} onClick={() => canEdit && setOpen(c)}>
                        <td><span className="mono-id cell-main">{c.item_code}</span> <span className="muted small">{nameOf({ name_en: c.item_name_en, name_ar: c.item_name_ar }, lang)}</span> <TypeBadge type={c.item_type} /></td>
                        <td>{c.resource_code ? <span className="mono-id">{c.resource_code}</span> : <span className="muted">{t("camp.allMachines")}</span>}</td>
                        <td className="num">{dash(c.max_batches)}</td>
                        <td className="num">{dash(c.max_days)}</td>
                        <td className="num">{dash(c.min_batches)}</td>
                        <td className="small muted">{c.notes}</td>
                      </tr>
                    ))}
                  </tbody>
                )}
              </table>
            </div>
          )}
        </div>
      </>}
      {showHolds && <EquipmentHolds siteId={siteId} canEdit={canEdit} />}
      {!showCampaigns && !showHolds && <Notice>{t("settings.features.lead")}</Notice>}
      {open && <CampaignSheet siteId={siteId} c={open === "new" ? null : open} products={products} machines={machines} onClose={() => setOpen(null)} onSaved={camps.reload} />}
    </>
  );
}
