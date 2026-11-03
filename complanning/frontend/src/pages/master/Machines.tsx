import { Fragment, useState } from "react";
import { LuFactory, LuPlus, LuSearch, LuTrash2, LuWrench } from "react-icons/lu";
import {
  Badge, Button, Confirm, Empty, LoadError, LoadingRows, Notice, PageHead, SelectField, Sheet, Switch, TextField,
  errorText, fieldErrors, useLoad, useToast,
} from "../../components/ui";
import { ExcelMenu, NumberField, ReadOnlyNote, SampleDataButton, str } from "../../components/master";
import { del, get, patch, post } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { usePerms } from "../../lib/session";
import { nameOf, type Downtime, type Resource } from "../../lib/types";

const RES_TYPES = ["machine", "qc_lab", "room", "operator_group"] as const;
const REASONS = ["maintenance", "calibration", "qualification", "breakdown", "other"] as const;

function MachineSheet({ siteId, res, areas, onClose, onSaved }: { siteId: string; res: Resource | null; areas: string[]; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [f, setF] = useState({ code: res?.code ?? "", name_en: res?.name_en ?? "", name_ar: res?.name_ar ?? "", type: res?.type ?? "machine",
    area: res?.area ?? "", location: res?.location ?? "", efficiency_pct: str(res?.efficiency_pct ?? 100), notes: res?.notes ?? "", active: res?.active ?? true });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF((s) => ({ ...s, [k]: v }));
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    const body = { name_en: f.name_en, name_ar: f.name_ar || null, type: f.type, area: f.area || null, location: f.location || null,
      efficiency_pct: Number(f.efficiency_pct || 100), notes: f.notes || null };
    try {
      if (res) await patch(`/api/resources/${res.id}`, { ...body, active: f.active });
      else await post(`/api/sites/${siteId}/resources`, { ...body, code: f.code });
      toast(t("machines.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={res ? t("machines.form.edit") : t("machines.form.new")} lead={res?.code} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{res ? t("common.save") : t("common.create")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <div className="grid-2">
        <TextField label={t("machines.f.code")} hint={!res ? t("machines.f.codeHint") : undefined} value={f.code} dir="ltr" maxLength={20}
          disabled={!!res} onChange={(v) => set("code")(v.toUpperCase())} error={errs.code} required />
        <SelectField label={t("machines.f.type")} value={f.type} onChange={set("type")} options={RES_TYPES.map((x) => ({ value: x, label: t(`res.${x}` as never) }))} />
      </div>
      <TextField label={t("items.f.nameEn")} value={f.name_en} dir="ltr" onChange={set("name_en")} error={errs.name_en} required />
      <TextField label={t("items.f.nameAr")} value={f.name_ar} dir="rtl" lang="ar" onChange={set("name_ar")} />
      <div className="grid-2">
        <div className="field">
          <label htmlFor="m-area">{t("machines.f.area")}</label>
          <input id="m-area" className="input" list="m-areas" value={f.area} onChange={(e) => set("area")(e.target.value)} />
          <datalist id="m-areas">{areas.map((a) => <option key={a} value={a} />)}</datalist>
          <div className="hint">{t("machines.f.areaHint")}</div>
        </div>
        <TextField label={t("machines.f.location")} value={f.location} onChange={set("location")} />
      </div>
      <NumberField label={t("machines.f.efficiency")} hint={t("machines.f.efficiencyHint")} value={f.efficiency_pct} min={1}
        onChange={set("efficiency_pct")} error={errs.efficiency_pct} suffix="%" />
      <TextField label={t("machines.f.notes")} value={f.notes} onChange={set("notes")} />
      {res && <div className="feature" style={{ padding: "4px 0", border: 0 }}>
        <div className="text"><strong>{t("common.active")}</strong></div>
        <Switch label={t("common.active")} checked={f.active} onChange={(v) => setF({ ...f, active: v })} />
      </div>}
    </Sheet>
  );
}

function DowntimeSheet({ siteId, machines, onClose, onSaved }: { siteId: string; machines: Resource[]; onClose: () => void; onSaved: () => void }) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const now = new Date();
  const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [f, setF] = useState({ resource_id: machines[0]?.id ?? "", starts_at: local(new Date(now.getTime() + 86400000)),
    ends_at: local(new Date(now.getTime() + 2 * 86400000)), reason: "maintenance", notes: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try {
      await post(`/api/sites/${siteId}/downtime`, { ...f, starts_at: new Date(f.starts_at).toISOString(), ends_at: new Date(f.ends_at).toISOString(), notes: f.notes || null });
      toast(t("downtime.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={t("downtime.new")} onClose={onClose} onSubmit={submit}
      footer={<><Button onClick={onClose}>{t("common.cancel")}</Button><Button type="submit" variant="primary" busy={busy}>{t("downtime.new")}</Button></>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <SelectField label={t("downtime.machine")} value={f.resource_id} onChange={(v) => setF({ ...f, resource_id: v })} error={errs.resource_id}
        options={machines.map((m) => ({ value: m.id, label: `${m.code} · ${nameOf(m, lang)}` }))} />
      <div className="grid-2">
        <TextField label={t("downtime.from")} type="datetime-local" value={f.starts_at} onChange={(v) => setF({ ...f, starts_at: v })} />
        <TextField label={t("downtime.to")} type="datetime-local" value={f.ends_at} onChange={(v) => setF({ ...f, ends_at: v })} error={errs.ends_at} />
      </div>
      <SelectField label={t("downtime.reason")} value={f.reason} onChange={(v) => setF({ ...f, reason: v })} options={REASONS.map((r) => ({ value: r, label: t(`reason.${r}` as never) }))} />
      <TextField label={t("downtime.notes")} value={f.notes} onChange={(v) => setF({ ...f, notes: v })} />
    </Sheet>
  );
}

export function Machines() {
  const { t, lang, qty, number, dateTime } = useI18n();
  const { editSite, site, siteId, admin } = usePerms();
  const toast = useToast();
  const [q, setQ] = useState("");
  const res = useLoad(() => (siteId ? get<{ items: Resource[] }>(`/api/sites/${siteId}/resources`) : Promise.resolve(null)), [siteId]);
  const down = useLoad(() => (siteId ? get<{ items: Downtime[] }>(`/api/sites/${siteId}/downtime`) : Promise.resolve(null)), [siteId]);
  const [open, setOpen] = useState<Resource | "new" | null>(null);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Downtime | null>(null);
  if (!siteId) return <><PageHead title={t("machines.title")} /><Notice>{t("common.noSite")}</Notice></>;
  const canEdit = editSite(siteId);
  const all = res.data?.items ?? [];
  const rows = all.filter((r) => !q.trim() || [r.code, r.name_en, r.name_ar ?? "", r.area ?? ""].some((s) => s.toLowerCase().includes(q.trim().toLowerCase())));
  const areas = Array.from(new Set(all.map((r) => r.area).filter(Boolean) as string[])).sort();
  const groups = Array.from(new Set(rows.map((r) => r.area ?? ""))).sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
  const tz = site?.timezone;

  return (
    <>
      <PageHead title={t("machines.title")} lead={t("machines.lead", { site: site?.name ?? "" })} actions={<>
        <ExcelMenu entity="machines" siteId={siteId} canEdit={canEdit} onImported={res.reload} />
        {canEdit && <Button variant="primary" icon={<LuPlus />} onClick={() => setOpen("new")}>{t("machines.new")}</Button>}
      </>} />
      <ReadOnlyNote show={!canEdit} />
      <div className="panel">
        <div className="toolbar">
          <div className="search"><LuSearch aria-hidden />
            <input className="input" type="search" placeholder={t("common.search")} aria-label={t("common.search")} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <span className="spacer" /><span className="small muted">{number(all.length)}</span>
        </div>
        {res.error ? <LoadError error={res.error} onRetry={res.reload} /> : res.data && all.length === 0 ? (
          <Empty icon={<LuFactory />} title={t("machines.empty")} body={t("machines.emptyBody")} action={<div className="row wrap" style={{ justifyContent: "center" }}>
            {canEdit && <Button variant="primary" icon={<LuPlus />} onClick={() => setOpen("new")}>{t("machines.new")}</Button>}
            {admin && <SampleDataButton onLoaded={() => { res.reload(); down.reload(); }} />}
          </div>} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("machines.f.type")}</th><th className="num">{t("machines.efficiency")}</th><th className="num">{t("machines.routings")}</th><th>{t("common.status")}</th></tr></thead>
              {!res.data ? <LoadingRows cols={6} rows={8} /> : (
                <tbody>
                  {groups.map((g) => (
                    <Fragment key={g || "none"}>
                      <tr className="group-row"><td colSpan={6}><strong>{g || t("machines.noArea")}</strong></td></tr>
                      {rows.filter((r) => (r.area ?? "") === g).map((r) => (
                        <tr key={r.id} className={`${canEdit ? "clickable" : ""} ${r.active ? "" : "inactive"}`} onClick={() => canEdit && setOpen(r)}>
                          <td className="mono-id cell-main" dir="ltr" style={{ textAlign: "start" }}>{r.code}</td>
                          <td>{nameOf(r, lang)}</td>
                          <td className="muted">{t(`res.${r.type}` as never)}</td>
                          <td className="num">{qty(r.efficiency_pct, 1)}%</td>
                          <td className="num">{number(r.routing_count)}</td>
                          <td>{r.active ? <Badge tone="ok" dot>{t("common.active")}</Badge> : <Badge>{t("common.inactive")}</Badge>}</td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}
      </div>

      <div className="section-head">
        <div className="titles"><h2>{t("downtime.title")}</h2><p>{t("downtime.lead")}</p></div>
        <div className="actions">{canEdit && all.length > 0 && <Button icon={<LuWrench />} onClick={() => setAdding(true)}>{t("downtime.new")}</Button>}</div>
      </div>
      <div className="panel">
        {down.error ? <LoadError error={down.error} onRetry={down.reload} /> : down.data && down.data.items.length === 0 ? (
          <div className="panel-body small subtle">{t("downtime.none")}</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>{t("downtime.machine")}</th><th>{t("downtime.from")}</th><th>{t("downtime.to")}</th><th>{t("downtime.reason")}</th><th>{t("downtime.notes")}</th><th /></tr></thead>
              {!down.data ? <LoadingRows cols={6} rows={2} /> : (
                <tbody>
                  {down.data.items.map((d) => (
                    <tr key={d.id}>
                      <td><span className="mono-id cell-main">{d.resource_code}</span> <span className="muted small">{nameOf({ name_en: d.resource_name_en, name_ar: d.resource_name_ar }, lang)}</span></td>
                      <td className="small num">{dateTime(d.starts_at, tz)}</td>
                      <td className="small num">{dateTime(d.ends_at, tz)}</td>
                      <td><Badge tone={d.reason === "breakdown" ? "danger" : d.reason === "maintenance" ? "warn" : undefined}>{t(`reason.${d.reason}` as never)}</Badge></td>
                      <td className="small muted">{d.notes}</td>
                      <td className="actions">{canEdit && <Button size="sm" variant="ghost" iconOnly aria-label={t("common.remove")} icon={<LuTrash2 />} onClick={() => setRemoving(d)} />}</td>
                    </tr>
                  ))}
                </tbody>
              )}
            </table>
          </div>
        )}
      </div>
      {open && <MachineSheet siteId={siteId} res={open === "new" ? null : open} areas={areas} onClose={() => setOpen(null)} onSaved={res.reload} />}
      {adding && <DowntimeSheet siteId={siteId} machines={all.filter((m) => m.active)} onClose={() => setAdding(false)} onSaved={down.reload} />}
      {removing && <Confirm danger title={t("downtime.removeTitle")} body={t("downtime.removeBody")} confirmLabel={t("common.remove")} onClose={() => setRemoving(null)}
        onConfirm={async () => { await del(`/api/downtime/${removing.id}`); toast(t("downtime.removedToast")); down.reload(); }} />}
    </>
  );
}
