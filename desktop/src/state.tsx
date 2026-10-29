import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, AuthState, Lang, ModelsStatus, Settings, get, patch, post } from "./api";
import en from "./i18n/en";
import fr from "./i18n/fr";

const DICTS: Record<Lang, Record<string, string>> = { en, fr };

export type TFn = (key: string, params?: Record<string, string | number>) => string;

function makeT(lang: Lang): TFn {
  return (key, params) => {
    let s = DICTS[lang][key] ?? DICTS.en[key] ?? key;
    if (params) for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(String(v));
    return s;
  };
}

export interface Toast { id: number; text: string; kind: "info" | "error" | "warn" }

interface AppCtx {
  loading: boolean;
  backendDown: boolean;
  auth: AuthState | null;
  settings: Settings | null;
  models: ModelsStatus | null;
  lang: Lang;
  theme: string;
  t: TFn;
  toasts: Toast[];
  toast: (text: string, kind?: Toast["kind"]) => void;
  refreshAuth: () => Promise<AuthState | null>;
  refreshModels: () => Promise<ModelsStatus | null>;
  updateSettings: (changes: Partial<Settings>) => Promise<void>;
  errorText: (e: unknown) => string;
  signOut: () => Promise<void>;
}

const Ctx = createContext<AppCtx>(null as any);
export const useApp = () => useContext(Ctx);

const LS = {
  get(k: string): string | null { try { return localStorage.getItem(k); } catch { return null; } },
  set(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [backendDown, setBackendDown] = useState(false);
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [models, setModels] = useState<ModelsStatus | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [prefLang, setPrefLang] = useState<Lang>((LS.get("op.lang") as Lang) || (navigator.language.startsWith("fr") ? "fr" : "en"));
  const [prefTheme, setPrefTheme] = useState<string>(LS.get("op.theme") || "dark");
  const nextId = useRef(1);

  const lang: Lang = settings?.language ?? prefLang;
  const t = useMemo(() => makeT(lang), [lang]);

  // appearance
  useEffect(() => {
    const el = document.documentElement;
    el.dataset.theme = settings?.theme ?? prefTheme;
    el.dataset.contrast = settings?.high_contrast ? "high" : "normal";
    el.dataset.font = settings?.font_size ?? "medium";
    el.lang = lang;
  }, [settings?.theme, settings?.high_contrast, settings?.font_size, prefTheme, lang]);

  const toast = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = nextId.current++;
    setToasts((l) => [...l, { id, text, kind }]);
    setTimeout(() => setToasts((l) => l.filter((x) => x.id !== id)), kind === "error" ? 8000 : 4500);
  }, []);

  const errorText = useCallback((e: unknown): string => {
    if (e instanceof ApiError) {
      const key = `err.${e.code}`;
      const base = DICTS[lang][key] ?? DICTS.en[key];
      if (e.code === "account_locked") return makeT(lang)("err.account_locked", { s: e.extra.retry_after ?? "" });
      if (e.code === "MODEL_MISSING") return makeT(lang)(`err.model_${e.extra.state || "missing"}`, { kind: makeT(lang)(`models.${e.extra.kind}`), reason: e.extra.reason || "", path: e.extra.path || "" });
      return base ?? e.message;
    }
    return e instanceof Error ? e.message : String(e);
  }, [lang]);

  const refreshAuth = useCallback(async () => {
    try {
      const a = await get<AuthState>("/api/auth/state");
      setAuth(a);
      setBackendDown(false);
      if (a.authenticated) {
        setSettings(await get<Settings>("/api/settings"));
        setModels(await get<ModelsStatus>("/api/models"));
      } else {
        setSettings(null);
        setModels(null);
      }
      return a;
    } catch (e) {
      if (e instanceof ApiError && e.code === "backend_unreachable") setBackendDown(true);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      const m = await get<ModelsStatus>("/api/models");
      setModels(m);
      return m;
    } catch { return null; }
  }, []);

  const updateSettings = useCallback(async (changes: Partial<Settings>) => {
    if (changes.language) { LS.set("op.lang", changes.language); setPrefLang(changes.language); }
    if (changes.theme) { LS.set("op.theme", changes.theme); setPrefTheme(changes.theme); }
    if (!settings) return;
    setSettings({ ...settings, ...changes } as Settings); // optimistic
    try {
      const s = await patch<Settings>("/api/settings", changes);
      setSettings(s);
      if ("device" in changes || "classification_checkpoint" in changes || "segmentation_checkpoint" in changes) await refreshModels();
    } catch (e) {
      toast(errorText(e), "error");
      setSettings(await get<Settings>("/api/settings"));
    }
  }, [settings, refreshModels, toast, errorText]);

  const signOut = useCallback(async () => {
    try { await post("/api/auth/logout"); } catch { /* already signed out */ }
    await refreshAuth();
  }, [refreshAuth]);

  useEffect(() => { refreshAuth(); }, [refreshAuth]);
  useEffect(() => {
    const h = () => { refreshAuth(); };
    window.addEventListener("oncopixel:signed-out", h);
    return () => window.removeEventListener("oncopixel:signed-out", h);
  }, [refreshAuth]);

  const value: AppCtx = { loading, backendDown, auth, settings, models, lang, theme: settings?.theme ?? prefTheme, t, toasts, toast, refreshAuth, refreshModels, updateSettings, errorText, signOut };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
