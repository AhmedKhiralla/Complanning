/* AI assistant: a chat panel that answers from the user's own data (read-only). */
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { LuArrowUp, LuBot, LuDatabase, LuRotateCcw, LuSparkles, LuX } from "react-icons/lu";
import { post } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { usePath } from "../lib/router";
import { useSession } from "../lib/session";
import type { StringKey } from "../lib/strings";
import { errorText } from "./ui";

interface Used { kind: string; id?: string; label?: string }
interface Turn { role: "user" | "assistant"; content: string; used?: Used[]; error?: boolean }

/** Bold, inline code, bullet and numbered lists, paragraphs. Model text is rendered as text, never as HTML. */
function inline(s: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const tok = m[0];
    out.push(tok.startsWith("**") ? <strong key={i++}>{tok.slice(2, -2)}</strong> : <code key={i++}>{tok.slice(1, -1)}</code>);
    last = m.index + tok.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

function Rich({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r/g, "").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((x, j) => <li key={j}>{inline(x)}</li>);
    blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const b = /^\s*[-*•]\s+(.*)$/.exec(line), n = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (b || n) {
      const ordered = !!n;
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push((b ?? n)![1]);
      continue;
    }
    flush();
    if (!line.trim()) continue;
    const h = /^#{1,4}\s+(.*)$/.exec(line);
    blocks.push(h ? <p key={blocks.length}><strong>{inline(h[1])}</strong></p> : <p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  return <>{blocks}</>;
}

function suggestions(path: string): StringKey[] {
  if (/^\/plans\/[0-9a-f-]{36}$/.test(path)) return ["ai.sg.late", "ai.sg.warnings", "ai.sg.busiest"];
  if (path.startsWith("/planning/requirements")) return ["ai.sg.short", "ai.sg.order"];
  if (path.startsWith("/planning/stock")) return ["ai.sg.expiring", "ai.sg.short"];
  if (path.startsWith("/master") || path.startsWith("/rules")) return ["ai.sg.setup", "ai.sg.howBom", "ai.sg.nopause"];
  if (path.startsWith("/settings")) return ["ai.sg.features", "ai.sg.setup"];
  return ["ai.sg.setup", "ai.sg.plans", "ai.sg.start"];
}

export function Assistant() {
  const { t, lang } = useI18n();
  const { me, siteId } = useSession();
  const path = usePath();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const planId = /^\/plans\/([0-9a-f-]{36})$/.exec(path)?.[1] ?? null;

  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }); }, [turns, busy]);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && open) setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!me?.tenant?.assistant) return null;

  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    const history = turns.filter((x) => !x.error).map(({ role, content }) => ({ role, content }));
    const next: Turn[] = [...turns, { role: "user", content: question }];
    setTurns(next); setText(""); setBusy(true);
    try {
      const r = await post<{ answer: string; used: Used[]; remaining: number }>("/api/assistant/chat", {
        messages: [...history, { role: "user", content: question }].slice(-12), site_id: siteId, plan_id: planId, page: path,
      });
      setTurns([...next, { role: "assistant", content: r.answer, used: r.used }]);
      setRemaining(r.remaining);
    } catch (e) {
      setTurns([...next, { role: "assistant", content: errorText(e, t), error: true }]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  const usedLabel = (u: Used) => `${t(`ai.used.${u.kind}` as StringKey)}${u.label ? `: ${u.label}` : ""}`;
  return (
    <>
      {!open && <button type="button" className="ai-fab" onClick={() => setOpen(true)} aria-label={t("ai.open")}>
        <LuSparkles aria-hidden /><span>{t("ai.title")}</span></button>}
      {open && (
        <aside className="ai-panel" role="dialog" aria-label={t("ai.title")} dir={lang === "ar" ? "rtl" : "ltr"}>
          <header className="ai-head">
            <span className="ai-mark" aria-hidden><LuBot /></span>
            <div className="grow"><strong>{t("ai.title")}</strong><span className="small muted">{t("ai.sub")}</span></div>
            {turns.length > 0 && <button type="button" className="icon-btn" title={t("ai.new")} aria-label={t("ai.new")}
              onClick={() => setTurns([])} disabled={busy}><LuRotateCcw /></button>}
            <button type="button" className="icon-btn" aria-label={t("ai.close")} onClick={() => setOpen(false)}><LuX /></button>
          </header>
          <div className="ai-list" ref={listRef} aria-live="polite">
            {turns.length === 0 && (
              <div className="ai-empty">
                <p>{t("ai.hello", { name: me.user.full_name.split(/\s+/)[0] })}</p>
                <div className="ai-sugs">
                  {suggestions(path).map((k) => <button key={k} type="button" className="ai-sug" onClick={() => send(t(k))}>{t(k)}</button>)}
                </div>
              </div>
            )}
            {turns.map((m, i) => (
              <Fragment key={i}>
                <div className={`ai-msg ${m.role} ${m.error ? "error" : ""}`}>
                  {m.role === "assistant" ? <Rich text={m.content} /> : <p>{m.content}</p>}
                </div>
                {m.used && m.used.length > 0 && <div className="ai-used"><LuDatabase aria-hidden />
                  <span>{t("ai.basedOn")} {m.used.map(usedLabel).join(" · ")}</span></div>}
              </Fragment>
            ))}
            {busy && <div className="ai-msg assistant ai-busy"><span className="spinner" aria-hidden />{t("ai.thinking")}</div>}
          </div>
          <form className="ai-input" onSubmit={(e) => { e.preventDefault(); send(text); }}>
            <textarea ref={inputRef} rows={1} value={text} maxLength={2000} placeholder={t("ai.placeholder")} aria-label={t("ai.placeholder")}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); } }} />
            <button type="submit" className="btn primary icon" disabled={busy || !text.trim()} aria-label={t("ai.send")}><LuArrowUp /></button>
          </form>
          <p className="ai-foot small subtle">{t("ai.foot")}{remaining !== null ? ` ${t("ai.remaining", { n: remaining })}` : ""}</p>
        </aside>
      )}
    </>
  );
}
