"""Append-only human review, knowledge ingestion and model registry transitions."""

import json
from uuid import uuid4
from .storage import encoded, digest
from .serving import rows, now, day_bounds


def model_states(store):
    result = rows(store, "SELECT * FROM model_version ORDER BY model_name,version")
    for model in result:
        event = store.db.execute(
            "SELECT * FROM model_lifecycle_event WHERE model_version_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (model["model_version_id"],),
        ).fetchone()
        model["effective_status"] = event["to_status"] if event else model["status"]
        model["trained"] = bool(
            json.loads(model["parameters_json"]).get("trained", False)
        )
    return result


def review_feedback(store, case_id, reason, training_eligible, reviewer_id="operator"):
    case = store.db.execute(
        "SELECT * FROM deviation_case WHERE case_id=?", (case_id,)
    ).fetchone()
    if not case:
        raise ValueError("偏差归因单不存在")
    if not reason.strip():
        raise ValueError("请填写人工确认的根因")
    prediction = store.db.execute(
        "SELECT prediction_id FROM prediction_value WHERE run_id=? AND target_start=?",
        (case["prediction_run_id"], case["interval_start"]),
    ).fetchone()
    if not prediction:
        raise ValueError("归因单没有可追溯预测输出")
    feedback_id = str(uuid4())
    store.append(
        "review_feedback",
        dict(
            feedback_id=feedback_id,
            prediction_id=prediction[0],
            reviewer_id=reviewer_id,
            feedback_type="deviation_root_cause",
            reason=reason.strip(),
            training_eligible=int(training_eligible),
            status="confirmed",
            created_at=now(),
        ),
    )
    return {
        "feedback_id": feedback_id,
        "case_id": case_id,
        "status": "confirmed",
        "training_eligible": bool(training_eligible),
    }


def ingest_feedback(store, feedback_id):
    feedback = store.db.execute(
        "SELECT * FROM review_feedback WHERE feedback_id=? AND status='confirmed'",
        (feedback_id,),
    ).fetchone()
    if not feedback:
        raise ValueError("仅可沉淀已确认人工反馈")
    case = store.db.execute(
        "SELECT c.* FROM deviation_case c JOIN prediction_value p ON p.run_id=c.prediction_run_id AND p.target_start=c.interval_start WHERE p.prediction_id=?",
        (feedback["prediction_id"],),
    ).fetchone()
    if not case:
        raise ValueError("人工反馈没有对应偏差归因单")
    doc_id = "rsi-feedback-" + feedback_id
    existing = store.db.execute(
        "SELECT doc_id FROM rag_document WHERE doc_id=?", (doc_id,)
    ).fetchone()
    if existing:
        return {
            "doc_id": doc_id,
            "chunk_id": doc_id + "-0",
            "status": "already_ingested",
        }
    content = f'人工确认案例；时段 {case["interval_start"]}；偏差 {case["error_value"]:.4f} MW。根因：{feedback["reason"]}。训练可用性：{bool(feedback["training_eligible"])}。source_mode={case["source_mode"]}。'
    created = now()
    store.append(
        "rag_document",
        dict(
            doc_id=doc_id,
            collection="rsi_case",
            title="人工复核偏差案例 · " + case["interval_start"],
            market_code="DEMO" if case["source_mode"] == "synthetic" else None,
            station_id=case["station_id"],
            effective_from=created,
            source_uri="database://review_feedback/" + feedback_id,
            content_hash=digest(content),
            version="1",
            status="active",
            source_mode=case["source_mode"],
            created_at=created,
        ),
    )
    store.append(
        "rag_chunk",
        dict(
            chunk_id=doc_id + "-0",
            doc_id=doc_id,
            chunk_index=0,
            heading_path="偏差/人工确认/根因",
            content_text=content,
            metadata_json=encoded(
                {
                    "feedback_id": feedback_id,
                    "case_id": case["case_id"],
                    "source_mode": case["source_mode"],
                }
            ),
            token_count=len(content),
            created_at=created,
        ),
    )
    return {"doc_id": doc_id, "chunk_id": doc_id + "-0", "status": "ingested"}


def approve_model(store, candidate_id, action, reason, reviewer_id="operator"):
    candidate = store.db.execute(
        "SELECT * FROM iteration_candidate WHERE candidate_id=?", (candidate_id,)
    ).fetchone()
    if not candidate:
        raise ValueError("候选提案不存在")
    if action not in ("approve", "rollback") or not reason.strip():
        raise ValueError("审批动作或理由无效")
    states = {m["model_version_id"]: m for m in model_states(store)}
    base, cand = (
        candidate["base_model_version_id"],
        candidate["candidate_model_version_id"],
    )
    if not cand or base not in states or cand not in states:
        raise ValueError("候选模型缺失")
    if (
        states[base]["source_mode"] != states[cand]["source_mode"]
        or states[base]["task"] != states[cand]["task"]
    ):
        raise ValueError("候选与基线口径不一致")
    if action == "approve" and states[cand]["effective_status"] not in (
        "candidate",
        "shadow",
        "rolled_back",
    ):
        raise ValueError("仅候选、影子或回滚模型可审批上线")
    if action == "rollback" and states[cand]["effective_status"] != "production":
        raise ValueError("候选尚未上线，不能回滚")
    if action == "approve" and not candidate["evaluation_id"]:
        raise ValueError("候选缺少评估证据")
    decision_id = str(uuid4())
    created = now()
    store.append(
        "approval_decision",
        dict(
            decision_id=decision_id,
            candidate_id=candidate_id,
            reviewer_id=reviewer_id,
            decision=action,
            reason=reason.strip(),
            created_at=created,
        ),
    )
    target = cand if action == "approve" else base
    changes = []
    # One production per model family and task. Retire the previous active version.
    for model in states.values():
        if (
            model["model_name"] == states[target]["model_name"]
            and model["task"] == states[target]["task"]
            and model["source_mode"] == states[target]["source_mode"]
        ):
            new = (
                "production"
                if model["model_version_id"] == target
                else (
                    "rolled_back"
                    if action == "rollback" and model["model_version_id"] == cand
                    else (
                        "archived"
                        if model["effective_status"] == "production"
                        else model["effective_status"]
                    )
                )
            )
            if new != model["effective_status"]:
                record = dict(
                    lifecycle_event_id=str(uuid4()),
                    model_version_id=model["model_version_id"],
                    from_status=model["effective_status"],
                    to_status=new,
                    decision_id=decision_id,
                    operator_id=reviewer_id,
                    reason=reason.strip(),
                    created_at=created,
                )
                store.append("model_lifecycle_event", record)
                changes.append(record)
    from .serving import refresh_serving_tables

    refresh_serving_tables(store)
    return {
        "decision_id": decision_id,
        "action": action,
        "events": changes,
        "source_mode": states[target]["source_mode"],
        "notice": (
            "演示注册状态已持久化；不代表生产模型训练或业务效果验证"
            if states[target]["source_mode"] == "synthetic"
            else "模型注册状态已持久化"
        ),
    }


def rsi_overview(store, station_id, day, source_mode="synthetic"):
    start, end = day_bounds(day)
    cases = rows(
        store,
        "SELECT * FROM deviation_case WHERE station_id=? AND interval_start>=? AND interval_end<=? AND source_mode=? ORDER BY abs(error_value) DESC",
        (station_id, start, end, source_mode),
    )
    for case in cases:
        feedback = store.db.execute(
            "SELECT f.* FROM review_feedback f JOIN prediction_value p USING(prediction_id) WHERE p.run_id=? AND p.target_start=? ORDER BY f.created_at DESC,f.rowid DESC LIMIT 1",
            (case["prediction_run_id"], case["interval_start"]),
        ).fetchone()
        case["feedback"] = dict(feedback) if feedback else None
        case["effective_status"] = "confirmed" if feedback else case["status"]
        case["rag_doc_id"] = (
            "rsi-feedback-" + feedback["feedback_id"]
            if feedback
            and store.db.execute(
                "SELECT 1 FROM rag_document WHERE doc_id=?",
                ("rsi-feedback-" + feedback["feedback_id"],),
            ).fetchone()
            else None
        )
    return {
        "cases": cases,
        "models": [m for m in model_states(store) if m["source_mode"] == source_mode],
        "candidates": rows(
            store,
            "SELECT c.* FROM iteration_candidate c JOIN model_version m ON m.model_version_id=c.candidate_model_version_id WHERE m.source_mode=?",
            (source_mode,),
        ),
        "lifecycle": rows(
            store,
            "SELECT e.* FROM model_lifecycle_event e JOIN model_version m USING(model_version_id) WHERE m.source_mode=? ORDER BY e.created_at DESC,e.rowid DESC",
            (source_mode,),
        ),
        "source_mode": source_mode,
    }
