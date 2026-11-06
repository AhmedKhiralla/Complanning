/* A number box that shows thousands separators (1,500,000) while the value stays a plain number string ("1500000"). */
import { useLayoutEffect, useRef, type InputHTMLAttributes } from "react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & {
  value: string | number | null | undefined;
  onChange?: (e: { target: { value: string } }) => void;
};

/** Keep digits, one decimal point and a leading minus. */
export function cleanNumber(v: string): string {
  let s = v.replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d))).replace(/٫/g, ".").replace(/[^\d.-]/g, "");
  const neg = s.startsWith("-");
  s = s.replace(/-/g, "");
  const dot = s.indexOf(".");
  if (dot >= 0) s = s.slice(0, dot + 1) + s.slice(dot + 1).replace(/\./g, "");
  return (neg ? "-" : "") + s;
}

/** "1500000.25" -> "1,500,000.25"; keeps what is being typed ("12." stays "12."). */
export function groupNumber(raw: string): string {
  if (!raw) return "";
  const neg = raw.startsWith("-");
  const s = neg ? raw.slice(1) : raw;
  const [int, dec] = s.split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (neg ? "-" : "") + grouped + (dec !== undefined ? "." + dec : "");
}

export function NumInput({ value, onChange, className = "input num", inputMode = "decimal", ...rest }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);          // characters (not commas) before the caret after a change
  const raw = value === null || value === undefined ? "" : cleanNumber(String(value));
  const shown = groupNumber(raw);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || caret.current === null || document.activeElement !== el) return;
    let n = caret.current, pos = 0;
    while (pos < shown.length && n > 0) { if (shown[pos] !== ",") n--; pos++; }
    el.setSelectionRange(pos, pos);
    caret.current = null;
  }, [shown]);

  return (
    <input ref={ref} type="text" inputMode={inputMode} dir="ltr" autoComplete="off" spellCheck={false} className={className}
      value={shown} {...rest}
      onChange={(e) => {
        const typed = e.target.value;
        const at = e.target.selectionStart ?? typed.length;
        caret.current = cleanNumber(typed.slice(0, at)).length;
        onChange?.({ target: { value: cleanNumber(typed) } });
      }} />
  );
}
