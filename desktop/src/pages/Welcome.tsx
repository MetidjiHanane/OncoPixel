import React from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../state";
import { Icon } from "../ui";

export default function Welcome() {
  const { t, settings, auth, lang, updateSettings } = useApp();
  const nav = useNavigate();
  const theme = settings?.theme;
  const go = async (tour: boolean) => {
    if (tour) sessionStorage.setItem("op.tour", "1"); else sessionStorage.removeItem("op.tour");
    await updateSettings({ welcome_seen: true, ...(tour ? {} : { tour_done: true }) });
    nav("/");
  };
  return (
    <div className="auth">
      <div className="auth-top">
        <button type="button" onClick={() => updateSettings({ language: lang === "en" ? "fr" : "en" })} aria-label={t("settings.language")}>{lang === "en" ? "Français" : "English"}</button>
        <button type="button" className="sq" onClick={() => updateSettings({ theme: theme === "light" ? "dark" : "light" })} aria-label={t("topbar.theme")}><Icon name={theme === "light" ? "moon" : "sun"} size={20} /></button>
      </div>
      <div className="auth-main">
        <div className="welcome-wrap">
          <img className="logo" src={theme === "light" ? "/logo-light.png" : "/logo-dark.png"} alt="OncoPixel" />
          <h1>{t("welcome.title", { name: auth?.user?.display_name ?? "" })}</h1>
          <p>{t("welcome.text")}</p>
          <div className="welcome-cards">
            <button className="welcome-card" onClick={() => go(true)}>
              <span className="tile"><Icon name="play" size={26} /></span>
              <h3>{t("welcome.tour")}</h3><p>{t("welcome.tour_text")}</p>
            </button>
            <button className="welcome-card" onClick={() => go(false)}>
              <span className="tile"><Icon name="dashboard" size={26} /></span>
              <h3>{t("welcome.explore")}</h3><p>{t("welcome.explore_text")}</p>
            </button>
          </div>
        </div>
      </div>
      <div className="auth-foot" role="note"><Icon name="alert" size={18} /><span>{auth?.disclaimer[lang]}</span></div>
    </div>
  );
}
