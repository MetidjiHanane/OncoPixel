import React, { useState } from "react";
import { ModelStatus, SelfTest, post } from "../api";
import { useApp } from "../state";
import { Banner, Field, Icon, Spinner, shell } from "../ui";

function StatusCard({ m }: { m: ModelStatus }) {
  const { t, settings, updateSettings, refreshModels } = useApp();
  const key = m.kind === "classification" ? "classification_checkpoint" : "segmentation_checkpoint";
  const [path, setPath] = useState<string>((settings?.[key] as string) ?? "");
  const [busy, setBusy] = useState(false);
  const apply = async () => { setBusy(true); await updateSettings({ [key]: path.trim() }); await refreshModels(); setBusy(false); };
  const browse = async () => { const p = await shell.selectFile?.({ filters: [{ name: "PyTorch", extensions: ["pt", "pth"] }] }); if (p) setPath(p); };
  const tone = m.state === "ready" ? "ok" : m.state === "missing" ? "warn" : "danger";
  const info = m.info;
  return (
    <div className="card card-pad col">
      <div className="row"><h3 style={{ flex: 1 }}>{t(`models.${m.kind}`)}</h3><span className={`chip ${tone}`}><span className="dot" />{t(`models.state_${m.state}`)}</span></div>
      <div className="kv">
        <div className="k">{t("models.path")}</div><div className="v mono" style={{ fontSize: ".8rem", wordBreak: "break-all" }}>{m.path}</div>
        <div className="k">{t("models.path_source")}</div><div className="v">{t(`models.source_${m.path_source}`)}</div>
        {info && <>
          <div className="k">{t("models.arch")}</div><div className="v mono">{info.name}{info.encoder ? ` / ${info.encoder}` : ""}</div>
          <div className="k">{t("models.checkpoint")}</div><div className="v mono">{info.short_id}</div>
          <div className="k">{t("models.sha")}</div><div className="v mono" style={{ fontSize: ".72rem", wordBreak: "break-all" }}>{info.sha256}</div>
          <div className="k">{t("models.input")}</div><div className="v mono">{info.input_size} px</div>
          <div className="k">{t("models.size")}</div><div className="v mono">{info.size_mb} MB</div>
          <div className="k">{t("models.device")}</div><div className="v mono">{info.device}</div>
          {info.classes && <><div className="k">{t("models.classes")}</div><div className="v mono">{info.classes.join(", ")}</div></>}
        </>}
      </div>
      {m.state !== "ready" && <Banner kind={m.state === "missing" ? "warn" : "danger"} title={t(`models.state_${m.state}`)}>
        <div className="mono" style={{ fontSize: ".82rem" }}>[{m.code}] {m.detail}</div><div style={{ marginTop: 4 }}>{t(`models.hint_${m.code}`) !== `models.hint_${m.code}` ? t(`models.hint_${m.code}`) : t("models.hint_generic")}</div></Banner>}
      {info?.test_fixture && <Banner kind="danger" title={t("banner.fixture.title")}>{t("banner.fixture.text")}</Banner>}
      <Field label={t("models.custom_path")} hint={t("models.custom_hint")}>
        <div className="row"><input type="text" value={path} placeholder={m.path} onChange={(e) => setPath(e.target.value)} />{shell.selectFile && <button className="btn" onClick={browse}>{t("common.browse")}</button>}<button className="btn primary" disabled={busy} onClick={apply}>{busy ? <Spinner /> : t("common.apply")}</button></div>
      </Field>
    </div>
  );
}

export default function Models() {
  const { t, models, refreshModels, errorText, toast } = useApp();
  const [test, setTest] = useState<SelfTest | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setTest(await post<SelfTest>("/api/models/selftest")); } catch (e) { toast(errorText(e), "error"); } finally { setBusy(false); } };
  return (
    <div className="page">
      <div className="page-head">
        <div className="grow"><h1>{t("models.title")}</h1><p className="sub">{t("models.subtitle")}</p></div>
        <button className="btn" onClick={() => refreshModels()}>{t("models.reload")}</button>
        <button className="btn primary" disabled={busy || !models?.all_ready} onClick={run}>{busy ? <Spinner /> : <Icon name="check" size={18} />}{t("models.selftest")}</button>
      </div>
      {models && !models.all_ready && <Banner kind="warn" title={t("banner.missing.title")}>{t("models.missing_explain")}</Banner>}
      {models && (
        <div className="card card-pad"><div className="row wrap" style={{ gap: 18 }}>
          <span><b>{t("models.device")}:</b> <span className="mono">{models.resolved_device}</span></span>
          {Object.entries(models.devices).map(([d, ok]) => <span key={d} className={`chip ${ok ? "ok" : ""}`}>{d}: {ok ? t("common.yes") : t("common.no")}</span>)}
        </div></div>
      )}
      {models && <div className="grid c2" data-tour="models-cards"><StatusCard m={models.models.classification} /><StatusCard m={models.models.segmentation} /></div>}
      {test && (
        <div className="card card-pad col">
          <div className="row"><h3 style={{ flex: 1 }}>{t("models.selftest_result")}</h3><span className={`chip ${test.all_ok ? "ok" : "danger"}`}>{test.all_ok ? t("models.selftest_ok") : t("models.selftest_fail")}</span></div>
          <p className="sub">{t("models.selftest_note")}</p>
          {(["classification", "segmentation"] as const).map((k) => (
            <div key={k} className="col" style={{ gap: 4 }}>
              <b>{t(`models.${k}`)}{test[k]?.forward_ms != null && <span className="mono sub"> · {test[k]!.forward_ms} ms ({test.device})</span>}</b>
              {test[k]?.checks.map((c) => <div key={c.name} className="row" style={{ gap: 8, fontSize: ".9rem" }}><Icon name={c.ok ? "check" : "x"} size={16} /><span style={{ color: c.ok ? "var(--text)" : "var(--danger)" }}>{t(`check.${c.name}`)}</span><span className="mono sub">{c.detail}</span></div>)}
              {test[k]?.state !== "ready" && <Banner kind="danger">{test[k]?.error?.detail}</Banner>}
            </div>))}
        </div>
      )}
      <div className="card card-pad col"><h3>{t("models.how")}</h3><p className="sub">{t("models.how_text")}</p><pre className="mono" style={{ margin: 0, padding: 12, background: "var(--bg)", borderRadius: 8, overflow: "auto", fontSize: ".82rem" }}>{`models/classification/best.pt\nmodels/segmentation/tumor_seg_model.pt`}</pre></div>
    </div>
  );
}
