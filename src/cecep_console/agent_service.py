"""Two evidence channels: SQL/calculation tools and FTS5/TF-IDF knowledge."""

from collections import Counter
from datetime import datetime
import json
import math
import re
import time
from .model_settings import load_settings, select_evidence, ProviderError, provider_open as urlopen
from uuid import uuid4
from .storage import encoded, digest, instant
from .serving import (
    build_intervals,
    compare_versions,
    daily_kpi,
    data_clock,
    day_bounds,
    rows,
    now,
)
from .trading import trading_overview
from .model_runtime import run_model_inference, list_runtime_models
from .proactive import forecast_sandbox


def terms(text):
    words = re.findall(r"[a-zA-Z_]+|[\u4e00-\u9fff]+", text.lower())
    result = []
    for word in words:
        result.append(word)
        if re.search(r"[\u4e00-\u9fff]", word):
            result += [word[i : i + 2] for i in range(len(word) - 1)]
    return result


def search_knowledge_rag(
    store, question, station_id, cutoff, source_mode="synthetic", limit=5
):
    docs = rows(
        store,
        "SELECT c.*,d.title,d.collection,d.source_uri,d.source_mode FROM rag_chunk c JOIN rag_document d USING(doc_id) WHERE d.status='active' AND d.source_mode=? AND (d.station_id IS NULL OR d.station_id=?) AND d.effective_from<=? AND (d.effective_to IS NULL OR d.effective_to>?) AND d.created_at<=?",
        (source_mode, station_id, cutoff, cutoff, cutoff),
    )
    if not docs:
        return []
    tokens = set(terms(question))
    query = " OR ".join('"' + t.replace('"', '""') + '"' for t in sorted(tokens)[:80])
    fts = (
        {
            r["chunk_id"]: r["score"]
            for r in rows(
                store,
                "SELECT chunk_id,bm25(rag_chunk_fts) AS score FROM rag_chunk_fts WHERE rag_chunk_fts MATCH ? ORDER BY score LIMIT 100",
                (query,),
            )
        }
        if query
        else {}
    )
    counts = [Counter(terms(d["heading_path"] + " " + d["content_text"])) for d in docs]
    results = []
    for doc, counts_doc in zip(docs, counts):
        tfidf = 0.0
        for token in tokens:
            df = sum(token in c for c in counts)
            if token in counts_doc:
                tfidf += (1 + math.log(counts_doc[token])) * math.log(
                    1 + len(docs) / (1 + df)
                )
        if not tfidf and doc["chunk_id"] not in fts:
            continue
        results.append(
            {
                **doc,
                "fts_bm25": fts.get(doc["chunk_id"]),
                "tfidf_score": tfidf,
                "score": tfidf + (1 if doc["chunk_id"] in fts else 0),
                "retrieval": "FTS5 BM25 + Chinese bigram TF-IDF",
            }
        )
    return sorted(results, key=lambda r: (-r["score"], r["chunk_id"]))[:limit]


def query_agent(store, question, scope, user_id="operator", session_id=None):
    started = time.perf_counter()
    station, day = scope["station_id"], scope["date"]
    mode = scope.get("source_mode", "synthetic")
    cutoff = instant(scope.get("cutoff_at") or data_clock(store, mode))
    intervals = build_intervals(
        store,
        station,
        day,
        cutoff,
        mode,
        registry_cutoff=cutoff if scope.get("mode") == "replay" else None,
    )
    selected = scope.get("selected_interval")
    focus = (
        [r for r in intervals if r["interval_start"] == selected]
        if selected
        else intervals
    )
    if selected and not focus:
        raise ValueError("选中时段不在当前交易日")
    kpi = daily_kpi(focus, cutoff)
    tool_inputs = {**scope, "cutoff_at": cutoff}
    calls = []

    def call(name, operation, extra_input=None):
        begin = now()
        output = operation()
        calls.append(
            {
                "tool_name": name,
                "input": {**tool_inputs, **(extra_input or {})},
                "output": output,
                "started_at": begin,
                "finished_at": now(),
            }
        )
        return output

    numerical = call(
        "query_timeseries",
        lambda: {
            "kpi": kpi,
            "interval_count": len(focus),
            "cutoff_at": cutoff,
            "selected_interval": selected,
            "lineage_refs": [json.loads(r["lineage_refs_json"]) for r in focus[:4]],
        },
    )
    comparisons = call(
        "compare_forecast_versions",
        lambda: compare_versions(store, station, day, cutoff, mode),
    ) if re.search("比较|版本|预测|复盘|方案|合约", question) else []
    diagnoses = call(
        "diagnose_deviation",
        lambda: [
            {
                "interval_start": r["interval_start"],
                "error_mw": r["actual_mw"] - r["da_forecast_mw"],
                "cloud_cover_pct": r["cloud_cover_pct"],
                "event_flag": r["active_event_flag"],
                "interpretation": "同期线索，需人工确认因果",
            }
            for r in sorted(
                [
                    r
                    for r in focus
                    if r["actual_mw"] is not None and r["da_forecast_mw"] is not None
                ],
                key=lambda r: abs(r["actual_mw"] - r["da_forecast_mw"]),
                reverse=True,
            )[:5]
        ],
    )
    revenues = call(
        "simulate_bidding_revenue",
        lambda: [
            {
                k: p[k]
                for k in (
                    "plan_id",
                    "plan_name",
                    "net_revenue_yuan",
                    "settled_count",
                    "unsettled_count",
                    "components",
                    "scope",
                )
            }
            for p in trading_overview(store, station, day, mode, cutoff)["plans"]
        ],
    ) if re.search("收益|申报|交易|合约|考核|复盘|沙盘|方案|场景", question) else []
    quality = call(
        "inspect_data_quality",
        lambda: {
            "missing_count": kpi["missing_count"],
            "due_count": kpi["due_count"],
            "observed_count": kpi["observed_count"],
            "pending_count": sum(r["quality_flag"] == "pending" for r in focus),
        },
    )
    knowledge_cutoff = cutoff if scope.get("mode") == "replay" else now()
    knowledge = call(
        "search_knowledge_rag",
        lambda: {
            "knowledge_cutoff_at": knowledge_cutoff,
            "chunks": search_knowledge_rag(
                store, question, station, knowledge_cutoff, mode
            ),
        },
    )["chunks"]
    inference = None
    what_if = bool(re.search(r"云量\s*[+-]?\d+(?:\.\d+)?\s*%|(?:升温|温度增加|温度)\s*[+-]?\d|限电(?:至|上限)?\s*[\d.]+\s*(?:MW|兆瓦)|假设|如果|重算预测|场景推演", question, re.I))
    runtime_id = None
    registry_cutoff = cutoff if scope.get("mode") == "replay" else now()
    if what_if or re.search("小模型|实时预测|实时推理", question):
        available = [m for m in list_runtime_models(store, registry_cutoff) if m["source_mode"] == mode and m["task"] == "day_ahead_power"]
        named = next((m for m in available if m["model_version_id"] in question or m["model_name"] in question), None)
        if named and not named["ready"]:
            raise ValueError(named["readiness_note"])
        preferred = named or next((m for m in available if m["ready"] and m["effective_status"] == "production"), None)
        runtime_id = preferred["model_version_id"] if preferred else None
    if what_if or re.search("小模型|实时预测|实时推理", question):
        inference = call("invoke_forecast_model", lambda: run_model_inference(
            store, station_id=station, trading_date=day, cutoff_at=cutoff, source_mode=mode,
            model_version_id=runtime_id, registry_cutoff=registry_cutoff), {"model_version_id": runtime_id})
    if what_if:
        overrides = {}
        patterns = [("cloud_delta_pct", r"云量\s*([+-]?\d+(?:\.\d+)?)\s*%"),
                    ("temp_delta_c", r"(?:升温|温度增加|温度)\s*([+-]?\d+(?:\.\d+)?)"),
                    ("curtailment_cap_mw", r"限电(?:至|上限)?\s*([\d.]+)\s*(?:MW|兆瓦)")]
        for key, pattern in patterns:
            found = re.search(pattern, question, re.I)
            if found:
                overrides[key] = float(found[1])
        if not overrides:
            raise ValueError("请明确场景参数，例如云量+30%、升温3℃或限电至20MW")

        def scenario_operation():
            scenario = run_model_inference(store, station_id=station, trading_date=day,
                                           cutoff_at=cutoff, source_mode=mode, overrides=overrides,
                                           model_version_id=runtime_id, registry_cutoff=registry_cutoff)
            try:
                scenario["sandbox"] = forecast_sandbox(store, scope, cutoff, intervals, inference, scenario)
            except ValueError as exc:
                scenario["sandbox"] = {"status": "unavailable", "reason": str(exc)}
            return scenario

        inference = call("run_what_if_forecast", scenario_operation, {"model_version_id":runtime_id, "overrides":overrides})
    artifacts = build_artifacts(calls)
    citations = [
        {"kind": "tool", "tool_name": c["tool_name"], "citation_id": f"tool-{i+1}"}
        for i, c in enumerate(calls)
    ]
    citations += [
        {
            "kind": "rag",
            "citation_id": r["chunk_id"],
            "chunk_id": r["chunk_id"],
            "doc_id": r["doc_id"],
            "title": r["title"],
            "source_uri": r["source_uri"],
        }
        for r in knowledge
    ]

    def number(v):
        return "暂无配对数据" if v is None else f"{v:.2f}"

    answer = f'当前分析覆盖 {len(focus)} 个时段，已到达并配对 {quality["observed_count"]} 个。功率 MAE 为 {number(kpi["power_mae_mw"])} MW，实测电量为 {number(kpi["energy_actual_mwh"])} MWh。'
    if diagnoses:
        d = diagnoses[0]
        answer += f' 重点复核时段 {d["interval_start"]}，偏差 {d["error_mw"]:.2f} MW。气象与事件仅提供同期线索，尚未确认根因。'
    if comparisons:
        answer += " 版本比较锁定相同 cutoff 与共同实测样本；日内修正含新增信息，不能直接解释为模型能力提升。"
    if revenues:
        best = max(
            (r for r in revenues if r["net_revenue_yuan"] is not None),
            key=lambda r: r["net_revenue_yuan"],
            default=None,
        )
        if best:
            answer += f' 当前已结算配对范围内，{best["plan_name"]}净收益 {best["net_revenue_yuan"]:.2f} 元，结算 {best["settled_count"]} 个时段；不外推未来收益。'
    answer += " 知识检索命中 " + str(len(knowledge)) + " 个可见切片。"
    if inference:
        comparison = inference["metrics"]["online_comparison"]
        answer += f' 小模型 {inference["model_name"]} 已实时输出 96 点。在 {comparison["sample_count"]} 个共同实测样本上，小模型 MAE {number(comparison["runtime_mae"])} MW；线上版本 MAE {number(comparison["online_mae"])} MW。拟合口径 {inference["trained_scope"]}，历史配对 {inference["training_pair_count"]} 条。'
        if what_if:
            sandbox = inference["sandbox"]
            answer += " 场景参数 " + encoded(inference["overrides"]) + "。"
            answer += (f' 同实测与电价申报沙盘净收益变化 {number(sandbox["delta_net_revenue_yuan"])} 元；考核项变化 {number(sandbox["delta_penalty_yuan"])} 元。' if sandbox.get("status") != "unavailable" else " 收益沙盘不可用：" + sandbox["reason"])
    llm_mode = "deterministic_tools_only"
    provider_error = None
    config = load_settings()
    key = config.api_key if config.enabled else ""
    if key:
        llm_mode = "openai_compatible_evidence_summary"
        facts = [answer] + [r["content_text"] for r in knowledge]
        try:
            selection = select_evidence(config, facts, question, transport=urlopen)
            answer = "\n\n".join(facts[i] for i in selection)
        except ProviderError as exc:
            provider_error = exc.code
            llm_mode = "provider_failed"
            answer = "外部大模型摘要失败；工具与检索证据已保存。请检查模型配置后重试。"
    if mode == "synthetic":
        answer += "\n\n合成演示数据与未训练场景模型；不代表真实生产结果或正式交易建议。"
    if llm_mode == "deterministic_tools_only":
        answer += (
            "\n\n未连接外部大模型，本结论由数据库、规则计算与 RAG 证据确定性组装。"
        )
    created = now()
    run_id = str(uuid4())
    session_id = session_id or str(uuid4())
    snapshot_id = str(uuid4())
    snapshot = {"scope": tool_inputs, "intervals": focus, "source_mode": mode}
    if store.db.execute(
        "SELECT 1 FROM agent_session WHERE session_id=?", (session_id,)
    ).fetchone():
        old = json.loads(
            store.db.execute(
                "SELECT scope_json FROM agent_session WHERE session_id=?", (session_id,)
            ).fetchone()[0]
        )
        if old.get("station_id") != station or old.get("source_mode") != mode:
            raise ValueError("会话场站或数据模式不匹配")
    else:
        store.append(
            "agent_session",
            dict(
                session_id=session_id,
                user_id=user_id,
                scope_json=encoded(scope),
                created_at=created,
            ),
        )
    start, end = day_bounds(day)
    store.append(
        "feature_snapshot",
        dict(
            snapshot_id=snapshot_id,
            task="agent_analysis",
            station_id=station,
            target_start=start,
            target_end=end,
            cutoff_at=cutoff,
            created_at=created,
            feature_version="agent-evidence-v1",
            source_mode=mode,
            payload_json=encoded(snapshot),
            content_hash=digest(snapshot),
        ),
    )
    store.append(
        "agent_run",
        dict(
            agent_run_id=run_id,
            station_id=station,
            snapshot_id=snapshot_id,
            model_name=(
                config.model
                if key
                else "deterministic-tools"
            ),
            prompt_version="grounded-v1",
            question=question,
            status="failed" if provider_error else "complete",
            started_at=created,
            finished_at=created,
            source_mode=mode,
        ),
    )
    for c in calls:
        store.append(
            "agent_tool_call",
            dict(
                tool_call_id=str(uuid4()),
                agent_run_id=run_id,
                tool_name=c["tool_name"],
                tool_version="1",
                input_json=encoded(c["input"]),
                output_json=encoded(c["output"]),
                status="success",
                started_at=c["started_at"],
                finished_at=c["finished_at"],
            ),
        )
    response_id = str(uuid4())
    latency = (time.perf_counter() - started) * 1000
    store.append(
        "agent_response",
        dict(
            response_id=response_id,
            agent_run_id=run_id,
            session_id=session_id,
            answer_markdown=answer,
            citations_json=encoded(citations),
            grounded_check_passed=int(not provider_error),
            llm_mode=llm_mode,
            latency_ms=latency,
            created_at=created,
        ),
    )
    return {
        "response_id": response_id,
        "session_id": session_id,
        "agent_run_id": run_id,
        "answer_markdown": answer,
        "citations": citations,
        "tool_calls": calls,
        "artifacts": artifacts,
        "llm_mode": llm_mode,
        "grounded_check_passed": not provider_error,
        "provider_error": provider_error,
        "latency_ms": latency,
        "scope": tool_inputs,
        "source_mode": mode,
    }


def agent_history(store, station_id, source_mode="synthetic"):
    history = rows(
        store,
        "SELECT a.*,r.question,r.source_mode FROM agent_response a JOIN agent_run r USING(agent_run_id) WHERE r.station_id=? AND r.source_mode=? ORDER BY a.created_at DESC,a.rowid DESC LIMIT 30",
        (station_id, source_mode),
    )
    for entry in history:
        entry["citations"] = json.loads(entry["citations_json"])
        entry["tool_calls"] = [
            {
                "tool_name": c["tool_name"],
                "input": json.loads(c["input_json"]),
                "output": json.loads(c["output_json"]),
            }
            for c in rows(
                store,
                "SELECT * FROM agent_tool_call WHERE agent_run_id=? ORDER BY started_at,rowid",
                (entry["agent_run_id"],),
            )
        ]
        entry["artifacts"] = build_artifacts(entry["tool_calls"])
    return {"history": history}


def build_artifacts(calls):
    """Artifacts are exact views of audited tool outputs; history uses the same path."""
    artifacts = []
    for call in calls:
        name, output = call["tool_name"], call["output"]
        if name in {"invoke_forecast_model", "run_what_if_forecast"}:
            artifacts.append(dict(type="forecast_overlay", tool_name=name, title="场景实时预测" if name == "run_what_if_forecast" else "小模型实时预测", data=output))
            if "sandbox" in output:
                artifacts.append(dict(type="revenue_compare", tool_name=name, title="What-If 同口径收益沙盘", data=output["sandbox"]))
        elif name == "simulate_bidding_revenue":
            artifacts.append(dict(type="revenue_compare", tool_name=name, title="申报方案收益", data=output))
        elif name == "diagnose_deviation":
            artifacts.append(dict(type="deviation_top", tool_name=name, title="重点偏差时段", data=output))
    return artifacts
