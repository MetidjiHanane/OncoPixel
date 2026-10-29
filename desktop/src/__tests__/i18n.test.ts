import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import en from "../i18n/en";
import fr from "../i18n/fr";

function walk(dir: string, out: string[] = []): string[] {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (f === "i18n" || f === "__tests__") continue;
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(f)) out.push(p);
  }
  return out;
}

const placeholders = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(",");

describe("i18n dictionaries", () => {
  it("English and French have the same keys", () => {
    expect(Object.keys(fr).sort()).toEqual(Object.keys(en).sort());
  });
  it("placeholders match between languages", () => {
    for (const k of Object.keys(en)) expect([k, placeholders(fr[k])]).toEqual([k, placeholders(en[k])]);
  });
  it("no empty strings", () => {
    for (const d of [en, fr]) for (const [k, v] of Object.entries(d)) expect([k, v.trim().length > 0]).toEqual([k, true]);
  });
  it("every static t('key') used in the source exists", () => {
    const used = new Set<string>();
    for (const f of walk(join(__dirname, ".."))) {
      const src = readFileSync(f, "utf8");
      for (const m of src.matchAll(/\bt\(\s*"([a-z_]+(?:\.[A-Za-z0-9_]+)+)"/g)) used.add(m[1]);
    }
    const missing = [...used].filter((k) => !(k in en));
    expect(missing).toEqual([]);
    expect(used.size).toBeGreaterThan(100);
  });
  it("every tour step in the component has its texts", () => {
    const src = readFileSync(join(__dirname, "..", "components", "Tour.tsx"), "utf8");
    const count = [...src.matchAll(/^  \{ route: /gm)].length;
    expect(count).toBe(19);
    const ns = Array.from({ length: count }, (_, n) => String(n));
    for (const n of ns) for (const k of [`tour.s${n}.t`, `tour.s${n}.b`]) { expect(k in en).toBe(true); expect(k in fr).toBe(true); }
  });
  it("dynamic key families are complete", () => {
    const need = [
      ...["pending", "analyzed", "reviewed", "flagged"].map((s) => `status.${s}`),
      ...["glioma", "meningioma", "no_tumor", "pituitary"].map((c) => `class.${c}`),
      ...["start", "import", "analysis", "viewer", "mask", "measure", "compare", "export", "models", "privacy", "limits"].flatMap((s) => [`help.${s}.title`, `help.${s}.text`]),
      ...Array.from({ length: 19 }, (_, n) => n).flatMap((n) => [`tour.s${n}.t`, `tour.s${n}.b`]),
      ...["ready", "missing", "invalid"].map((s) => `models.state_${s}`),
      ...["environment", "settings", "default"].map((s) => `models.source_${s}`),
    ];
    expect(need.filter((k) => !(k in en))).toEqual([]);
  });
});
