// Tiny history-based router: usePath(), navigate(), <Link>.
import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";

const listeners = new Set<() => void>();

export function navigate(to: string, replace = false) {
  if (to === window.location.pathname + window.location.search) return;
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  listeners.forEach((fn) => fn());
  window.scrollTo({ top: 0 });
}

window.addEventListener("popstate", () => listeners.forEach((fn) => fn()));

export function usePath() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const fn = () => setPath(window.location.pathname);
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  }, []);
  return path;
}

export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(to);
  };
  return <a href={to} onClick={handle} {...rest} />;
}
