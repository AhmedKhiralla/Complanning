/* Company settings › Production orders: one template per order kind (packaging, manufacturing). */
import { useEffect, useMemo, useState } from "react";
import { LuArrowDown, LuArrowUp, LuEye, LuImagePlus, LuPlus, LuTrash2 } from "react-icons/lu";
import { NumInput } from "../../components/numinput";
import { Button, Dialog, Field, LoadError, Notice, SelectField, Switch, TextField, errorText, fieldErrors, useLoad, useToast } from "../../components/ui";
import { ApiError, get, put } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { useSession } from "../../lib/session";
import type { StringKey } from "../../lib/strings";

export interface OrderTemplate {
  id: string; kind: "packaging" | "manufacturing"; name: string; title: string; format_number: string | null; number_pattern: string;
  next_seq: number; orientation: "landscape" | "portrait"; logo: string | null; header_columns: number;
  header_fields: { key: string; label: string }[]; columns: { key: string; label: string }[]; component_types: string[];
  signatures: { title: string }[]; require_esign: boolean; remarks_label: string | null; remarks_lines: number;
  footer_note: string | null; is_default: boolean; active: boolean;
}
interface Vocab { items: OrderTemplate[]; header_fields: Record<string, string>; columns: Record<string, string>; item_types: string[] }
type Row = { key: string; label: string; on: boolean };

/** Included fields first (in their order), then the rest with their default labels. */
function rowsOf(chosen: { key: string; label: string }[], all: Record<string, string>): Row[] {
  const on = chosen.filter((c) => c.key in all).map((c) => ({ ...c, on: true }));
  const rest = Object.entries(all).filter(([k]) => !chosen.some((c) => c.key === k)).map(([key, label]) => ({ key, label, on: false }));
  return [...on, ...rest];
}

function expand(pattern: string, seq: number): string {
  const d = new Date();
  return pattern.replace(/\{([A-Z]+)(?::(\d+))?\}/g, (m, tok: string, w?: string) => {
    if (tok === "YY") return String(d.getFullYear() % 100).padStart(2, "0");
    if (tok === "YYYY") return String(d.getFullYear());
    if (tok === "MM") return String(d.getMonth() + 1).padStart(2, "0");
    if (tok === "DD") return String(d.getDate()).padStart(2, "0");
    if (tok === "BATCH") return "26013";
    if (tok === "CODE") return "FP_01";
    if (tok === "SEQ") return String(seq).padStart(Number(w || 1), "0");
    return m;
  });
}

function FieldRows({ rows, setRows, label }: { rows: Row[]; setRows: (r: Row[]) => void; label: string }) {
  const { t } = useI18n();
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const next = [...rows];
    [next[i], next[j]] = [next[j], next[i]];
    setRows(next);
  };
  return (
    <div className="ot-rows" role="list" aria-label={label}>
      {rows.map((r, i) => (
        <div key={r.key} className={`ot-row ${r.on ? "" : "off"}`} role="listitem">
          <input type="checkbox" className="cb" checked={r.on} aria-label={r.label}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, on: e.target.checked } : x)))} />
          <input className="input" value={r.label} maxLength={60} disabled={!r.on} aria-label={`${r.key} label`}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
          <span className="mono-id small subtle">{r.key}</span>
          <button type="button" className="icon-btn" aria-label={t("ot.moveUp")} disabled={i === 0} onClick={() => move(i, -1)}><LuArrowUp /></button>
          <button type="button" className="icon-btn" aria-label={t("ot.moveDown")} disabled={i === rows.length - 1} onClick={() => move(i, 1)}><LuArrowDown /></button>
        </div>
      ))}
    </div>
  );
}

export function OrderTemplatesTab() {
  const { t } = useI18n();
  const { me } = useSession();
  const admin = !!me?.user.is_tenant_admin;
  const data = useLoad(() => get<Vocab>("/api/order-templates"));
  const [kind, setKind] = useState<"packaging" | "manufacturing">("packaging");
  const tpl = useMemo(() => data.data?.items.find((x) => x.kind === kind && x.is_default) ?? data.data?.items.find((x) => x.kind === kind), [data.data, kind]);
  if (data.error) return <LoadError error={data.error} onRetry={data.reload} />;
  if (!data.data || !tpl) return <div className="skeleton" style={{ width: "40%" }} />;
  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>{t("ot.lead")}</p>
      {!admin && <Notice>{t("ot.adminOnly")}</Notice>}
      <div className="seg" role="group" aria-label={t("settings.tab.orders")}>
        {(["packaging", "manufacturing"] as const).map((k) => (
          <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>{t(`ot.kind.${k}` as StringKey)}</button>
        ))}
      </div>
      <Editor key={tpl.id + tpl.kind} tpl={tpl} vocab={data.data} readOnly={!admin} onSaved={() => data.reload()} />
    </div>
  );
}

function Editor({ tpl, vocab, readOnly, onSaved }: { tpl: OrderTemplate; vocab: Vocab; readOnly: boolean; onSaved: () => void }) {
  const { t, tx } = useI18n();
  const toast = useToast();
  const [f, setF] = useState(tpl);
  const [heads, setHeads] = useState(() => rowsOf(tpl.header_fields, vocab.header_fields));
  const [cols, setCols] = useState(() => rowsOf(tpl.columns, vocab.columns));
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const body = () => ({
    name: f.name, title: f.title, format_number: f.format_number || null, number_pattern: f.number_pattern, next_seq: Number(f.next_seq) || 1,
    orientation: f.orientation, logo: f.logo, header_columns: f.header_columns,
    header_fields: heads.filter((r) => r.on).map(({ key, label }) => ({ key, label })),
    columns: cols.filter((r) => r.on).map(({ key, label }) => ({ key, label })),
    component_types: f.component_types, signatures: f.signatures.filter((s) => s.title.trim()), require_esign: f.require_esign,
    remarks_label: f.remarks_label || null, remarks_lines: Number(f.remarks_lines) || 0, footer_note: f.footer_note || null, active: f.active,
  });
  const save = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    try { await put(`/api/order-templates/${tpl.id}`, body()); toast(t("ot.saved")); onSaved(); }
    catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); }
    finally { setBusy(false); }
  };
  const showPreview = async () => {
    setGeneral(null);
    try {
      const res = await fetch(`/api/order-templates/preview?kind=${tpl.kind}`, {
        method: "POST", credentials: "same-origin", body: JSON.stringify(body()),
        headers: { "Content-Type": "application/json", "X-Requested-With": "complanning" },
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new ApiError(res.status, j.error?.code ?? "error", j.error?.message ?? res.statusText, j.error?.fields ?? {});
      }
      setPreview(URL.createObjectURL(await res.blob()));
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); }
  };
  const pickLogo = (file: File | undefined) => {
    if (!file) return;
    if (file.size > 1_000_000) { setErrs({ logo: t("ot.logoTooBig") }); return; }
    const r = new FileReader();
    r.onload = () => setF({ ...f, logo: String(r.result) });
    r.readAsDataURL(file);
  };
  const ro = readOnly;
  const typeLabel = (x: string) => tx(`type.${x}`, x);

  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); save(); }}>
      {general && <Notice tone="danger">{general}</Notice>}
      <section className="panel"><div className="panel-head"><h3>{t("ot.doc")}</h3></div><div className="panel-body stack">
        <div className="grid-2">
          <TextField label={t("ot.title")} value={f.title} maxLength={120} disabled={ro} error={errs.title} onChange={(v) => setF({ ...f, title: v })} required />
          <TextField label={t("ot.name")} value={f.name} maxLength={80} disabled={ro} error={errs.name} onChange={(v) => setF({ ...f, name: v })} required />
          <TextField label={t("ot.formatNumber")} hint={t("ot.formatHint")} value={f.format_number ?? ""} maxLength={60} disabled={ro}
            onChange={(v) => setF({ ...f, format_number: v })} />
          <SelectField label={t("ot.orientation")} value={f.orientation} disabled={ro} onChange={(v) => setF({ ...f, orientation: v as OrderTemplate["orientation"] })}
            options={[{ value: "landscape", label: t("ot.landscape") }, { value: "portrait", label: t("ot.portrait") }]} />
        </div>
        <Field label={t("ot.logo")} hint={t("ot.logoHint")} error={errs.logo}>{(id) => (
          <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
            {f.logo && <img src={f.logo} alt="" className="ot-logo" />}
            {!ro && <label className="btn" htmlFor={id}><LuImagePlus aria-hidden />{t("ot.logoChoose")}
              <input id={id} type="file" accept="image/png,image/jpeg" hidden onChange={(e) => pickLogo(e.target.files?.[0])} /></label>}
            {!ro && f.logo && <Button variant="ghost" icon={<LuTrash2 />} onClick={() => setF({ ...f, logo: null })}>{t("ot.logoRemove")}</Button>}
          </div>
        )}</Field>
        <TextField label={t("ot.footer")} hint={t("ot.footerHint")} value={f.footer_note ?? ""} maxLength={140} disabled={ro}
          onChange={(v) => setF({ ...f, footer_note: v })} />
      </div></section>

      <section className="panel"><div className="panel-head"><h3>{t("ot.numbering")}</h3></div><div className="panel-body grid-2">
        <TextField label={t("ot.pattern")} hint={t("ot.patternHint")} value={f.number_pattern} maxLength={80} dir="ltr" disabled={ro}
          error={errs.number_pattern} onChange={(v) => setF({ ...f, number_pattern: v })} required />
        <Field label={t("ot.nextSeq")} hint={t("ot.example", { n: expand(f.number_pattern, Number(f.next_seq) || 1) })}>{(id) => (
          <NumInput id={id} value={f.next_seq} disabled={ro} onChange={(e) => setF({ ...f, next_seq: Number(e.target.value) || 1 })} />
        )}</Field>
      </div></section>

      <section className="panel"><div className="panel-head"><h3>{t("ot.header")}</h3><p className="small muted">{t("ot.headerLead")}</p></div>
        <div className="panel-body stack">
          <div style={{ maxWidth: 220 }}>
            <SelectField label={t("ot.headerCols")} value={String(f.header_columns)} disabled={ro}
              onChange={(v) => setF({ ...f, header_columns: Number(v) })} options={[1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }))} />
          </div>
          <FieldRows rows={heads} setRows={ro ? () => undefined : setHeads} label={t("ot.header")} />
        </div></section>

      <section className="panel"><div className="panel-head"><h3>{t("ot.columns")}</h3><p className="small muted">{t("ot.columnsLead")}</p></div>
        <div className="panel-body stack">
          <Field label={t("ot.types")} hint={t("ot.typesHint")} error={errs.component_types}>{() => (
            <div className="row" style={{ gap: 16, flexWrap: "wrap" }}>
              {vocab.item_types.map((x) => (
                <label key={x} className="row small" style={{ gap: 6 }}>
                  <input type="checkbox" className="cb" disabled={ro} checked={f.component_types.includes(x)}
                    onChange={(e) => setF({ ...f, component_types: e.target.checked ? [...f.component_types, x] : f.component_types.filter((y) => y !== x) })} />
                  {typeLabel(x)}
                </label>
              ))}
            </div>
          )}</Field>
          {errs.columns && <Notice tone="danger">{errs.columns}</Notice>}
          <FieldRows rows={cols} setRows={ro ? () => undefined : setCols} label={t("ot.columns")} />
        </div></section>

      <section className="panel"><div className="panel-head"><h3>{t("ot.approvals")}</h3><p className="small muted">{t("ot.approvalsLead")}</p></div>
        <div className="panel-body stack">
          {f.signatures.map((s, i) => (
            <div key={i} className="ot-row">
              <span className="step-no">{i + 1}</span>
              <input className="input" value={s.title} maxLength={60} disabled={ro} placeholder={t("ot.levelPh")} aria-label={`${t("ot.approvals")} ${i + 1}`}
                onChange={(e) => setF({ ...f, signatures: f.signatures.map((x, j) => (j === i ? { title: e.target.value } : x)) })} />
              <span />
              <button type="button" className="icon-btn" aria-label={t("ot.moveUp")} disabled={ro || i === 0}
                onClick={() => { const n = [...f.signatures]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; setF({ ...f, signatures: n }); }}><LuArrowUp /></button>
              <button type="button" className="icon-btn" aria-label={t("common.remove")} disabled={ro}
                onClick={() => setF({ ...f, signatures: f.signatures.filter((_, j) => j !== i) })}><LuTrash2 /></button>
            </div>
          ))}
          {!ro && f.signatures.length < 8 && <div><Button icon={<LuPlus />} onClick={() => setF({ ...f, signatures: [...f.signatures, { title: "" }] })}>{t("ot.addLevel")}</Button></div>}
          <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
            <Switch label={t("ot.esign")} checked={f.require_esign} disabled={ro} onChange={(v) => setF({ ...f, require_esign: v })} />
            <div><strong className="small">{t("ot.esign")}</strong><div className="small muted">{t("ot.esignHint")}</div></div>
          </div>
        </div></section>

      <section className="panel"><div className="panel-head"><h3>{t("ot.remarks")}</h3></div><div className="panel-body grid-2">
        <TextField label={t("ot.remarksLabel")} value={f.remarks_label ?? ""} maxLength={60} disabled={ro} onChange={(v) => setF({ ...f, remarks_label: v })} />
        <Field label={t("ot.remarksLines")}>{(id) => (
          <NumInput id={id} value={f.remarks_lines} disabled={ro} onChange={(e) => setF({ ...f, remarks_lines: Math.min(10, Number(e.target.value) || 0) })} />
        )}</Field>
      </div></section>

      <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
        <Button icon={<LuEye />} onClick={showPreview}>{t("ot.preview")}</Button>
        {!ro && <Button type="submit" variant="primary" busy={busy}>{t("common.save")}</Button>}
      </div>

      {preview && (
        <Dialog title={t("ot.previewTitle")} onClose={() => setPreview(null)} footer={<Button onClick={() => setPreview(null)}>{t("common.close")}</Button>}>
          <iframe src={preview} title={t("ot.previewTitle")} className="ot-preview" />
        </Dialog>
      )}
    </form>
  );
}
