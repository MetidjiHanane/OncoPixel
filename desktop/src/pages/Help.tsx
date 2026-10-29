import React, { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useApp } from "../state";
import { Icon } from "../ui";

const SECTIONS = ["start", "import", "analysis", "viewer", "mask", "measure", "compare", "export", "models", "privacy", "limits"] as const;
const SHORTCUTS: [string, string][] = [
  ["1 – 7", "help.sc_nav"], ["?", "help.sc_help"], ["+  /  -", "help.sc_zoom"], ["0", "help.sc_fit"], ["H", "help.sc_pan"],
  ["B  /  E", "help.sc_brush"], ["[  /  ]", "help.sc_size"], ["Ctrl/⌘ Z", "help.sc_undo"], ["Ctrl/⌘ ⇧ Z", "help.sc_redo"], ["Ctrl/⌘ S", "help.sc_save"],
  ["↑ ↓ / PgUp PgDn / wheel", "help.sc_slice"], ["Ctrl/⌘ + wheel", "help.sc_wheel"], ["Shift + drag", "help.sc_drag"], ["Esc", "help.sc_esc"],
];

export default function Help() {
  const { t, auth, lang } = useApp();
  const loc = useLocation();
  useEffect(() => { if (loc.hash) document.querySelector(loc.hash)?.scrollIntoView(); }, [loc.hash]);
  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <div className="page-head"><div className="grow"><h1>{t("help.title")}</h1><p className="sub">{t("help.subtitle")}</p></div></div>
      <div className="card card-pad md">
        {SECTIONS.map((s) => (
          <section key={s} id={s}>
            <h2>{t(`help.${s}.title`)}</h2>
            {t(`help.${s}.text`).split("\n").map((line, i) => line.startsWith("- ") ? <ul key={i}><li>{line.slice(2)}</li></ul> : <p key={i}>{line}</p>)}
          </section>
        ))}
      </div>
      <div className="card card-pad col" id="shortcuts">
        <h2><Icon name="keyboard" size={20} /> {t("help.shortcuts")}</h2>
        <div className="kv">{SHORTCUTS.map(([k, d]) => <React.Fragment key={k}><div className="k"><kbd>{k}</kbd></div><div className="v">{t(d)}</div></React.Fragment>)}</div>
      </div>
      <div className="card card-pad col">
        <h2>{t("help.about")}</h2>
        <p className="sub">{t("help.about_text", { v: auth?.app.version ?? "" })}</p>
        <p className="disclaimer">{auth?.disclaimer[lang]}</p>
      </div>
    </div>
  );
}
