// Shared pieces for master-data screens.
import { useRef, useState } from "react";
import { LuChevronDown, LuDownload, LuFileSpreadsheet, LuSparkles, LuUpload } from "react-icons/lu";
import { ApiError, get, post, qs } from "../lib/api";
import { navigate } from "../lib/router";
import { useI18n } from "../lib/i18n";
import type { ItemType, Market, Uom } from "../lib/types";
import { Badge, Button, Confirm, Dialog, Field, Menu, Notice, errorText, useLoad, useToast } from "./ui";

export function TypeBadge({ type }: { type: ItemType }) {
  const { tx } = useI18n();
  const tone = type === "finished" ? "brand" : type === "semi_finished" ? "warn" : type === "wip" ? "ok" : undefined;
  return <Badge tone={tone}>{tx(`type.${type}`, type)}</Badge>;
}

export function NumberField({ label, hint, error, value, onChange, disabled, suffix, min, step = "any", required }: {
  label: string; hint?: string; error?: string; value: string; onChange: (v: string) => void; disabled?: boolean;
  suffix?: string; min?: number; step?: string; required?: boolean;
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, describedBy) => (
        <div className="input-suffix">
          <input id={id} className="input num" type="number" inputMode="decimal" step={step} min={min} value={value}
            disabled={disabled} required={required} aria-invalid={!!error} aria-describedby={describedBy}
            onChange={(e) => onChange(e.target.value)} />
          {suffix && <span className="suffix">{suffix}</span>}
        </div>
      )}
    </Field>
  );
}

/** "" -> null, "12.5" -> 12.5 for API bodies. */
export const numOrNull = (v: string) => (v.trim() === "" ? null : Number(v));
export const str = (v: number | string | null | undefined) => (v === null || v === undefined ? "" : String(v));

export function useUoms() {
  return useLoad(() => get<{ items: Uom[] }>("/api/uoms"));
}
export function useMarkets() {
  return useLoad(() => get<{ items: Market[] }>("/api/markets"));
}

interface ImportSummary {
  rows: number; create: number; update: number; error_count: number; committed: boolean;
  errors: { row: number; code: string | null; problems: string[] }[];
}

async function upload(entity: string, siteId: string | undefined, file: File, commit: boolean): Promise<ImportSummary> {
  const res = await fetch("/api/master/import" + qs({ entity, site_id: siteId, commit: commit ? 1 : 0 }), {
    method: "POST", body: file, credentials: "same-origin",
    headers: { "X-Requested-With": "complanning", "Content-Type": "application/octet-stream" },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data?.error?.code ?? "server_error", data?.error?.message ?? res.statusText);
  return data;
}

function ImportDialog({ entity, siteId, onClose, onDone }: { entity: "items" | "machines"; siteId?: string; onClose: () => void; onDone: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const run = async (commit: boolean) => {
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const s = await upload(entity, siteId, file, commit);
      setSummary(s);
      if (s.committed) { toast(t("io.done")); onDone(); onClose(); }
    } catch (e) { setErr(errorText(e, t)); }
    finally { setBusy(false); }
  };

  return (
    <Dialog title={t("io.title")} onClose={onClose} footer={<>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      {summary && summary.error_count === 0 && !summary.committed
        ? <Button variant="primary" busy={busy} onClick={() => run(true)}>{t("io.commit", { n: summary.rows })}</Button>
        : <Button variant="primary" busy={busy} disabled={!file} onClick={() => run(false)}>{t("io.check")}</Button>}
    </>}>
      <p>{t("io.lead")}</p>
      <input ref={input} type="file" accept=".xlsx" className="visually-hidden"
        onChange={(e) => { setFile(e.target.files?.[0] ?? null); setSummary(null); setErr(null); }} />
      <Button icon={<LuFileSpreadsheet />} onClick={() => input.current?.click()}>{file ? file.name : t("io.choose")}</Button>
      {err && <Notice tone="danger">{err}</Notice>}
      {summary && (
        <div className="stack" style={{ gap: 8 }}>
          <div className="row wrap small">
            <Badge>{t("io.rows", { n: summary.rows })}</Badge>
            <Badge tone="ok">{t("io.willCreate", { n: summary.create })}</Badge>
            <Badge tone="brand">{t("io.willUpdate", { n: summary.update })}</Badge>
            {summary.error_count > 0 && <Badge tone="danger">{t("io.errors", { n: summary.error_count })}</Badge>}
          </div>
          {summary.error_count === 0 ? <Notice tone="ok">{t("io.ok")}</Notice> : (
            <>
              <p className="small">{t("io.fix")}</p>
              <ul className="import-errors">
                {summary.errors.map((e) => (
                  <li key={e.row}><strong>{t("io.row", { n: e.row })}</strong>{e.code ? ` · ${e.code}` : ""}: {e.problems.join(" ")}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

/** Template, import and export menu. */
export function ExcelMenu({ entity, siteId, canEdit, onImported }: { entity: "items" | "machines"; siteId?: string; canEdit: boolean; onImported: () => void }) {
  const { t } = useI18n();
  const [importing, setImporting] = useState(false);
  return (
    <>
      <Menu trigger={(p) => <Button icon={<LuFileSpreadsheet />} {...p}>Excel<LuChevronDown /></Button>}>
        {(close) => <>
          {canEdit && <button type="button" role="menuitem" className="menu-item" onClick={() => { close(); setImporting(true); }}>
            <LuUpload />{entity === "items" ? t("io.importItems") : t("io.importMachines")}</button>}
          <a className="menu-item" role="menuitem" href={`/api/master/template?entity=${entity}`} onClick={close}><LuDownload />{t("io.template")}</a>
          <div className="menu-sep" />
          <a className="menu-item" role="menuitem" href={"/api/master/export" + qs({ site_id: siteId })} onClick={close}><LuFileSpreadsheet />{t("io.exportAll")}</a>
        </>}
      </Menu>
      {importing && <ImportDialog entity={entity} siteId={siteId} onClose={() => setImporting(false)} onDone={onImported} />}
    </>
  );
}

export function SampleDataButton({ onLoaded }: { onLoaded: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button icon={<LuSparkles />} onClick={() => setOpen(true)}>{t("sample.load")}</Button>
      {open && <Confirm title={t("sample.title")} body={t("sample.body")} confirmLabel={t("sample.load")} onClose={() => setOpen(false)}
        onConfirm={async () => { await post("/api/sample-data"); toast(t("sample.done")); onLoaded(); }} />}
    </>
  );
}

export function ReadOnlyNote({ show }: { show: boolean }) {
  const { t } = useI18n();
  return show ? <Notice>{t("common.readOnly")}</Notice> : null;
}

/** Choose a produced item to open its bill of materials or routing, or go create the item first. */
export function PickProducedItem({ title, lead, options, onPick, onClose, canCreateItem }: {
  title: string; lead: string; canCreateItem: boolean; onClose: () => void; onPick: (id: string) => void;
  options: { id: string; label: string; group: string; note: string }[];
}) {
  const { t } = useI18n();
  const [id, setId] = useState(options[0]?.id ?? "");
  const groups = Array.from(new Set(options.map((o) => o.group)));
  return (
    <Dialog title={title} onClose={onClose} footer={<>
      {canCreateItem && <Button variant="ghost" onClick={() => { onClose(); navigate("/master/items?new=produced"); }}>{t("pick.createItem")}</Button>}
      <span className="spacer" />
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button variant="primary" disabled={!id} onClick={() => onPick(id)}>{t("pick.continue")}</Button>
    </>}>
      <p>{lead}</p>
      {options.length === 0 ? <Notice>{t("pick.noItems")}</Notice> : (
        <Field label={t("pick.item")}>{(fid) => (
          <select id={fid} className="select" value={id} onChange={(e) => setId(e.target.value)} data-autofocus>
            {groups.map((g) => <optgroup key={g} label={g}>
              {options.filter((o) => o.group === g).map((o) => <option key={o.id} value={o.id}>{o.label} — {o.note}</option>)}
            </optgroup>)}
          </select>
        )}</Field>
      )}
    </Dialog>
  );
}
