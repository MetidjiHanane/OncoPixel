import React from "react";
import { Link } from "react-router-dom";
import { useApp } from "../state";
import { Banner } from "../ui";

/** Always tells the truth about the models: missing, invalid, or an untrained test fixture. */
export default function ModelBanner() {
  const { models, t } = useApp();
  if (!models) return null;
  const bad = (["classification", "segmentation"] as const).map((k) => models.models[k]).filter((m) => m.state !== "ready");
  return (
    <>
      {bad.length > 0 && (
        <Banner kind="warn" title={t("banner.missing.title")} action={<Link className="btn sm" to="/models">{t("banner.missing.action")}</Link>}>
          {bad.map((m) => <div key={m.kind}>{t(`err.model_${m.state}`, { kind: t(`models.${m.kind}`), reason: m.code ?? "", path: m.path })}</div>)}
          <div style={{ marginTop: 4 }}>{t("banner.missing.text")}</div>
        </Banner>
      )}
      {models.any_test_fixture && <Banner kind="danger" title={t("banner.fixture.title")}>{t("banner.fixture.text")}</Banner>}
    </>
  );
}
