import { useState, type CSSProperties } from "react";
import { LuLanguages, LuMonitor, LuMoon, LuSun } from "react-icons/lu";
import { Button, Notice, PasswordField, TextField, errorText } from "../components/ui";
import { ApiError, get, post } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useSession, type Me } from "../lib/session";
import { useTheme } from "../lib/theme";
import { Logo } from "../components/Logo";

/** A small, illustrative schedule: five machines, batches, cleaning and a QC wait. */
const LANES: { name: string; code: string; bars: { l: number; w: number; cls?: string; label?: string }[] }[] = [
  { name: "Granulator", code: "GR-01", bars: [{ l: 2, w: 20, label: "PAR-500 · B114" }, { l: 23, w: 5, cls: "clean" }, { l: 29, w: 22, cls: "b2", label: "MET-850 · B061" }, { l: 52, w: 5, cls: "clean" }, { l: 58, w: 24, label: "PAR-500 · B115" }] },
  { name: "Tablet press", code: "TP-02", bars: [{ l: 12, w: 26, cls: "b3", label: "PAR-500 · B113" }, { l: 39, w: 4, cls: "clean" }, { l: 44, w: 26, label: "PAR-500 · B114" }, { l: 72, w: 20, cls: "b2", label: "MET-850" }] },
  { name: "Coater", code: "CT-01", bars: [{ l: 0, w: 14, cls: "qc", label: "QC" }, { l: 18, w: 24, cls: "b2", label: "AML-10 · B020" }, { l: 43, w: 6, cls: "clean" }, { l: 50, w: 24, cls: "b3", label: "PAR-500 · B113" }] },
  { name: "Blister line", code: "BL-03", bars: [{ l: 6, w: 22, label: "AML-10 · EG" }, { l: 29, w: 3, cls: "clean" }, { l: 33, w: 24, cls: "b2", label: "AML-10 · KSA" }, { l: 60, w: 12, cls: "qc", label: "QC" }, { l: 74, w: 22, cls: "b3", label: "PAR-500" }] },
  { name: "Cartoner", code: "CR-01", bars: [{ l: 10, w: 20, cls: "b3", label: "AML-10 · EG" }, { l: 34, w: 24, label: "AML-10 · KSA" }, { l: 62, w: 6, cls: "clean" }, { l: 70, w: 24, cls: "b2", label: "PAR-500" }] },
];

function Ribbon() {
  const { t } = useI18n();
  return (
    <div className="ribbon" aria-hidden>
      <div className="grid" />
      {LANES.map((lane, i) => (
        <div className="lane" key={lane.code}>
          <div className="lane-name"><b>{lane.name}</b>{lane.code}</div>
          <div className="track">
            {lane.bars.map((b, j) => (
              <div key={j} className={`bar ${b.cls ?? ""}`}
                style={{ left: `${b.l}%`, width: `${b.w}%`, "--d": `${0.15 + i * 0.08 + j * 0.06}s` } as CSSProperties}>
                {b.label}
              </div>
            ))}
          </div>
        </div>
      ))}
      <div className="now" title={t("login.legendNow")} />
    </div>
  );
}

export function Prefs() {
  const { lang } = useI18n();
  const { choice } = useTheme();
  const { savePreference } = useSession();
  const { t } = useI18n();
  return (
    <div className="row wrap">
      <div className="seg" role="group" aria-label={t("common.language")}>
        <button type="button" aria-pressed={lang === "en"} onClick={() => savePreference({ language: "en" })} lang="en">
          <LuLanguages aria-hidden />English
        </button>
        <button type="button" aria-pressed={lang === "ar"} onClick={() => savePreference({ language: "ar" })} lang="ar">العربية</button>
      </div>
      <div className="seg" role="group" aria-label={t("theme.label")}>
        <button type="button" aria-pressed={choice === "light"} onClick={() => savePreference({ theme: "light" })} title={t("theme.light")} aria-label={t("theme.light")}><LuSun /></button>
        <button type="button" aria-pressed={choice === "dark"} onClick={() => savePreference({ theme: "dark" })} title={t("theme.dark")} aria-label={t("theme.dark")}><LuMoon /></button>
        <button type="button" aria-pressed={choice === "system"} onClick={() => savePreference({ theme: "system" })} title={t("theme.system")} aria-label={t("theme.system")}><LuMonitor /></button>
      </div>
    </div>
  );
}

export function Login() {
  const { t } = useI18n();
  const { setMe, signedOutReason } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      await post("/api/auth/login", { email: email.trim(), password });
      setMe(await get<Me>("/api/auth/me"));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 422 ? t("common.fixFields") : errorText(e, t));
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <div className="auth-form">
        <div className="top">
          <Logo height={44} />
        </div>
        <div className="middle">
          <h1>{t("login.title")}</h1>
          <p className="lead">{t("login.lead")}</p>
          <form onSubmit={(e) => { e.preventDefault(); submit(); }} noValidate>
            {signedOutReason === "expired" && !error && <Notice tone="warn">{t("login.expired")}</Notice>}
            {signedOutReason === "signed-out" && !error && <Notice tone="ok">{t("login.signedOut")}</Notice>}
            {error && <Notice tone="danger">{error}</Notice>}
            <TextField label={t("login.email")} type="email" value={email} onChange={setEmail}
              autoComplete="username" dir="ltr" required autoFocus />
            <PasswordField label={t("login.password")} value={password} onChange={setPassword} required />
            <Button type="submit" variant="primary" block busy={busy} disabled={!email || !password}>
              {busy ? t("login.submitting") : t("login.submit")}
            </Button>
            <p className="small subtle">{t("login.forgot")}</p>
          </form>
        </div>
        <div className="foot">
          <Prefs />
          <span>Complanning · Comp11 Labs</span>
        </div>
      </div>
      <div className="auth-visual">
        <div className="claim">
          <h2>{t("login.visualTitle")}</h2>
          <p>{t("login.visualBody")}</p>
        </div>
        <Ribbon />
        <div className="legend">
          <span><i style={{ background: "#7d34ad" }} />{t("login.legendBatch")}</span>
          <span><i style={{ background: "repeating-linear-gradient(135deg, rgba(255,255,255,.35) 0 3px, transparent 3px 6px)" }} />{t("login.legendClean")}</span>
          <span><i style={{ boxShadow: "inset 0 0 0 1px rgba(242,162,58,.8)" }} />{t("login.legendQc")}</span>
          <span><i style={{ background: "#f2a23a", width: 2, height: 14 }} />{t("login.legendNow")}</span>
        </div>
      </div>
    </div>
  );
}
