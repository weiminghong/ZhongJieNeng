export type Selection = {
  source: string;
  task: string;
  date: string;
  tab: string;
  model: string;
  record: string;
  slot: number | null;
  mode: "live" | "post" | "replay";
  until: string;
  basis: "latest" | "snapshot";
  window: "tune" | "promotion" | "final_audit";
};
export const defaultSelection: Selection = {
  source: "market:shandong",
  task: "",
  date: "",
  tab: "overview",
  model: "",
  record: "",
  slot: null,
  mode: "post",
  until: "23:59",
  basis: "latest",
  window: "promotion",
};
export function readSelection(
  search: string,
  saved?: Partial<Selection>,
): Selection {
  const p = new URLSearchParams(search);
  const legacySite = !p.has("source") && p.get("workspace") === "site";
  const source =
    p.get("source") ||
    (legacySite
      ? `station:${p.get("station") || "lanneng"}:${p.get("source_mode") === "production" ? "production" : "synthetic"}`
      : "market:shandong");
  const stored = saved?.source === source ? saved : {};
  const s = {
    ...defaultSelection,
    ...stored,
    source,
    task: p.get("task") || stored.task || "",
    date: p.get("date") || p.get("ml_date") || stored.date || "",
    tab: p.get("tab") || stored.tab || "overview",
  };
  s.tab =
    (
      {
        source_review: "rsi",
        market: "raw",
        decompose: "analytics",
        connections: "flow",
      } as Record<string, string>
    )[s.tab] || s.tab;
  if (
    ![
      "overview",
      "raw",
      "learning",
      "forecast",
      "plan",
      "settlement",
      "review",
      "compare",
      "analytics",
      "rsi",
      "monitor",
      "flow",
      "trading",
      "agent",
      "settings",
    ].includes(s.tab)
  )
    s.tab = "overview";
  // Old market pointers on a station URL are never inherited.
  if (!legacySite && source === "market:shandong") {
    s.model = p.get("ml_model") || stored.model || "";
    s.record = p.get("ml_prediction") || stored.record || "";
  }
  if (legacySite) {
    s.task = "";
    s.date = "";
    s.model = "";
    s.record = "";
    s.slot = null;
  }
  const slot = p.get("slot");
  if (p.has("task") && p.get("task") !== stored.task) {
    s.model = "";
    s.record = "";
    s.slot = null;
    if (!p.has("date")) s.date = "";
  }
  if (slot !== null && !legacySite) {
    const n = Number(slot);
    s.slot = Number.isInteger(n) && n >= 0 && n < 96 ? n : null;
  }
  const mode = p.get("mode");
  if (mode === "live" || mode === "post" || mode === "replay") s.mode = mode;
  s.until = p.get("until") || stored.until || "23:59";
  if (["plan", "settlement", "review"].includes(s.tab)) { s.mode = "post"; s.until = "23:59"; }
  return s;
}
export type Change =
  | { type: "source"; source: string }
  | { type: "task"; task: string }
  | { type: "date"; date: string }
  | { type: "model"; model: string }
  | { type: "record"; record: string; model: string; date: string }
  | { type: "tab"; tab: string }
  | { type: "slot"; slot: number }
  | { type: "view"; mode: Selection["mode"]; until: string }
  | { type: "basis"; basis: Selection["basis"] }
  | { type: "window"; window: Selection["window"] }
  | {
      type: "hydrate";
      date: string;
      model: string;
      record: string;
      task?: string;
    };
export function selectionChange(s: Selection, c: Change): Selection {
  switch (c.type) {
    case "source":
      return { ...defaultSelection, source: c.source, tab: s.tab };
    case "task":
      return {
        ...defaultSelection,
        source: s.source,
        task: c.task,
        tab: s.tab,
      };
    case "date":
      return { ...s, date: c.date, record: "", slot: null };
    case "model":
      return { ...s, model: c.model, record: "", slot: null };
    case "record":
      return {
        ...s,
        record: c.record,
        model: c.model,
        date: c.date,
        slot: null,
      };
    case "tab":
      return ["plan", "settlement", "review"].includes(c.tab) ? { ...s, tab: c.tab, mode: "post", until: "23:59" } : { ...s, tab: c.tab };
    case "slot":
      return { ...s, slot: c.slot };
    case "view":
      return { ...s, mode: c.mode, until: c.until, record: "", slot: null };
    case "basis":
      return { ...s, basis: c.basis };
    case "window":
      return { ...s, window: c.window };
    case "hydrate":
      return {
        ...s,
        date: c.date,
        model: c.model,
        record: c.record,
        task: c.task ?? s.task,
      };
  }
}
export function selectionUrl(s: Selection): string {
  const p = new URLSearchParams({ source: s.source, tab: s.tab });
  if (s.task) p.set("task", s.task);
  if (s.date) p.set("date", s.date);
  if (s.slot !== null) p.set("slot", String(s.slot));
  if (s.mode !== "post") {
    p.set("mode", s.mode);
    p.set("until", s.until);
  }
  // Private record references stay in source-owned session state, not the address bar.
  return "?" + p.toString();
}
