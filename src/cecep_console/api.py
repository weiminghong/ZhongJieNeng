"""Unified workbench API. SQLite remains the source of all displayed business data."""

from contextlib import asynccontextmanager
from datetime import date as Date
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .storage import Store, CATALOG, instant
from . import storage_api
from .serving import (
    rows,
    data_clock,
    build_intervals,
    daily_kpi,
    compare_versions,
    metrics,
)
from .rsi import (
    rsi_overview,
    review_feedback,
    ingest_feedback,
    approve_model,
    model_states,
)
from .trading import trading_overview
from .agent_service import query_agent, agent_history


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_id: str = Field(default="lanneng", min_length=1, max_length=100)
    date: str = "2026-11-20"
    mode: Literal["live", "post", "replay"] = "live"
    cutoff_at: str | None = None
    source_mode: Literal["synthetic", "production"] = "synthetic"
    selected_interval: str | None = None

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        Date.fromisoformat(value)
        return value

    @field_validator("cutoff_at", "selected_interval")
    @classmethod
    def valid_time(cls, value):
        return instant(value) if value else None


class AgentQuery(Scope):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    reason: str = Field(min_length=1, max_length=4000)
    training_eligible: bool
    reviewer_id: str = Field(default="operator", min_length=1, max_length=100)


class Ingest(BaseModel):
    feedback_id: str


class Approval(BaseModel):
    candidate_id: str
    action: Literal["approve", "rollback"]
    reason: str = Field(min_length=1, max_length=4000)
    reviewer_id: str = "operator"


def get_store():
    with Store() as store:
        yield store


def resolve_scope(scope, store):
    if scope.mode == "replay" and not scope.cutoff_at:
        raise ValueError("时点回放必须指定含时区的 cutoff_at")
    return (
        scope.cutoff_at
        if scope.mode == "replay"
        else data_clock(store, scope.source_mode)
    )


def overview(store, scope):
    cutoff = resolve_scope(scope, store)
    if scope.mode == "replay":
        intervals = build_intervals(
            store,
            scope.station_id,
            scope.date,
            cutoff,
            scope.source_mode,
            registry_cutoff=cutoff,
        )
        kpi = daily_kpi(intervals, cutoff)
        path = "pit_engine: Store.as_of + Store.predictions"
    else:
        intervals = rows(
            store,
            "SELECT * FROM serving_interval_wide WHERE station_id=? AND trading_date=? AND source_mode=? ORDER BY interval_start",
            (scope.station_id, scope.date, scope.source_mode),
        )
        result = store.db.execute(
            "SELECT * FROM serving_daily_kpi WHERE station_id=? AND trading_date=? AND scope='all' AND source_mode=?",
            (scope.station_id, scope.date, scope.source_mode),
        ).fetchone()
        kpi = dict(result) if result else None
        path = "serving_interval_wide + serving_daily_kpi"
    return {
        "intervals": intervals,
        "kpi": kpi,
        "query_path": path,
        "cutoff_at": cutoff,
        "scope": scope.model_dump(),
        "source_mode": scope.source_mode,
        "warning": (
            "合成演示数据 · 模型未经真实训练"
            if scope.source_mode == "synthetic"
            else None
        ),
    }


def create_app():
    @asynccontextmanager
    async def lifespan(app):
        with Store() as store:
            store.initialize()
        yield

    app = FastAPI(title="中节能光伏交易工作台", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(ValueError)
    async def bad_input(request, exc):
        return JSONResponse(
            status_code=400, content={"error": str(exc), "type": "contract_error"}
        )

    @app.exception_handler(sqlite3.IntegrityError)
    async def invalid_state(request, exc):
        return JSONResponse(
            status_code=409, content={"error": str(exc), "type": "database_constraint"}
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "cecep-workbench-v1"}

    @app.get("/api/storage/{endpoint}")
    def legacy(endpoint: str, request: Request):
        if endpoint not in ("health", "query", "features", "predictions"):
            raise HTTPException(404, "unknown storage endpoint")
        query = {k: request.query_params.getlist(k) for k in request.query_params}
        return storage_api.response("/api/storage/" + endpoint, query)

    @app.get("/api/v1/workbench/bootstrap")
    def bootstrap(store: Store = Depends(get_store)):
        stations = rows(
            store,
            "SELECT s.station_id,s.station_name,s.latitude,s.longitude,c.capacity_ac_mw FROM station s JOIN station_config_version c USING(station_id) WHERE c.revision_no=(SELECT max(revision_no) FROM station_config_version c2 WHERE c2.station_id=s.station_id) ORDER BY s.station_id",
        )
        return {
            "stations": stations,
            "dates": [
                r[0]
                for r in store.db.execute(
                    "SELECT DISTINCT trading_date FROM serving_interval_wide ORDER BY trading_date"
                )
            ],
            "modes": ["live", "replay", "post"],
            "source_modes": [
                r[0]
                for r in store.db.execute(
                    "SELECT DISTINCT source_mode FROM serving_interval_wide"
                )
            ],
            "default_date": "2026-11-20",
            "data_clock": data_clock(store),
            "models": model_states(store),
            "timezone": "Asia/Shanghai",
            "interval_minutes": 15,
            "llm_mode": (
                "openai_compatible_evidence_summary"
                if os.environ.get("CECEP_LLM_API_KEY")
                else "deterministic_tools_only"
            ),
            "evidently": {
                "report_url": os.environ.get(
                    "CECEP_EVIDENTLY_URL", "http://10.21.179.91:8502"
                ),
                "status": "external_report_link_unverified",
                "notice": "漂移告警为合成示例；报告服务可用性需独立核验",
            },
            "data_contract": {
                "power": "MW",
                "energy": "MWh",
                "price": "元/MWh",
                "spread": "RT − DA",
                "error": "实测 − 预测（偏差归因单）",
                "source_notice": "所有 synthetic 数据、演示模型及示例规则均不代表真实生产结果",
            },
        }

    @app.get("/api/v1/workbench/overview")
    def get_overview(scope: Scope = Depends(), store: Store = Depends(get_store)):
        return overview(store, scope)

    @app.get("/api/v1/workbench/raw")
    def raw(
        scope: Scope = Depends(),
        search: str = "",
        quality: str = "all",
        store: Store = Depends(get_store),
    ):
        data = overview(store, scope)
        data["intervals"] = [
            r
            for r in data["intervals"]
            if (quality == "all" or r["quality_flag"] == quality)
            and (
                not search
                or search.lower() in json.dumps(r, ensure_ascii=False).lower()
            )
        ]
        data["drift"] = rows(
            store,
            "SELECT * FROM drift_check_run WHERE station_id=? AND source_mode=? AND created_at<=? ORDER BY created_at DESC LIMIT 1",
            (scope.station_id, scope.source_mode, data["cutoff_at"]),
        )
        return data

    @app.get("/api/v1/workbench/lineage")
    def lineage(
        interval_start: str, scope: Scope = Depends(), store: Store = Depends(get_store)
    ):
        data = overview(store, scope)
        selected = next(
            (
                r
                for r in data["intervals"]
                if r["interval_start"] == instant(interval_start)
            ),
            None,
        )
        if not selected:
            raise HTTPException(404, "当前范围没有该时段")
        evidence = []
        for ref in json.loads(selected["lineage_refs_json"]):
            table = ref["table"]
            if table not in CATALOG:
                raise ValueError("血缘表不在允许列表")
            record = store.db.execute(
                f'SELECT * FROM {table} WHERE {CATALOG[table]["pk"]}=?',
                (ref["record_id"],),
            ).fetchone()
            item = {
                "reference": ref,
                "record": dict(record) if record else None,
                "available_before_cutoff": ref["available_at"] <= data["cutoff_at"],
            }
            if table == "prediction_value" and record:
                run = store.db.execute(
                    "SELECT * FROM prediction_run WHERE run_id=?", (record["run_id"],)
                ).fetchone()
                item["prediction_run"] = dict(run)
                item["feature_inputs"] = rows(
                    store,
                    "SELECT table_name,record_id,available_at,record_hash FROM feature_input WHERE snapshot_id=? ORDER BY table_name,record_id",
                    (run["snapshot_id"],),
                )
            evidence.append(item)
        return {
            "interval": selected,
            "cutoff_at": data["cutoff_at"],
            "query_path": data["query_path"],
            "evidence": evidence,
        }

    @app.get("/api/v1/workbench/compare")
    def compare(scope: Scope = Depends(), store: Store = Depends(get_store)):
        cutoff = resolve_scope(scope, store)
        if scope.mode == "replay":
            comparisons = compare_versions(
                store, scope.station_id, scope.date, cutoff, scope.source_mode
            )
            path = "pit_engine"
        else:
            cache = rows(
                store,
                "SELECT metrics_b_json FROM serving_version_compare WHERE station_id=? AND date_start=? AND source_mode=? ORDER BY compare_key",
                (scope.station_id, scope.date, scope.source_mode),
            )
            comparisons = [json.loads(r["metrics_b_json"]) for r in cache]
            path = "serving_version_compare"
        intervals = overview(store, scope)["intervals"]
        paired = [
            r
            for r in intervals
            if r["actual_mw"] is not None
            and r["id_corrected_mw"] is not None
            and r["da_forecast_mw"] is not None
        ]
        return {
            "versions": comparisons,
            "query_path": path,
            "cutoff_at": cutoff,
            "intraday": {
                "comparison_basis": "日内新增信息 · 相同配对实测时段",
                "day_ahead": metrics(
                    [r["actual_mw"] for r in paired],
                    [r["da_forecast_mw"] for r in paired],
                ),
                "corrected": metrics(
                    [r["actual_mw"] for r in paired],
                    [r["id_corrected_mw"] for r in paired],
                ),
            },
        }

    @app.get("/api/v1/workbench/trading")
    def trading(scope: Scope = Depends(), store: Store = Depends(get_store)):
        return trading_overview(
            store,
            scope.station_id,
            scope.date,
            scope.source_mode,
            resolve_scope(scope, store),
        )

    @app.post("/api/v1/workbench/trading/recalculate")
    def recalculate(scope: Scope, store: Store = Depends(get_store)):
        from .serving import refresh_serving_tables

        with store.db:
            result = trading_overview(
                store,
                scope.station_id,
                scope.date,
                scope.source_mode,
                resolve_scope(scope, store),
                persist=True,
            )
            refresh_serving_tables(store, scope.station_id)
        return result

    @app.get("/api/v1/workbench/rsi")
    def rsi(scope: Scope = Depends(), store: Store = Depends(get_store)):
        return rsi_overview(
            store,
            scope.station_id,
            scope.date,
            scope.source_mode,
            cutoff=resolve_scope(scope, store) if scope.mode == "replay" else None,
        )

    @app.post("/api/v1/rsi/feedback")
    def feedback(body: Feedback, store: Store = Depends(get_store)):
        with store.db:
            return review_feedback(store, **body.model_dump())

    @app.post("/api/v1/rsi/rag-ingest")
    def ingest(body: Ingest, store: Store = Depends(get_store)):
        with store.db:
            return ingest_feedback(store, body.feedback_id)

    @app.post("/api/v1/rsi/approve")
    def approve(body: Approval, store: Store = Depends(get_store)):
        with store.db:
            return approve_model(store, **body.model_dump())

    @app.post("/api/v1/agent/query")
    def agent(body: AgentQuery, store: Store = Depends(get_store)):
        scope = Scope(**body.model_dump(exclude={"question", "session_id"}))
        scope.cutoff_at = resolve_scope(scope, store)
        with store.db:
            result = query_agent(
                store, body.question, scope.model_dump(), session_id=body.session_id
            )
        return JSONResponse(
            status_code=502 if result["provider_error"] else 200, content=result
        )

    @app.get("/api/v1/agent/history")
    def history(
        station_id: str = "lanneng",
        source_mode: Literal["synthetic", "production"] = "synthetic",
        store: Store = Depends(get_store),
    ):
        return agent_history(store, station_id, source_mode)

    dist = Path(__file__).resolve().parents[2] / "apps/web/dist"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        target = (dist / path).resolve()
        if not target.is_relative_to(dist.resolve()):
            raise HTTPException(404, "资源不存在")
        if target.is_file():
            return FileResponse(target)
        if Path(path).suffix:
            raise HTTPException(404, "静态资源不存在")
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        raise HTTPException(503, "前端未构建，请运行 npm --prefix apps/web run build")

    return app


app = create_app()
