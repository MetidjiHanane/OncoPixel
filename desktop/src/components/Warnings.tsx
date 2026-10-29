import React from "react";
import { Warning } from "../api";
import { useApp } from "../state";
import { Icon } from "../ui";

/** Translated list of validation and plausibility warnings. */
export default function Warnings({ items, hideInfo }: { items: Warning[]; hideInfo?: boolean }) {
  const { t } = useApp();
  const list = hideInfo ? items.filter((w) => w.severity !== "info") : items;
  if (!list.length) return null;
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
      {list.map((w, i) => (
        <li key={i} className="row" style={{ alignItems: "flex-start", gap: 8, fontSize: ".88rem", color: w.severity === "error" ? "var(--danger)" : w.severity === "warning" ? "var(--warn)" : "var(--muted)" }}>
          <Icon name={w.severity === "info" ? "info" : "alert"} size={16} />
          <span style={{ color: "var(--text)" }}>{t(`warn.${w.code}`, w.params as any)}</span>
        </li>
      ))}
    </ul>
  );
}
