import React, { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { Banner, Icon, useAsync } from "../ui";
import { useApp } from "../state";
import { Dashboard, get } from "../api";
import Tour from "./Tour";

const NAV: { to: string; icon: string; key: string; end?: boolean }[] = [
  { to: "/", icon: "dashboard", key: "nav.dashboard", end: true },
  { to: "/import", icon: "upload", key: "nav.import" },
  { to: "/patients", icon: "patients", key: "nav.patients" },
  { to: "/studies", icon: "history", key: "nav.studies" },
  { to: "/compare", icon: "compare", key: "nav.compare" },
];
const NAV2: typeof NAV = [
  { to: "/models", icon: "models", key: "nav.models" },
  { to: "/activity", icon: "activity", key: "nav.activity" },
  { to: "/settings", icon: "settings", key: "nav.settings" },
  { to: "/help", icon: "help", key: "nav.help" },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  const { t, lang, settings, auth, models, updateSettings, signOut } = useApp();
  const nav = useNavigate();
  const loc = useLocation();
  const [tour, setTour] = useState(false);
  const { data: dash } = useAsync<Dashboard>(() => get("/api/dashboard"), [loc.pathname]);
  const missing = models && !models.all_ready;

  useEffect(() => { if (settings && settings.welcome_seen && !settings.tour_done && sessionStorage.getItem("op.tour") === "1") setTour(true); }, [settings]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.metaKey || e.ctrlKey || e.altKey) return;
      const map: Record<string, string> = { "1": "/", "2": "/import", "3": "/patients", "4": "/studies", "5": "/compare", "6": "/models", "7": "/settings" };
      if (map[e.key]) { nav(map[e.key]); e.preventDefault(); }
      if (e.key === "?") { nav("/help#shortcuts"); e.preventDefault(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [nav]);

  const logo = settings?.theme === "light" ? "/logo-light.png" : "/logo-dark.png";
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><img src={logo} alt="OncoPixel" /></div>
        <nav className="nav" aria-label={t("nav.workspace")}>
          <span className="nav-label">{t("nav.workspace")}</span>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} data-tour={`nav-${n.icon}`} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon name={n.icon} />{t(n.key)}
              {n.to === "/studies" && dash && dash.pending_reviews > 0 && <span className="count" data-tip={t("dash.pending_reviews")}>{dash.pending_reviews}</span>}
            </NavLink>
          ))}
        </nav>
        <nav className="nav" aria-label={t("nav.system")}>
          <span className="nav-label">{t("nav.system")}</span>
          {NAV2.map((n) => (
            <NavLink key={n.to} to={n.to} data-tour={`nav-${n.icon}`} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon name={n.icon} />{t(n.key)}
              {n.to === "/models" && missing && <span className="count" style={{ background: "var(--warn-bg)", color: "var(--warn)" }}>!</span>}
            </NavLink>
          ))}
          <a href="#tour" onClick={(e) => { e.preventDefault(); setTour(true); }}><Icon name="tour" />{t("nav.tour")}</a>
        </nav>
      </aside>
      <header className="topbar">
        <div className="disclaimer" role="note" data-tour="disclaimer">{auth?.disclaimer[lang]}</div>
        <div className="spacer" />
        {missing && <button className="chip warn" style={{ border: 0, cursor: "pointer" }} onClick={() => nav("/models")}><Icon name="alert" size={14} />{t("topbar.models_missing")}</button>}
        {!missing && models?.any_test_fixture && <button className="chip danger" style={{ border: 0, cursor: "pointer" }} onClick={() => nav("/models")}><Icon name="alert" size={14} />{t("topbar.test_model")}</button>}
        <div className="row" style={{ gap: 10 }} data-tour="topbar-user">
        <div className="seg" role="group" aria-label={t("settings.language")}>
          {(["en", "fr"] as const).map((l) => <button key={l} className={lang === l ? "on" : ""} onClick={() => updateSettings({ language: l })} aria-pressed={lang === l}>{l.toUpperCase()}</button>)}
        </div>
        <button className="btn icon ghost" data-tip={t("topbar.theme")} aria-label={t("topbar.theme")} onClick={() => updateSettings({ theme: settings?.theme === "dark" ? "light" : "dark" })}>
          <Icon name={settings?.theme === "dark" ? "sun" : "moon"} />
        </button>
        <button className="btn ghost" onClick={() => { setTour(true); }} data-tip={t("tour.start")}><Icon name="tour" size={18} /></button>
        <div className="row" style={{ gap: 8 }}>
          <span style={{ fontSize: ".88rem", color: "var(--muted)" }}>{auth?.user?.display_name}</span>
          <button className="btn icon ghost" onClick={signOut} data-tip={t("auth.sign_out")} aria-label={t("auth.sign_out")}><Icon name="logout" /></button>
        </div>
        </div>
      </header>
      <main className="main" id="main">{children}</main>
      {tour && <Tour onClose={() => { setTour(false); sessionStorage.removeItem("op.tour"); if (settings && !settings.tour_done) updateSettings({ tour_done: true }); }} />}
    </div>
  );
}
