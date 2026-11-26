import { fmt, stamp } from "./api";
import {
  businessText,
  fieldLabel,
  stateLabel,
  taskLabel,
} from "./presentation";

export default function BusinessFacts({ value }: { value: unknown }) {
  const items: { label: string; value: string }[] = [];
  function visit(input: unknown) {
    if (!input || typeof input !== "object" || items.length >= 12) return;
    for (const [key, v] of Object.entries(input)) {
      if (items.length >= 12) break;
      if (typeof v === "object" && v !== null) {
        visit(v);
        continue;
      }
      const label = fieldLabel(key);
      if (label === "业务记录") continue;
      const shown =
        v === null
          ? "缺失"
          : typeof v === "number"
            ? fmt(v, 2)
            : key === "task"
              ? taskLabel(String(v))
              : key === "quality_flag" || key === "status"
                ? stateLabel(String(v))
                : key.endsWith("_at") ||
                    key.startsWith("interval_") ||
                    key.startsWith("target_")
                  ? stamp(String(v))
                  : businessText(v);
      items.push({ label, value: shown });
    }
  }
  visit(value);
  return items.length ? (
    <dl className="research-facts">
      {items.map((item, i) => (
        <div key={i}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  ) : (
    <p className="research-help">暂无可展示的业务数值，请结合原始记录核对。</p>
  );
}
