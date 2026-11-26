import { useState } from "react";
import { useResource, stamp } from "./api";
import { businessText, stateLabel } from "./presentation";
import { Panel, Status } from "./components";

type Review = {
  id: string;
  name: string;
  slot: number | null;
  reason: string;
  actor: string;
  created_at: string;
  state: string;
  notice: string;
};
export default function ReviewHistory({
  source,
  task,
  date,
  mode,
  until,
  revision,
}: {
  source: string;
  task: string;
  date: string;
  mode: string;
  until: string;
  revision: number;
}) {
  const [page, setPage] = useState(0);
  const q = new URLSearchParams({
    source_key: source,
    task_id: task,
    trading_date: date,
    mode,
    until,
  });
  const r = useResource<{ records: Review[] }>(
    "/api/v1/workspace/reviews?" + q,
    revision,
    10000,
  );
  const list = r.data?.records || [];
  return (
    <Panel
      title="复核历史"
      subtitle="保留历次意见；历史确认不自动适用于更新后的实际值。"
    >
      <Status loading={r.loading} error={r.error} />
      {!r.loading && !r.error && !list.length && (
        <p className="research-empty">当前范围暂无复核历史。</p>
      )}
      <div className="research-events">
        {list.slice(page * 10, (page + 1) * 10).map((x) => (
          <article className="unified-review-history" key={x.id}>
            <h3>
              {businessText(x.name)} ·{" "}
              {x.slot === null
                ? "原始数据"
                : `${String(Math.floor(x.slot / 4)).padStart(2, "0")}:${String((x.slot % 4) * 15).padStart(2, "0")}`}{" "}
              · {stateLabel(x.state)}
            </h3>
            <p>{businessText(x.reason)}</p>
            <small>
              {businessText(x.actor)} · {stamp(x.created_at)}
            </small>
            <p className="research-help">{businessText(x.notice)}</p>
          </article>
        ))}
      </div>
      {list.length > 10 && (
        <div className="research-filters">
          <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            上一页
          </button>
          <span>
            第 {page + 1} 页 · {list.length} 条记录
          </span>
          <button
            disabled={(page + 1) * 10 >= list.length}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </Panel>
  );
}
