import React, { useEffect, useState } from "react";
import { useApp } from "../state";
import { Field, Icon } from "../ui";
import { FORMATS } from "../components/Panels";

type Tab = "classification" | "segmentation" | "measurements" | "report";

/**
 * An empty copy of the study page. It is used only by the guided tour, so that every part of the study
 * screen can be shown even when no image has been imported yet. Nothing here is stored or analysed.
 */
export default function StudyPreview() {
  const { t } = useApp();
  const [tab, setTab] = useState<Tab>("classification");
  useEffect(() => {
    const h = (e: Event) => setTab((e as CustomEvent).detail as Tab);
    window.addEventListener("op-tour-tab", h);
    return () => window.removeEventListener("op-tour-tab", h);
  }, []);
  const tabs: [Tab, string][] = [["classification", "study.tab_cls"], ["segmentation", "study.tab_seg"], ["measurements", "study.tab_meas"], ["report", "study.tab_report"]];
  const tools: [string, string][] = [["hand", "viewer.tool_pan"], ["zoomin", "viewer.zoom_in"], ["zoomout", "viewer.zoom_out"], ["fit", "viewer.fit"], ["brush", "viewer.tool_brush"], ["eraser", "viewer.tool_eraser"]];
  return (
    <div className="page">
      <div className="page-head">
        <div className="grow"><h1 className="mono" style={{ fontSize: "1.35rem" }}>{t("preview.title")}</h1><p className="sub">{t("preview.sub")}</p></div>
        <button className="btn primary" disabled style={{ height: 42 }} data-tour="analyze"><Icon name="play" size={18} />{t("study.analyze")}</button>
      </div>
      <div className="viewer-grid">
        <div className="col">
          <div className="stage" aria-label={t("viewer.label")}>
            <div className="stage-tools" role="toolbar" aria-label={t("viewer.tools")}>
              {tools.map(([ic, key], i) => (
                <React.Fragment key={ic}>
                  {i === 4 && <hr style={{ width: "100%", border: 0, borderTop: "1px solid var(--border2)", margin: "2px 0" }} />}
                  <button className={`btn icon sm ${i === 0 ? "on" : ""}`} disabled={i !== 0} aria-label={t(key)}><Icon name={ic} size={18} /></button>
                </React.Fragment>
              ))}
            </div>
            <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "#8fa6ab", textAlign: "center", padding: 24 }}>
              <div><Icon name="upload" size={38} /><p style={{ marginTop: 8 }}>{t("preview.no_image")}</p></div>
            </div>
          </div>
        </div>
        <div className="side" data-tour="v-panel">
          <div className="tabs" role="tablist">{tabs.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{t(label)}</button>)}</div>
          {tab === "classification" && <div className="card card-pad"><p className="sub">{t("cls.none")}</p></div>}
          {tab === "segmentation" && <div className="card card-pad"><p className="sub">{t("seg.none")}</p></div>}
          {tab === "measurements" && <div className="card card-pad"><p className="sub">{t("meas.none")}</p></div>}
          {tab === "report" && (
            <div className="col">
              <div className="card card-pad col" data-tour="review">
                <h3>{t("review.title")}</h3>
                <p className="sub">{t("review.need_analysis")}</p>
                <Field label={t("review.note")}><textarea disabled /></Field>
                <div className="row wrap">
                  <button className="btn primary" disabled><Icon name="check" size={18} />{t("review.mark")}</button>
                  <button className="btn" disabled><Icon name="flag" size={18} />{t("review.flag")}</button>
                </div>
              </div>
              <div className="card card-pad col" data-tour="exports">
                <h3>{t("export.title")}</h3>
                <div className="grid c2" style={{ gap: 8 }}>
                  {FORMATS.map(([fmt, , key]) => (
                    <div key={fmt} className="row" style={{ gap: 4 }}>
                      <span className="btn sm ghost" style={{ flex: 1, opacity: 0.6 }}><Icon name="download" size={15} />{t(key)}</span>
                    </div>))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
