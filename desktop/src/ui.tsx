import React, { useCallback, useEffect, useRef, useState } from "react";
import { ClassName, StudyStatus } from "./api";
import { useApp } from "./state";

const PATHS: Record<string, string> = {
  dashboard: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
  patients: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6M16 4.5a3.5 3.5 0 0 1 0 7M18 14.2c2 .7 3.5 2.6 3.5 5.8",
  upload: "M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M12 8v8M8 12h8",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2",
  compare: "M8 3v18M16 3v18M3 8h5M16 16h5M3 16h5M16 8h5",
  models: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  help: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  plus: "M12 5v14M5 12h14", check: "M20 6L9 17l-5-5", x: "M18 6L6 18M6 6l12 12",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  alert: "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  flag: "M4 22V4M4 4h13l-2 4 2 4H4",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  play: "M6 4l14 8-14 8z", trash: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6",
  edit: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  zoomin: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3M11 8v6M8 11h6",
  zoomout: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3M8 11h6",
  fit: "M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4",
  hand: "M18 11V6a2 2 0 0 0-4 0M14 10V4a2 2 0 0 0-4 0v6M10 10.5V6a2 2 0 0 0-4 0v8M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.9-5.9-2.4L3.4 16a2 2 0 0 1 3-2.7L8 15",
  brush: "M9.1 11.9L20 1l3 3-10.9 10.9M9 12a4 4 0 0 0-4 4c0 1.7-1 3-3 3 1.5 1.5 3.5 2 5 2a5 5 0 0 0 5-5 3 3 0 0 0-3-4z",
  eraser: "M20 20H9L3.5 14.5a2 2 0 0 1 0-2.8l8-8a2 2 0 0 1 2.8 0l6 6a2 2 0 0 1 0 2.8L12 20M7 11l6 6",
  ruler: "M3 17L17 3l4 4L7 21zM7 13l2 2M10 10l2 2M13 7l2 2",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  undo: "M3 7v6h6M3 13a9 9 0 1 0 3-7", redo: "M21 7v6h-6M21 13a9 9 0 1 1-3-7",
  contrast: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 2v20",
  eye: "M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  eyeoff: "M17.9 17.9A10.1 10.1 0 0 1 12 20C5 20 1 12 1 12a18 18 0 0 1 5.1-5.9M9.9 4.2A9.1 9.1 0 0 1 12 4c7 0 11 8 11 8a18 18 0 0 1-2.2 3.2M1 1l22 22",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4", shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  chevron: "M9 6l6 6-6 6", back: "M15 18l-6-6 6-6", layers: "M12 2l10 5-10 5L2 7zM2 17l10 5 10-5M2 12l10 5 10-5",
  cpu: "M9 9h6v6H9zM4 4h16v16H4zM9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3",
  keyboard: "M2 6h20v12H2zM6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5V22h16",
  tour: "M12 2l3 7h7l-5.5 4.5L18.5 21 12 16.8 5.5 21l2-7.5L2 9h7z",
};

export function Icon({ name, size = 20, className }: { name: string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
      <path d={PATHS[name] || PATHS.info} />
    </svg>
  );
}

/** Password field with an eye button that shows or hides what is typed. */
export function PasswordInput({ value, onChange, autoComplete, required, autoFocus }: { value: string; onChange: (v: string) => void; autoComplete?: string; required?: boolean; autoFocus?: boolean }) {
  const { t } = useApp();
  const [show, setShow] = useState(false);
  return (
    <span className="pw">
      <input type={show ? "text" : "password"} value={value} autoComplete={autoComplete} required={required} autoFocus={autoFocus} onChange={(e) => onChange(e.target.value)} />
      <button type="button" className="pw-eye" onMouseDown={(e) => e.preventDefault()} onClick={() => setShow(!show)} aria-label={show ? t("auth.hide_password") : t("auth.show_password")} aria-pressed={show} data-tip={show ? t("auth.hide_password") : t("auth.show_password")}><Icon name={show ? "eyeoff" : "eye"} size={20} /></button>
    </span>
  );
}

export function Spinner() { return <span className="spinner" role="status" aria-label="loading" />; }

export function StatusChip({ status, flagged }: { status: StudyStatus; flagged?: boolean }) {
  const { t } = useApp();
  return (
    <span className="row" style={{ gap: 6 }}>
      <span className={`chip ${status === "reviewed" ? "ok" : status === "analyzed" ? "info" : ""}`}><span className="dot" />{t(`status.${status}`)}</span>
      {flagged && <span className="chip warn"><Icon name="flag" size={12} />{t("status.flagged")}</span>}
    </span>
  );
}

export function ClassChip({ label }: { label: ClassName }) {
  const { t } = useApp();
  return <span className="chip" style={{ color: `var(--class-${label})`, background: "var(--surface3)" }}><span className="dot" />{t(`class.${label}`)}</span>;
}

export function Banner({ kind = "info", title, children, action }: { kind?: "info" | "warn" | "danger"; title?: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className={`banner ${kind}`} role={kind === "info" ? "status" : "alert"}>
      <Icon name={kind === "info" ? "info" : "alert"} className="ico" />
      <div className="grow">{title && <b>{title}</b>}{children}</div>
      {action}
    </div>
  );
}

export function Modal({ title, children, footer, onClose, wide }: { title: string; children: React.ReactNode; footer?: React.ReactNode; onClose: () => void; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h2>{title}</h2></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ title, text, confirmLabel, danger, onConfirm, onClose }: { title: string; text: string; confirmLabel: string; danger?: boolean; onConfirm: () => void; onClose: () => void }) {
  const { t } = useApp();
  return (
    <Modal title={title} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>{t("common.cancel")}</button>
      <button className={`btn ${danger ? "danger" : "primary"}`} onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</button>
    </>}><p>{text}</p></Modal>
  );
}

export function Field({ label, required, children, hint }: { label: string; required?: boolean; children: React.ReactNode; hint?: string }) {
  return <label className="field"><span className={required ? "req" : ""}>{label}</span>{children}{hint && <small style={{ color: "var(--dim)" }}>{hint}</small>}</label>;
}

export function Toasts() {
  const { toasts } = useApp();
  return <div className="toasts" aria-live="polite">{toasts.map((x) => <div key={x.id} className={`toast ${x.kind}`}>{x.text}</div>)}</div>;
}

export function Empty({ icon, title, text, action }: { icon: string; title: string; text?: string; action?: React.ReactNode }) {
  return <div className="empty"><Icon name={icon} size={34} /><h3 style={{ color: "var(--text)" }}>{title}</h3>{text && <p style={{ maxWidth: 420 }}>{text}</p>}{action}</div>;
}

// ---- helpers -----------------------------------------------------------------------------------
export function useAsync<T>(fn: () => Promise<T>, deps: any[]): { data: T | null; error: unknown; loading: boolean; reload: () => void } {
  const [state, setState] = useState<{ data: T | null; error: unknown; loading: boolean }>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    const id = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn().then((data) => { if (id === seq.current) setState({ data, error: null, loading: false }); })
        .catch((error) => { if (id === seq.current) setState({ data: null, error, loading: false }); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { ...state, reload };
}

export function fmtDate(iso: string | null | undefined, lang: string): string {
  if (!iso) return "-";
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(lang === "fr" ? "fr-FR" : "en-GB", { year: "numeric", month: "short", day: "2-digit" });
}
export function fmtDateTime(iso: string | null | undefined, lang: string): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(lang === "fr" ? "fr-FR" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
}
export const pct = (v: number | null | undefined, d = 1) => (v == null ? "-" : `${(v * 100).toFixed(d)} %`);
export const num = (v: number | null | undefined, d = 1) => (v == null ? "-" : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => { const h = setTimeout(() => setV(value), ms); return () => clearTimeout(h); }, [value, ms]);
  return v;
}

/** Desktop shell bridge (Electron preload). Absent when the interface runs in a plain browser. */
export interface Shell {
  getPathForFile?: (f: File) => string;
  selectFolder?: () => Promise<string | null>;
  selectFile?: (opts?: { filters?: { name: string; extensions: string[] }[] }) => Promise<string | null>;
  showItemInFolder?: (p: string) => void;
  appVersion?: string;
  platform?: string;
}
export const shell: Shell = (window as any).oncopixel ?? {};
