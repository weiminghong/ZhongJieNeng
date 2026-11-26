import { businessText, sourceLabel } from "./presentation";
import { useEffect, useRef, useState } from "react";
import type { ProactiveBrief, Scope } from "./types";
import { query, request, stamp, useResource } from "./api";
import { Status } from "./components";

export default function ProactiveBriefs({
  scope,
  compact = false,
  onEnter,
  onDraft,
}: {
  scope: Scope;
  compact?: boolean;
  onEnter?: () => void;
  onDraft: (text: string, interval?: string) => void;
}) {
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fresh, setFresh] = useState<ProactiveBrief | null>(null);
  const key = query(scope);
  const current = useRef(key);
  current.current = key;
  const data = useResource<{ briefs: ProactiveBrief[] }>(
    scope.date ? "/api/v1/agent/proactive?" + key : null,
    revision,
  );
  useEffect(() => {
    setFresh(null);
    setError("");
  }, [key]);
  async function scan() {
    setBusy(true);
    setError("");
    const captured = key;
    try {
      const result = await request<ProactiveBrief>(
        "/api/v1/agent/proactive/run",
        scope,
      );
      if (current.current === captured) setFresh(result);
    } catch (e) {
      if (current.current === captured) setError((e as Error).message);
    } finally {
      setBusy(false);
      setRevision((v) => v + 1);
    }
  }
  const briefs = fresh
    ? [
        fresh,
        ...(data.data?.briefs || []).filter(
          (b) => b.brief_id !== fresh.brief_id,
        ),
      ]
    : data.data?.briefs || [];
  return (
    <section
      className={compact ? "proactive-strip" : "proactive-briefs"}
      aria-label="智能体主动研判"
    >
      <div className="proactive-heading">
        <strong>智能体主动研判</strong>
        <span className="muted">
          {briefs[0]?.headline || "暂无简报，巡检后生成真实证据"}
        </span>
        <button disabled={busy || !scope.date} onClick={() => void scan()}>
          {busy ? "正在扫描与复算…" : "立即主动巡检"}
        </button>
        {onEnter && <button onClick={onEnter}>进入智能体</button>}
      </div>
      <Status loading={busy} error={error || data.error} />
      {(compact ? briefs.slice(0, 1) : briefs).map((b) => (
        <article key={b.brief_id}>
          <span
            className={`badge ${b.severity === "critical" ? "error" : b.severity === "warning" ? "warning" : "info"}`}
          >
            {b.severity === "critical"
              ? "重点复核"
              : b.severity === "warning"
                ? "关注"
                : "信息"}
          </span>{" "}
          <small>
            {stamp(b.created_at)} · {sourceLabel(b.source_mode)}
          </small>
          {!compact && <p>{businessText(b.summary_markdown)}</p>}
          <p className="research-help">
            本次巡检引用 {b.citations.length} 条业务依据。
          </p>
          <button
            onClick={() =>
              onDraft(
                businessText(b.summary_markdown),
                b.recommended_action.rsi_intervals[0],
              )
            }
          >
            送入人工复核
          </button>
        </article>
      ))}
    </section>
  );
}
