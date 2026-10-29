import React, { useState } from "react";
import { post } from "../api";
import { useApp } from "../state";
import { Banner, Field, Icon, PasswordInput, Spinner } from "../ui";

type Mode = "login" | "reset" | "key";

export default function AuthPage() {
  const { auth, t, lang, refreshAuth, errorText, updateSettings, theme, toast } = useApp();
  const setup = !!auth?.setup_required;
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [display, setDisplay] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [recovery, setRecovery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newKey, setNewKey] = useState("");
  const [saved, setSaved] = useState(false);

  const finish = async () => { sessionStorage.setItem("op.tour", "1"); await refreshAuth(); };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if ((setup || mode === "reset") && password !== confirm) { setError(t("err.password_mismatch")); return; }
    setBusy(true);
    try {
      if (setup) { const r = await post<{ recovery_key: string }>("/api/auth/setup", { username, display_name: display, password }); setNewKey(r.recovery_key); setMode("key"); }
      else if (mode === "reset") { const r = await post<{ recovery_key: string }>("/api/auth/reset", { username, recovery_key: recovery, new_password: password }); setNewKey(r.recovery_key); setMode("key"); }
      else { await post("/api/auth/login", { username, password }); await finish(); }
    } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  };

  const copyKey = async () => { try { await navigator.clipboard.writeText(newKey); toast(t("auth.key_copied")); } catch { /* clipboard unavailable: the key is selectable */ } };
  const downloadKey = () => {
    const blob = new Blob([`OncoPixel recovery key\nUser: ${username}\n\n${newKey}\n\nKeep this file somewhere safe and private. It lets you choose a new password if you forget yours.\n`], { type: "text/plain" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "oncopixel-recovery-key.txt"; a.click(); URL.revokeObjectURL(a.href);
  };

  const logo = theme === "light" ? "/logo-light.png" : "/logo-dark.png";
  const title = mode === "key" ? t("auth.key.title") : mode === "reset" ? t("auth.reset.title") : setup ? t("auth.setup.title") : t("auth.login.title");
  return (
    <div className="auth">
      <div className="auth-top">
        <button type="button" onClick={() => updateSettings({ language: lang === "en" ? "fr" : "en" })} aria-label={t("settings.language")}>{lang === "en" ? "Français" : "English"}</button>
        <button type="button" className="sq" onClick={() => updateSettings({ theme: theme === "light" ? "dark" : "light" })} aria-label={t("topbar.theme")}><Icon name={theme === "light" ? "moon" : "sun"} size={20} /></button>
      </div>
      <div className="auth-main">
        {mode === "key" ? (
          <div className="auth-card" role="dialog" aria-labelledby="auth-title">
            <div className="auth-brand"><img src={logo} alt="OncoPixel" /><span>{t("app.tagline")}</span></div>
            <h1 id="auth-title">{title}</h1>
            <div className="auth-info"><Icon name="info" size={26} /><span>{t("auth.key.text")}</span></div>
            <div className="recovery-key" data-testid="recovery-key">{newKey}</div>
            <div className="auth-row">
              <button type="button" onClick={copyKey}><Icon name="copy" size={18} />{t("auth.key.copy")}</button>
              <button type="button" onClick={downloadKey}><Icon name="download" size={18} />{t("auth.key.download")}</button>
            </div>
            <label className="check"><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /><span>{t("auth.key.saved")}</span></label>
            <button className="auth-submit" disabled={!saved} onClick={finish}>{t("auth.key.continue")}</button>
          </div>
        ) : (
          <form className="auth-card" onSubmit={submit} aria-labelledby="auth-title">
            <div className="auth-brand"><img src={logo} alt="OncoPixel" /><span>{t("app.tagline")}</span></div>
            <h1 id="auth-title">{title}</h1>
            {!setup && <div className="auth-info"><Icon name="info" size={26} /><span>{mode === "reset" ? t("auth.reset.text") : t("auth.login.text")}</span></div>}
            {error && <Banner kind="danger">{error}</Banner>}
            <Field label={t("auth.username")}><input type="text" autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} /></Field>
            {setup && <Field label={t("auth.display_name")}><input type="text" value={display} onChange={(e) => setDisplay(e.target.value)} /></Field>}
            {mode === "reset" && <Field label={t("auth.recovery_key")}><input type="text" autoComplete="off" spellCheck={false} placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX" value={recovery} onChange={(e) => setRecovery(e.target.value)} required /></Field>}
            <Field label={mode === "reset" ? t("settings.new_password") : t("auth.password")}><PasswordInput value={password} onChange={setPassword} required autoComplete={setup || mode === "reset" ? "new-password" : "current-password"} /></Field>
            {(setup || mode === "reset") && <Field label={t("auth.confirm")}><PasswordInput value={confirm} onChange={setConfirm} required autoComplete="new-password" /></Field>}
            {(setup || mode === "reset") && <p className="auth-hint">{t("auth.password_rules")}</p>}
            <button className="auth-submit" disabled={busy}>{busy && <Spinner />}{setup ? t("auth.setup.submit") : mode === "reset" ? t("auth.reset.submit") : t("auth.login.submit")}</button>
            {!setup && mode === "login" && <button type="button" className="auth-link" onClick={() => { setMode("reset"); setError(""); setPassword(""); }}>{t("auth.forgot")}</button>}
            {mode === "reset" && <button type="button" className="auth-link" onClick={() => { setMode("login"); setError(""); setPassword(""); setConfirm(""); }}>{t("auth.back_to_login")}</button>}
            {mode === "reset" && <p className="auth-hint" style={{ fontSize: ".86rem" }}>{t("auth.reset.nokey")}</p>}
          </form>
        )}
      </div>
      <div className="auth-foot" role="note"><Icon name="alert" size={18} /><span>{auth?.disclaimer[lang]}</span></div>
    </div>
  );
}
