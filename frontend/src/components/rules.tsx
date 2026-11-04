// Shared pieces for the planning-rules screens.
import { useState } from "react";
import { LuDroplets, LuEye, LuTestTubeDiagonal, LuTrash2 } from "react-icons/lu";
import { del, patch, post } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSession } from "../lib/session";
import { nameOf, type ItemType, type Resource } from "../lib/types";
import { NumberField, numOrNull, str } from "./master";
import { Button, Confirm, Field, Notice, SelectField, Sheet, TextField, errorText, fieldErrors, useToast } from "./ui";

export type Verification = "none" | "visual" | "rinse" | "swab";
export type RuleKind = "same_product" | "same_group" | "group_to_group" | "product_pair" | "default";

export interface CleaningGroup { id: string; code: string; name_en: string; name_ar: string | null; notes: string | null; sort_order: number; active: boolean; item_count: number; }
export interface Rule {
  id: string; resource_id: string | null; resource_code: string | null; kind: RuleKind; from_group: string | null; to_group: string | null;
  from_item_id: string | null; from_item_code: string | null; to_item_id: string | null; to_item_code: string | null;
  cleaning_minutes: number; format_minutes: number; verification: Verification; verification_wait_minutes: number;
  notes: string | null; total_minutes: number;
}
export interface Cell { rule_id: string; kind: RuleKind; total_minutes: number; verification: Verification; specific: boolean; scope: "site" | "machine"; }
export interface Matrix { groups: { code: string; name_en: string; name_ar: string | null }[]; matrix: (Cell | null)[][]; same_product: Cell | null; default: Cell | null; }
export interface ItemTimes {
  id: string; code: string; name_en: string; name_ar: string | null; type: ItemType; cleaning_group: string | null;
  hold_min_hours: number | null; hold_max_hours: number | null; release_lead_days: number | null;
  release_at_risk_allowed: boolean; test_before_sale: boolean;
}
export interface MachineHold extends Pick<Resource, "id" | "code" | "name_en" | "name_ar" | "area" | "type"> { dirty_hold_hours: number | null; clean_hold_hours: number | null; }

/** Whether a company feature toggle is on (on when unknown). */
export function useFeature() {
  const { me } = useSession();
  return (name: string) => me?.tenant?.features?.[name] ?? true;
}

/** 95 -> "1 h 35 min". */
export function useDuration() {
  const { t, number } = useI18n();
  return (minutes: number | null | undefined) => {
    const m = Math.round(Number(minutes ?? 0));
    if (!m) return t("dur.none");
    if (m < 60) return t("dur.min", { n: number(m) });
    const h = Math.floor(m / 60), r = m % 60;
    return r ? t("dur.hmin", { h: number(h), m: number(r) }) : t("dur.h", { n: number(h) });
  };
}

const VER_ICON = { visual: <LuEye />, rinse: <LuDroplets />, swab: <LuTestTubeDiagonal /> } as const;

export function VerIcon({ v }: { v: Verification }) {
  const { t } = useI18n();
  if (v === "none") return null;
  return <span className={`ver ver-${v}`} title={t(`ver.${v}` as never)} aria-label={t(`ver.${v}` as never)}>{VER_ICON[v]}</span>;
}

// ------------------------------------------------------------------ cleaning group sheet
export function GroupSheet({ group, onClose, onSaved }: { group: CleaningGroup | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [f, setF] = useState({ code: group?.code ?? "", name_en: group?.name_en ?? "", name_ar: group?.name_ar ?? "", notes: group?.notes ?? "", active: group?.active ?? true });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    const body = { name_en: f.name_en, name_ar: f.name_ar || null, notes: f.notes || null };
    try {
      if (group) await patch(`/api/cleaning-groups/${group.id}`, { ...body, active: f.active });
      else await post("/api/cleaning-groups", { ...body, code: f.code });
      toast(t("groups.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };
  return (
    <Sheet title={group ? t("groups.form.edit") : t("groups.form.new")} lead={group?.code} onClose={onClose} onSubmit={submit}
      footer={<>
        {group && <Button variant="ghost" icon={<LuTrash2 />} onClick={() => setDeleting(true)} style={{ marginInlineEnd: "auto" }}>{t("groups.delete")}</Button>}
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button type="submit" variant="primary" busy={busy}>{group ? t("common.save") : t("common.create")}</Button>
      </>}>
      {general && <Notice tone="danger">{general}</Notice>}
      <TextField label={t("groups.f.code")} hint={!group ? t("groups.f.codeHint") : undefined} value={f.code} dir="ltr" maxLength={20}
        disabled={!!group} onChange={(v) => setF({ ...f, code: v.toUpperCase() })} error={errs.code} required />
      <TextField label={t("items.f.nameEn")} value={f.name_en} dir="ltr" onChange={(v) => setF({ ...f, name_en: v })} error={errs.name_en} required />
      <TextField label={t("items.f.nameAr")} value={f.name_ar} dir="rtl" lang="ar" onChange={(v) => setF({ ...f, name_ar: v })} />
      <TextField label={t("groups.f.notes")} value={f.notes} onChange={(v) => setF({ ...f, notes: v })} />
      {deleting && group && <Confirm danger title={t("groups.deleteTitle", { code: group.code })} body={t("groups.deleteBody")} confirmLabel={t("groups.delete")}
        onClose={() => setDeleting(false)} onConfirm={async () => { await del(`/api/cleaning-groups/${group.id}`); onSaved(); onClose(); }} />}
    </Sheet>
  );
}

// ------------------------------------------------------------------ changeover rule sheet
export interface RuleDraft {
  kind: RuleKind; resource_id: string | null; from_group?: string | null; to_group?: string | null;
  from_item_id?: string | null; to_item_id?: string | null;
  /** Times to start from, for example the rule the cell inherits today. */
  seed?: Partial<Pick<Rule, "cleaning_minutes" | "format_minutes" | "verification" | "verification_wait_minutes">>;
}

export function RuleSheet({ siteId, rule, draft, machines, products, groups, onClose, onSaved }: {
  siteId: string; rule: Rule | null; draft: RuleDraft | null; machines: Resource[]; products: ItemTimes[]; groups: CleaningGroup[];
  onClose: () => void; onSaved: () => void;
}) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const feature = useFeature();
  const verifyOn = feature("cleaning_verification");
  const base = rule ?? draft!;
  const seed = rule ?? draft?.seed ?? {};
  const [f, setF] = useState({
    resource_id: base.resource_id ?? "", from_item_id: base.from_item_id ?? "", to_item_id: base.to_item_id ?? "",
    cleaning_minutes: str(seed.cleaning_minutes ?? 0), format_minutes: str(seed.format_minutes ?? 0),
    verification: (seed.verification ?? "none") as Verification, verification_wait_minutes: str(seed.verification_wait_minutes ?? 0),
    notes: rule?.notes ?? "",
  });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const kind = base.kind;
  const pairNew = !rule && kind === "product_pair";
  const groupName = (code?: string | null) => { const g = groups.find((x) => x.code === code); return g ? `${g.code} · ${nameOf(g, lang)}` : code ?? ""; };
  const machineName = (id: string | null) => { const m = machines.find((x) => x.id === id); return m ? `${m.code} · ${nameOf(m, lang)}` : t("co.allMachines"); };
  const productName = (id?: string | null) => { const p = products.find((x) => x.id === id); return p ? `${p.code} · ${nameOf(p, lang)}` : ""; };

  const appliesTo = kind === "group_to_group" ? `${groupName(base.from_group)} → ${groupName(base.to_group)}`
    : kind === "same_group" ? (base.from_group ? groupName(base.from_group) : t("co.kind.same_group.d"))
    : kind === "product_pair" && rule ? `${productName(rule.from_item_id) || rule.from_item_code} → ${productName(rule.to_item_id) || rule.to_item_code}`
    : t(`co.kind.${kind}.d` as never);

  const total = (Number(f.cleaning_minutes) || 0) + (Number(f.format_minutes) || 0) + (verifyOn ? Number(f.verification_wait_minutes) || 0 : 0);
  const dur = useDuration();

  const submit = async () => {
    setBusy(true); setErrs({}); setGeneral(null);
    const fields = {
      cleaning_minutes: numOrNull(f.cleaning_minutes) ?? 0, format_minutes: numOrNull(f.format_minutes) ?? 0,
      verification: verifyOn ? f.verification : "none", verification_wait_minutes: verifyOn ? numOrNull(f.verification_wait_minutes) ?? 0 : 0,
      notes: f.notes || null,
    };
    try {
      if (rule) await patch(`/api/changeovers/${rule.id}`, fields);
      else await post(`/api/sites/${siteId}/changeovers`, {
        ...fields, kind, resource_id: (pairNew ? f.resource_id : draft!.resource_id) || null,
        from_group: draft!.from_group ?? null, to_group: draft!.to_group ?? null,
        from_item_id: pairNew ? f.from_item_id || null : null, to_item_id: pairNew ? f.to_item_id || null : null,
      });
      toast(t("co.savedToast")); onSaved(); onClose();
    } catch (e) { setErrs(fieldErrors(e)); setGeneral(errorText(e, t)); setBusy(false); }
  };

  const productOptions = [{ value: "", label: "—" }, ...products.map((p) => ({ value: p.id, label: `${p.code} · ${nameOf(p, lang)}` }))];
  return (
    <Sheet title={rule ? t("co.form.edit") : t("co.form.new")} lead={t(`co.kind.${kind}` as never)} onClose={onClose} onSubmit={submit}
      footer={<>
        {rule && <Button variant="ghost" icon={<LuTrash2 />} onClick={() => setRemoving(true)} style={{ marginInlineEnd: "auto" }}>{t("co.removeRule")}</Button>}
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button type="submit" variant="primary" busy={busy}>{rule ? t("common.save") : t("common.create")}</Button>
      </>}>
      {general && <Notice tone="danger">{general}</Notice>}
      {pairNew ? <>
        <SelectField label={t("co.machine")} value={f.resource_id} onChange={(v) => setF({ ...f, resource_id: v })} error={errs.resource_id}
          options={[{ value: "", label: t("co.allMachines") }, ...machines.map((m) => ({ value: m.id, label: `${m.code} · ${nameOf(m, lang)}` }))]} />
        <div className="grid-2">
          <SelectField label={t("co.fromProduct")} value={f.from_item_id} onChange={(v) => setF({ ...f, from_item_id: v })} error={errs.from_item_id} options={productOptions} />
          <SelectField label={t("co.toProduct")} value={f.to_item_id} onChange={(v) => setF({ ...f, to_item_id: v })} error={errs.to_item_id} options={productOptions} />
        </div>
      </> : (
        <div className="rule-scope">
          <div><span className="small muted">{t("co.f.appliesTo")}</span><strong>{appliesTo}</strong></div>
          <div><span className="small muted">{t("co.machine")}</span><strong>{machineName(base.resource_id)}</strong></div>
        </div>
      )}
      <div className="grid-2">
        <NumberField label={t("co.f.cleaning")} value={f.cleaning_minutes} min={0} step="1" onChange={(v) => setF({ ...f, cleaning_minutes: v })} error={errs.cleaning_minutes} />
        <NumberField label={t("co.f.format")} hint={t("co.f.formatHint")} value={f.format_minutes} min={0} step="1" onChange={(v) => setF({ ...f, format_minutes: v })} error={errs.format_minutes} />
      </div>
      {verifyOn && <>
        <Field label={t("co.f.verification")}>{() => (
          <div className="seg ver-seg" role="group" aria-label={t("co.f.verification")}>
            {(["none", "visual", "rinse", "swab"] as Verification[]).map((v) => (
              <button key={v} type="button" aria-pressed={f.verification === v} onClick={() => setF({ ...f, verification: v, verification_wait_minutes: v === "none" ? "0" : f.verification_wait_minutes })}>
                {v !== "none" && VER_ICON[v]}{t(`ver.${v}` as never)}
              </button>
            ))}
          </div>
        )}</Field>
        {f.verification !== "none" && <NumberField label={t("co.f.wait")} hint={t("co.f.waitHint")} value={f.verification_wait_minutes} min={0} step="1"
          onChange={(v) => setF({ ...f, verification_wait_minutes: v })} error={errs.verification_wait_minutes} />}
      </>}
      <div className="rule-total"><span>{t("co.total")}</span><strong>{dur(total)}</strong></div>
      <TextField label={t("co.f.notes")} value={f.notes} onChange={(v) => setF({ ...f, notes: v })} />
      {removing && rule && <Confirm danger title={t("co.removeTitle")} body={t("co.removeBody")} confirmLabel={t("co.removeRule")} onClose={() => setRemoving(false)}
        onConfirm={async () => { await del(`/api/changeovers/${rule.id}`); toast(t("co.deletedToast")); onSaved(); onClose(); }} />}
    </Sheet>
  );
}
