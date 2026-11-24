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
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from urllib.parse import urlsplit
from .model_settings import (
    public_settings,
    save_settings,
    test_connection,
    ProviderError,
)
from .storage import Store, CATALOG, instant
from . import storage_api
from .serving import (
    rows,
    data_clock,
    build_intervals,
    daily_kpi,
    compare_versions,
    metrics,
    power_metrics,
)
from .workbench_analytics import multi_day, trading_sandbox
from .rsi import (
    rsi_overview,
    review_feedback,
    ingest_feedback,
    approve_model,
    model_states,
)
from .trading import trading_overview
from .agent_service import query_agent, agent_history
from .model_runtime import list_runtime_models, register_runtime_model, run_model_inference
from .proactive import run_proactive_analysis, latest_proactive_briefs
from .serving import now
from .readiness import connection_readiness, available_dates


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


class SandboxInput(Scope):
    plan_id: str | None = None
    bid_multiplier: float = Field(default=1.0, ge=0.7, le=1.3, allow_inf_nan=False)
    exempt_fraction: float = Field(default=0.05, ge=0.01, le=0.15, allow_inf_nan=False)
    penalty_yuan_mwh: float | None = Field(
        default=None, ge=0.0, le=500.0, allow_inf_nan=False
    )


class ModelSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=2000)
    model: str | None = Field(default=None, max_length=200)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    timeout_seconds: int | None = Field(default=None, ge=5, le=120)
    max_output_tokens: int | None = Field(default=None, ge=128, le=4096)


class RuntimeRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    task: str = "day_ahead_power"
    artifact_uri: str = Field(min_length=1, max_length=2000)
    artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_mode: Literal["synthetic", "production"] = "synthetic"
    params_json: dict = Field(default_factory=dict)


class RuntimePrediction(Scope):
    model_version_id: str | None = None
    overrides: dict | None = None
    persist: bool = False


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
    # Each request owns its connection. FastAPI may resume/close it on a different
    # worker thread; no connection is shared between concurrent requests.
    with Store(check_same_thread=False) as store:
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
        if kpi is not None:
            m = power_metrics(intervals)
            kpi.update(
                {
                    k: m[k]
                    for k in (
                        "mbe",
                        "skill_score",
                        "interval_coverage_pct",
                        "direction_breakdown",
                    )
                }
            )
            kpi["mbe_mw"] = m["mbe"]
        path = "serving_interval_wide + serving_daily_kpi"
        if not intervals and scope.date in available_dates(store, scope.station_id, scope.source_mode):
            intervals = build_intervals(store, scope.station_id, scope.date, cutoff, scope.source_mode, registry_cutoff=cutoff)
            kpi = daily_kpi(intervals, cutoff)
            path = "pit_engine: 尚无预聚合记录，按原始到达证据查询"
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

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        if request.url.path.startswith("/api/v1/settings/") or request.url.path == "/api/v1/models/register":
            # Validation errors must never echo a submitted credential or body.
            return JSONResponse(
                status_code=422, content={"error": "配置项格式或范围无效，请检查表单"}
            )
        return await request_validation_exception_handler(request, exc)

    def settings_origin(request):
        origin = request.headers.get("origin")
        if request.headers.get("x-cecep-settings") != "1" or (
            origin and urlsplit(origin).netloc != request.headers.get("host")
        ):
            raise HTTPException(403, "请从本站模型配置页面操作")

    @app.get("/api/v1/settings/llm")
    def get_model_settings():
        return JSONResponse(public_settings(), headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/settings/llm")
    def update_model_settings(body: ModelSettingsInput, request: Request):
        settings_origin(request)
        changes = body.model_dump(exclude_none=True)
        if body.api_key is not None:
            changes["api_key"] = body.api_key.get_secret_value()
        return JSONResponse(
            save_settings(changes), headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/v1/settings/llm/test")
    def check_model_connection(request: Request):
        settings_origin(request)
        try:
            result = test_connection()
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except ProviderError as exc:
            return JSONResponse(
                status_code=502,
                content={
                    "status": "failed",
                    "error": "模型连接或证据约束测试失败",
                    "code": exc.code,
                },
                headers={"Cache-Control": "no-store"},
            )

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

    @app.get("/api/v1/models/runtime")
    def runtime_models(store: Store = Depends(get_store)):
        return {"models": list_runtime_models(store)}

    @app.post("/api/v1/models/register")
    def register_model(body: RuntimeRegistration, request: Request, store: Store = Depends(get_store)):
        settings_origin(request)
        return register_runtime_model(store, body.model_dump())

    @app.post("/api/v1/models/predict")
    def predict_model(body: RuntimePrediction, store: Store = Depends(get_store)):
        scope = Scope(**body.model_dump(exclude={"model_version_id", "overrides", "persist"}))
        return run_model_inference(store, model_version_id=body.model_version_id, station_id=scope.station_id,
                                   trading_date=scope.date, cutoff_at=resolve_scope(scope, store), source_mode=scope.source_mode,
                                   overrides=body.overrides, persist=body.persist,
                                   registry_cutoff=resolve_scope(scope, store) if scope.mode == "replay" else now())

    @app.get("/api/v1/agent/proactive")
    def proactive_briefs(scope: Scope = Depends(), store: Store = Depends(get_store)):
        cutoff = resolve_scope(scope, store) if scope.mode == "replay" else now()
        return {"briefs": latest_proactive_briefs(store, scope.station_id, scope.date, scope.source_mode, cutoff)}

    @app.post("/api/v1/agent/proactive/run")
    def proactive_run(scope: Scope, store: Store = Depends(get_store)):
        return run_proactive_analysis(store, {**scope.model_dump(), "cutoff_at": resolve_scope(scope, store)})

    @app.get("/api/storage/{endpoint}")
    def legacy(endpoint: str, request: Request):
        if endpoint not in ("health", "query", "features", "predictions"):
            raise HTTPException(404, "unknown storage endpoint")
        query = {k: request.query_params.getlist(k) for k in request.query_params}
        return storage_api.response("/api/storage/" + endpoint, query)

    @app.get("/api/v1/workbench/bootstrap")
    def bootstrap(station_id: str | None = None, source_mode: Literal["synthetic", "production"] = "synthetic", store: Store = Depends(get_store)):
        stations = rows(
            store,
            "SELECT s.station_id,s.station_name,s.latitude,s.longitude,c.capacity_ac_mw FROM station s JOIN station_config_version c USING(station_id) WHERE c.revision_no=(SELECT max(revision_no) FROM station_config_version c2 WHERE c2.station_id=s.station_id) ORDER BY s.station_id",
        )
        return {
            "stations": stations,
            "dates": available_dates(store, station_id, source_mode),
            "modes": ["live", "replay", "post"],
            "source_modes": [
                r[0]
                for r in store.db.execute(
                    "SELECT DISTINCT source_mode FROM serving_interval_wide"
                )
            ],
            "default_date": "2026-11-20",
            "data_clock": data_clock(store, source_mode),
            "models": model_states(store),
            "timezone": "Asia/Shanghai",
            "interval_minutes": 15,
            "llm_mode": public_settings()["llm_mode"],
            "llm_model": public_settings()["model"],
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

    @app.get("/api/v1/workbench/readiness")
    def readiness_status(station_id: str = "lanneng", source_mode: Literal["synthetic", "production"] = "synthetic", store: Store = Depends(get_store)):
        return connection_readiness(store, station_id, source_mode)

    @app.get("/api/v1/workbench/overview")
    def get_overview(scope: Scope = Depends(), store: Store = Depends(get_store)):
        return overview(store, scope)

    @app.get("/api/v1/workbench/multi-day")
    def get_multi_day(scope: Scope = Depends(), store: Store = Depends(get_store)):
        return multi_day(store, scope, resolve_scope(scope, store))

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
        # Enrich older serving JSON without requiring migration or a cache rebuild.
        interval_map = {r["interval_start"]: r for r in intervals}
        for version in comparisons:
            points = rows(
                store,
                "SELECT p.* FROM prediction_value p JOIN prediction_run r USING(run_id) WHERE p.run_id=? AND r.available_at<=? ORDER BY p.target_start",
                (version["run_id"], cutoff),
            )
            mask = set(version["matched_intervals"])
            matched = [
                {
                    **interval_map[p["target_start"]],
                    "da_forecast_mw": p["value"],
                    "lower_mw": p["lower_value"],
                    "upper_mw": p["upper_value"],
                }
                for p in points
                if p["target_start"] in mask and p["target_start"] in interval_map
            ]
            version.update(power_metrics(matched))
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

    @app.post("/api/v1/workbench/trading/sandbox")
    def sandbox(body: SandboxInput, store: Store = Depends(get_store)):
        scope = Scope(
            **body.model_dump(
                exclude={
                    "plan_id",
                    "bid_multiplier",
                    "exempt_fraction",
                    "penalty_yuan_mwh",
                }
            )
        )
        data = overview(store, scope)
        return trading_sandbox(store, body, data["cutoff_at"], data["intervals"])

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
        if path in {"settings", "settings/"}:
            if (dist / "settings.html").is_file():
                return FileResponse(dist / "settings.html")
            raise HTTPException(503, "模型配置页面尚未构建")
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
