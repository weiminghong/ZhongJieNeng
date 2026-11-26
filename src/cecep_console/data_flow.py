"""Immutable snapshots of our configured source and append-only label matching.

Archiving records today's ingestion, never a fabricated historical arrival time.
Observation updates do not overwrite predictions or frozen evaluation protocols.
"""
import hashlib
import json
import os
import shutil

import numpy as np

from . import learning as ml, public_data
from .storage import digest


def revision_id(source_hash):
    return "source_"+source_hash


def archive_current(store, expected_hash=None):
    meta, _, _ = public_data.dataset()
    sha = meta["source_hash"]
    if expected_hash and expected_hash != sha:
        raise ValueError("归档前源文件已变化，请重新读取版本")
    oid = revision_id(sha)
    store.db.execute("BEGIN IMMEDIATE")
    try:
        old = store.db.execute("SELECT 1 FROM ml_object WHERE object_id=?", (oid,)).fetchone()
        if old:
            revision = ml.get_object(store, oid, "source_revision")
            ref = revision["payload"]["archive"]
            if ml.checksum(ml.file_path(ref["path"])) != sha:
                raise ValueError("源数据归档校验失败，不能继续使用")
            store.db.commit(); return revision
        if shutil.disk_usage(ml.root()).free < meta["bytes"]*3+64*1024**2:
            raise ValueError("归档磁盘空间不足，未更改已有记录")
        raw = public_data.source_path().read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("读取期间源文件变化，未登记归档")
        relative = f"sources/{sha}.csv"
        path = ml.file_path(relative)
        if path.exists():
            if ml.checksum(path) != sha:
                raise ValueError("已有归档内容与版本哈希不符")
            ref = dict(path=relative, sha256=sha, bytes=path.stat().st_size)
        else:
            ref = ml.atomic(relative, raw)
        previous = store.db.execute("SELECT object_id FROM ml_object WHERE kind='source_revision' ORDER BY rowid DESC LIMIT 1").fetchone()
        ml.add_object(store, "source_revision", dict(metadata=meta, archive=ref, ingested_at=ml.now(),
                      original_path=str(public_data.source_path()), source_mode="synthetic" if os.environ.get("CECEP_ML_TEST_FIXTURE")=="1" else "public_reference",
                      time_policy="historical_assumed", historical_arrival_verified=False,
                      note="当前系统归档时间，不是历史发布时间；原文件只读，版本按字节哈希固定"), sha,
                      previous[0] if previous else None, oid)
        ml.event(store, oid, "archived", source_hash=sha, rows=meta["row_count"], bytes=ref["bytes"])
        store.db.commit(); return ml.get_object(store, oid)
    except Exception:
        store.db.rollback(); raise


def source_version(store, source_hash):
    # Prefer the immutable revision whenever available, even for current input.
    old = store.db.execute("SELECT object_id FROM ml_object WHERE object_id=?", (revision_id(source_hash),)).fetchone()
    if old:
        revision = ml.get_object(store, old[0], "source_revision")
        ref = revision["payload"]["archive"]; path = ml.file_path(ref["path"])
        if ml.checksum(path) != source_hash:
            raise ValueError("原始数据归档校验失败")
        stat = path.stat()
        meta, dates, days = public_data._load(str(path), stat.st_mtime_ns, stat.st_size)
        return dict(meta, source_file=revision["payload"]["metadata"]["source_file"], archived_version=True), dates, days
    result = public_data.dataset()
    if result[0]["source_hash"] != source_hash:
        raise ValueError("该旧源版本尚未归档，不能用新文件替代旧输入")
    return result


def reconcile(store, source_hash):
    """Match date+slot in our source. Preserve each original prediction snapshot."""
    meta, _, days = source_version(store, source_hash)
    added = 0
    records = store.db.execute("SELECT object_id,payload_json,source_hash FROM ml_object WHERE kind='prediction' ORDER BY rowid").fetchall()
    for row in records:
        oid, p, input_sha = row[0], json.loads(row[1]), row[2]
        match_id = "observation_"+digest(dict(prediction_id=oid, observation_source_hash=source_hash))[:32]
        if store.db.execute("SELECT 1 FROM ml_object WHERE object_id=?", (match_id,)).fetchone() or p["date"] not in days:
            continue
        points = []
        for saved in p["points"]:
            observed = days[p["date"]].get(saved["slot"])
            from .task_catalog import target
            points.append(dict(slot=saved["slot"], predicted=saved["predicted"], actual=target(p["task"],days[p["date"]],saved["slot"]),
                               source_line=observed["source_line"] if observed else None,
                               snapshot_actual=saved["actual"], snapshot_source_line=saved["source_line"]))
        paired = [v for v in points if v["actual"] is not None]
        scores = ml.scores(np.array([v["actual"] for v in paired]), np.array([v["predicted"] for v in paired]))
        changed = sum(v["snapshot_actual"] != v["actual"] for v in points)
        previous = latest_observation(store, oid)
        payload = dict(prediction_id=oid, model_id=p["model_id"], date=p["date"], unit=p["unit"], points=points,
                       scores=scores, snapshot_scores=p["scores"], input_source_hash=input_sha,
                       observation_source_hash=source_hash, source_revision_id=revision_id(source_hash),
                       observed_points=len(paired), changed_from_snapshot=changed,
                       previous_observation_id=previous["id"] if previous else None,
                       paired_mask_hash=digest([v["slot"] for v in paired]), checked_at=ml.now(),
                       evaluation_kind="observations_matched_to_saved_prediction_v1", time_policy="historical_assumed",
                       notice="按交易日与15分钟时段匹配，仅追加核对记录；不改写原始预测，不并入冻结模型评估，不自动训练")
        ml.add_object(store, "observation_match", payload, source_hash, oid, match_id)
        ml.event(store, match_id, "matched", prediction_id=oid, observed_points=len(paired), changed_points=changed)
        store.db.commit(); added += 1
    return added


def latest_observation(store, prediction_id):
    row = store.db.execute("SELECT observation_id FROM ml_observations WHERE prediction_id=? ORDER BY created_at DESC,observation_id DESC LIMIT 1", (prediction_id,)).fetchone()
    return ml.get_object(store, row[0], "observation_match") if row else None


def flow(store, model_id=None, prediction_id=None):
    catalog = public_data.catalog()
    pred = ml.get_object(store, prediction_id, "prediction") if prediction_id else None
    if pred:
        if model_id and model_id != pred["payload"]["model_id"]:
            raise ValueError("模型与预测记录不属于同一条数据链")
        model_id = pred["payload"]["model_id"]
    model_id = model_id or ml.active(store)["detail"].get("model_id")
    model = ml.get_object(store, model_id, "model") if model_id else None
    if model and not pred:
        row = store.db.execute("SELECT object_id FROM ml_object WHERE kind='prediction' AND json_extract(payload_json,'$.model_id')=? ORDER BY rowid DESC LIMIT 1", (model_id,)).fetchone()
        pred = ml.get_object(store, row[0], "prediction") if row else None
    ds = ml.get_object(store, model["payload"]["dataset_id"], "dataset") if model else None
    job = ml.job(store, model["payload"]["job_id"]) if model else None
    train_sha = model["source_hash"] if model else (catalog.get("metadata") or {}).get("source_hash")
    archives = ml.objects(store, "source_revision", 50)
    archive_row = store.db.execute("SELECT object_id FROM ml_object WHERE object_id=?",(revision_id(train_sha),)).fetchone() if train_sha else None
    archive = ml.get_object(store, archive_row[0], "source_revision") if archive_row else None
    if archive and ml.checksum(ml.file_path(archive["payload"]["archive"]["path"])) != train_sha:
        raise ValueError("原始归档校验失败，数据链不能标为就绪")
    matched = latest_observation(store, pred["id"]) if pred else None
    feedback = [f for f in ml.objects(store, "feedback") if pred and f["parent_id"] == pred["id"]]
    proposals = [p for p in ml.objects(store, "proposal") if p["payload"]["feedback_id"] in {f["id"] for f in feedback}]
    versions = [dict(id=a["id"], display_name=a["display_name"], source_hash=a["source_hash"], rows=a["payload"]["metadata"]["row_count"],
                     date_start=a["payload"]["metadata"]["date_start"], date_end=a["payload"]["metadata"]["date_end"],
                     bytes=a["payload"]["archive"]["bytes"], ingested_at=a["payload"]["ingested_at"]) for a in archives]
    return dict(current_source=catalog, monitor=ml.state(store, "monitor"), model=model, dataset=ds, job=job,
                archive=archive, prediction=pred, observation=matched, feedback=feedback, proposals=proposals,
                versions=versions, checked_at=ml.now(), time_policy="historical_assumed",
                source_policy="只使用本项目配置的既有数据源；参考软件未提供业务数值。")
