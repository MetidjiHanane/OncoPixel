import React, { useState } from "react";
import { post, api } from "../api";
import { useApp } from "../state";
import { Banner, Field, Icon, PasswordInput, Spinner, shell } from "../ui";

export default function SettingsPage() {
  const { t, settings: s, updateSettings, toast, errorText, models, signOut, auth, refreshAuth } = useApp();
  const [rkey, setRkey] = useState("");
  const [pw, setPw] = useState({ cur: "", next: "", confirm: "" });
  const [bk, setBk] = useState({ pass: "", restorePass: "" });
  const [busy, setBusy] = useState("");
  if (!s) return null;

  const changePw = async () => {
    if (pw.next !== pw.confirm) { toast(t("err.password_mismatch"), "error"); return; }
    try { await post("/api/auth/password", { current_password: pw.cur, new_password: pw.next }); toast(t("common.saved")); setPw({ cur: "", next: "", confirm: "" }); }
    catch (e) { toast(errorText(e), "error"); }
  };
  const makeKey = async () => {
    try { const r = await post<{ recovery_key: string }>("/api/auth/recovery-key", { current_password: pw.cur }); setRkey(r.recovery_key); setPw({ ...pw, cur: "" }); await refreshAuth(); }
    catch (e) { toast(errorText(e), "error"); }
  };
  const backup = async () => {
    setBusy("backup");
    try { const r = await post<{ path: string; name: string; size_mb: number }>("/api/backup", { passphrase: bk.pass }); toast(t("settings.backup_done", { path: r.path })); shell.showItemInFolder?.(r.path); setBk({ ...bk, pass: "" }); }
    catch (e) { toast(errorText(e), "error"); } finally { setBusy(""); }
  };
  const restore = async (file: File) => {
    setBusy("restore");
    try {
      const fd = new FormData(); fd.append("file", file); fd.append("passphrase", bk.restorePass);
      await api("/api/backup/restore", { method: "POST", body: fd });
      toast(t("settings.restore_done")); await signOut();
    } catch (e) { toast(errorText(e), "error"); } finally { setBusy(""); }
  };
  const pickExport = async () => { const p = await shell.selectFolder?.(); if (p) updateSettings({ export_dir: p }); };

  return (
    <div className="page">
      <div className="page-head"><div className="grow"><h1>{t("settings.title")}</h1><p className="sub">{t("settings.subtitle")}</p></div></div>
      <div className="grid c2" style={{ alignItems: "start" }}>
        <div className="col">
          <div className="card card-pad col">
            <h3>{t("settings.display")}</h3>
            <Field label={t("settings.theme")}><div className="seg">{(["dark", "light"] as const).map((k) => <button key={k} className={s.theme === k ? "on" : ""} onClick={() => updateSettings({ theme: k })}>{t(`settings.theme_${k}`)}</button>)}</div></Field>
            <Field label={t("settings.language")}><div className="seg">{(["en", "fr"] as const).map((k) => <button key={k} className={s.language === k ? "on" : ""} onClick={() => updateSettings({ language: k })}>{k === "en" ? "English" : "Français"}</button>)}</div></Field>
            <Field label={t("settings.font")}><div className="seg">{(["small", "medium", "large"] as const).map((k) => <button key={k} className={s.font_size === k ? "on" : ""} onClick={() => updateSettings({ font_size: k })}>{t(`settings.font_${k}`)}</button>)}</div></Field>
            <label className="check"><input type="checkbox" checked={s.high_contrast} onChange={(e) => updateSettings({ high_contrast: e.target.checked })} /><span>{t("settings.contrast")}<small>{t("settings.contrast_hint")}</small></span></label>
            <label className="check"><input type="checkbox" checked={s.show_contour} onChange={(e) => updateSettings({ show_contour: e.target.checked })} /><span>{t("settings.contour")}</span></label>
            <Field label={`${t("seg.opacity")}: ${Math.round(s.overlay_opacity * 100)}%`}><input type="range" min={0} max={1} step={0.05} value={s.overlay_opacity} onChange={(e) => updateSettings({ overlay_opacity: Number(e.target.value) })} /></Field>
          </div>
          <div className="card card-pad col">
            <h3>{t("settings.inference")}</h3>
            <Field label={t("settings.device")} hint={t("settings.device_hint", { d: models?.resolved_device ?? "" })}>
              <select value={s.device} onChange={(e) => updateSettings({ device: e.target.value as any })}>{["auto", "mps", "cpu"].map((d) => <option key={d} value={d}>{d === "auto" ? t("settings.device_auto") : d.toUpperCase()}</option>)}</select></Field>
            <label className="check"><input type="checkbox" checked={s.classifier_tta} onChange={(e) => updateSettings({ classifier_tta: e.target.checked })} /><span>{t("settings.cls_tta")}<small>{t("settings.cls_tta_hint")}</small></span></label>
            <Field label={t("settings.seg_tta")}><select value={s.segmenter_tta === null ? "default" : String(s.segmenter_tta)} onChange={(e) => updateSettings({ segmenter_tta: e.target.value === "default" ? null : e.target.value === "true" })}><option value="default">{t("settings.model_default")}</option><option value="true">{t("common.yes")}</option><option value="false">{t("common.no")}</option></select></Field>
            <Field label={`${t("settings.review_threshold")}: ${Math.round(s.review_threshold * 100)} %`} hint={t("settings.review_hint")}><input type="range" min={0.5} max={0.99} step={0.01} value={s.review_threshold} onChange={(e) => updateSettings({ review_threshold: Number(e.target.value) })} /></Field>
            <Field label={t("settings.seg_threshold")} hint={t("settings.seg_threshold_hint")}><div className="row"><input type="number" min={0.05} max={0.95} step={0.01} value={s.segmentation_threshold ?? ""} placeholder={t("settings.model_default")} onChange={(e) => updateSettings({ segmentation_threshold: e.target.value === "" ? null : Number(e.target.value) })} /></div></Field>
          </div>
        </div>
        <div className="col">
          <div className="card card-pad col">
            <h3>{t("settings.data")}</h3>
            <Field label={t("settings.export_dir")}><div className="row"><input type="text" value={s.export_dir} onChange={(e) => updateSettings({ export_dir: e.target.value })} />{shell.selectFolder && <button className="btn" onClick={pickExport}>{t("common.browse")}</button>}</div></Field>
            <Field label={t("settings.report_lang")}><div className="seg">{(["en", "fr"] as const).map((k) => <button key={k} className={s.report_language === k ? "on" : ""} onClick={() => updateSettings({ report_language: k })}>{k === "en" ? "English" : "Français"}</button>)}</div></Field>
            <label className="check"><input type="checkbox" checked={s.anonymize_exports} onChange={(e) => updateSettings({ anonymize_exports: e.target.checked })} /><span>{t("export.anonymize")}<small>{t("export.anonymize_hint")}</small></span></label>
            <Banner kind="info">{t("settings.encrypted_note")}</Banner>
          </div>
          <div className="card card-pad col">
            <h3>{t("settings.backup")}</h3><p className="sub">{t("settings.backup_text")}</p>
            <Field label={t("settings.passphrase")}><input type="password" value={bk.pass} autoComplete="new-password" onChange={(e) => setBk({ ...bk, pass: e.target.value })} /></Field>
            <button className="btn" disabled={bk.pass.length < 8 || !!busy} onClick={backup}>{busy === "backup" ? <Spinner /> : <Icon name="download" size={18} />}{t("settings.backup_now")}</button>
            <hr style={{ border: 0, borderTop: "1px solid var(--border)", width: "100%" }} />
            <Field label={t("settings.restore_pass")}><input type="password" value={bk.restorePass} autoComplete="off" onChange={(e) => setBk({ ...bk, restorePass: e.target.value })} /></Field>
            <label className={`btn ${bk.restorePass ? "" : "ghost"}`} style={{ opacity: bk.restorePass ? 1 : 0.5 }}>{busy === "restore" ? <Spinner /> : <Icon name="upload" size={18} />}{t("settings.restore_now")}
              <input type="file" accept=".opbackup" hidden disabled={!bk.restorePass || !!busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) restore(f); e.target.value = ""; }} /></label>
            <p className="sub" style={{ fontSize: ".8rem" }}>{t("settings.restore_note")}</p>
          </div>
          <div className="card card-pad col">
            <h3>{t("settings.account")}</h3>
            <Field label={t("settings.current_password")}><PasswordInput autoComplete="current-password" value={pw.cur} onChange={(v) => setPw({ ...pw, cur: v })} /></Field>
            <Field label={t("settings.new_password")} hint={t("auth.password_rules")}><PasswordInput autoComplete="new-password" value={pw.next} onChange={(v) => setPw({ ...pw, next: v })} /></Field>
            <Field label={t("auth.confirm")}><PasswordInput autoComplete="new-password" value={pw.confirm} onChange={(v) => setPw({ ...pw, confirm: v })} /></Field>
            <button className="btn" disabled={!pw.cur || !pw.next} onClick={changePw}>{t("settings.change_password")}</button>
            <hr style={{ border: 0, borderTop: "1px solid var(--border)", width: "100%" }} />
            <h3>{t("settings.recovery")}</h3>
            <p className="sub">{auth?.user?.has_recovery_key ? t("settings.recovery_set") : t("settings.recovery_none")}</p>
            <button className="btn" disabled={!pw.cur} onClick={makeKey}><Icon name="shield" size={18} />{t("settings.recovery_make")}</button>
            {rkey && <><div className="recovery-key">{rkey}</div><p className="sub" style={{ fontSize: ".82rem" }}>{t("settings.recovery_shown")}</p></>}
          </div>
        </div>
      </div>
    </div>
  );
}
