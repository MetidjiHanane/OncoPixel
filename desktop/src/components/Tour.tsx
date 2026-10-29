import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useApp } from "../state";

type Side = "right" | "left" | "bottom" | "top";
interface Step {
  /** Page to show. null keeps the current page. */
  route: string | null;
  /** CSS selector of the element to highlight; null shows a centred card. */
  sel: string | null;
  side?: Side;
  /** Study tab to open (the study page used here is an empty copy, so the tour works without any image). */
  tab?: string;
}

// Texts live in i18n as tour.s{index}.t / tour.s{index}.b
const STEPS: Step[] = [
  { route: "/", sel: "[data-tour=dash-stats]", side: "bottom" },
  { route: "/", sel: "[data-tour=topbar-user]", side: "bottom" },
  { route: "/import", sel: "[data-tour=import-drop]", side: "bottom" },
  { route: "/import", sel: "[data-tour=import-patient]", side: "left" },
  { route: "/study-preview", sel: ".stage-tools", side: "right", tab: "classification" },
  { route: "/study-preview", sel: ".stage", side: "bottom", tab: "classification" },
  { route: "/study-preview", sel: "[data-tour=analyze]", side: "bottom", tab: "classification" },
  { route: "/study-preview", sel: "[data-tour=v-panel]", side: "left", tab: "classification" },
  { route: "/study-preview", sel: "[data-tour=v-panel]", side: "left", tab: "segmentation" },
  { route: "/study-preview", sel: "[data-tour=v-panel]", side: "left", tab: "measurements" },
  { route: "/study-preview", sel: "[data-tour=review]", side: "left", tab: "report" },
  { route: "/study-preview", sel: "[data-tour=exports]", side: "left", tab: "report" },
  { route: "/patients", sel: "[data-tour=nav-patients]", side: "right" },
  { route: "/studies", sel: "[data-tour=nav-history]", side: "right" },
  { route: "/compare", sel: "[data-tour=compare-pick]", side: "bottom" },
  { route: null, sel: "[data-tour=nav-models]", side: "right" },
  { route: "/settings", sel: "[data-tour=nav-settings]", side: "right" },
  { route: "/help", sel: "[data-tour=nav-help]", side: "right" },
  { route: "/", sel: "[data-tour=disclaimer]", side: "bottom" },
];

const CARD_W = 340;

export default function Tour({ onClose }: { onClose: () => void }) {
  const { t } = useApp();
  const nav = useNavigate();
  const loc = useLocation();
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: 0, top: 0 });
  const [ready, setReady] = useState(false);
  const step = STEPS[i];
  const last = i === STEPS.length - 1;

  // Remember the page the user was on, so the tour can bring them back when it ends.
  const origin = useRef(loc.pathname);
  const close = () => { if (loc.pathname === "/study-preview") nav(origin.current === "/study-preview" ? "/" : origin.current); onClose(); };

  useEffect(() => { if (step.route && loc.pathname !== step.route) nav(step.route); }, [i]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (step.tab) window.dispatchEvent(new CustomEvent("op-tour-tab", { detail: step.tab }));
  }, [i, step.tab, loc.pathname]);

  // Find the element. The previous highlight stays in place until the new one is found, so the move is animated
  // instead of jumping (the page may still be rendering after a navigation).
  useEffect(() => {
    let stop = false, tries = 0, timer: number | undefined;
    const find = () => {
      if (stop) return;
      if (!step.sel) { setRect(null); setReady(true); return; }
      const el = document.querySelector(step.sel) as HTMLElement | null;
      const onPage = !step.route || window.location.pathname === step.route || loc.pathname === step.route;
      if (el && onPage) {
        el.scrollIntoView({ block: "nearest", inline: "nearest" });
        const r = el.getBoundingClientRect();
        // wait one more frame so that a tab or layout change has settled
        timer = window.setTimeout(() => { if (!stop) { setRect(el.getBoundingClientRect()); setReady(true); } }, tries === 0 ? 60 : 30);
        void r;
      } else if (tries++ < 40) timer = window.setTimeout(find, 60);
      else { setRect(null); setReady(true); }
    };
    find();
    const onResize = () => { const el = step.sel ? (document.querySelector(step.sel) as HTMLElement | null) : null; setRect(el ? el.getBoundingClientRect() : null); };
    window.addEventListener("resize", onResize);
    return () => { stop = true; if (timer) clearTimeout(timer); window.removeEventListener("resize", onResize); };
  }, [i, loc.pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "ArrowRight") setI((x) => Math.min(STEPS.length - 1, x + 1));
      if (e.key === "ArrowLeft") setI((x) => Math.max(0, x - 1));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => {
    const h = card.current?.offsetHeight ?? 200;
    const vw = window.innerWidth, vh = window.innerHeight;
    if (!rect) return setPos({ left: (vw - CARD_W) / 2, top: Math.max(40, (vh - h) / 2 - 40) });
    let left = rect.left, top = rect.bottom + 14;
    const side = step.side ?? "bottom";
    if (side === "right") { left = rect.right + 14; top = rect.top + 8; }
    else if (side === "left") { left = rect.left - CARD_W - 14; top = rect.top + 8; }
    else if (side === "top") top = rect.top - h - 14;
    setPos({ left: Math.min(Math.max(12, left), vw - CARD_W - 12), top: Math.min(Math.max(12, top), vh - h - 12) });
  }, [rect, step.side, i]);

  // With no element to point at the spotlight shrinks to the middle of the screen, so the dimmed background never flickers.
  const spot = rect
    ? { left: rect.left - 5, top: rect.top - 5, width: rect.width + 10, height: rect.height + 10, opacity: 1 }
    : { left: window.innerWidth / 2, top: window.innerHeight / 2, width: 0, height: 0, opacity: 0 };

  return (
    <>
      <div className="tour-mask" />
      <div className="tour-spot" style={spot} />
      <div className={`tour-card ${ready ? "" : "wait"}`} ref={card} style={pos} role="dialog" aria-label={t("tour.title")} aria-live="polite">
        <div key={i} className="tour-body">
          <div className="tour-step">{t("tour.step", { n: i + 1, total: STEPS.length })}</div>
          <h3>{t(`tour.s${i}.t`)}</h3>
          <p>{t(`tour.s${i}.b`)}</p>
        </div>
        <div className="tour-dots">{STEPS.map((_, k) => <i key={k} className={k === i ? "on" : ""} />)}</div>
        <div className="tour-actions">
          <button className="btn sm ghost" onClick={close}>{t("tour.skip")}</button>
          <span style={{ flex: 1 }} />
          <button className="btn sm" disabled={i === 0} onClick={() => setI(i - 1)}>{t("common.back")}</button>
          {last
            ? <button className="btn sm primary" onClick={close}>{t("tour.finish")}</button>
            : <button className="btn sm primary" onClick={() => setI(i + 1)}>{t("common.next")}</button>}
        </div>
      </div>
    </>
  );
}
