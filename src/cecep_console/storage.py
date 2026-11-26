"""Versioned SQLite storage and point-in-time evidence queries. UTC internally."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

BASE = Path(__file__).resolve().parent
CATALOG = json.loads((BASE / "storage_catalog.json").read_text())
TASKS = (
    "day_ahead_power",
    "intraday_power",
    "day_ahead_price",
    "prebid_spread",
    "intraday_spread",
)
DEFAULT_DB = BASE.parents[1] / "runtime/data/cecep.sqlite3"
REGISTRY_TABLES = {"ml_source_registry","ml_dataset_registry","ml_model_registry","ml_prediction_registry","ml_observation_registry","ml_feedback_registry","ml_retrain_registry","ml_audit_registry"}
REGISTRY_TABLES |= {name+"_v2" for name in REGISTRY_TABLES if name not in {"ml_source_registry","ml_dataset_registry"}}
REGISTRY_TABLES.add("ml_business_scenario")
REGISTRY_TABLES |= {"ml_"+name+"_registry_v3" for name in ("model","prediction","observation","feedback","retrain","audit")}
REGISTRY_TABLES |= {"ml_optimization_origin", "ml_business_scenario_v3"}
UPPER_TABLES = {
    "training_dataset_version",
    "drift_check_run",
    "model_lifecycle_event",
    "contract_position",
    "bidding_plan",
    "bidding_plan_item",
    "rag_document",
    "rag_chunk",
    "agent_session",
    "agent_response",
    "deviation_case",
    "agent_proactive_brief",
    "public_reference_run",
    "ml_object",
    "ml_job",
    "ml_event",
}


def instant(value):
    """Reject naive times instead of guessing the timezone of real data."""
    dt = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return (
        dt.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def is_instant(field):
    return field.endswith("_at") or field in {
        "effective_from",
        "effective_to",
        "effective_start",
        "effective_end",
        "target_start",
        "target_end",
        "interval_start",
        "interval_end",
        "period_start",
        "period_end",
        "requested_start",
        "requested_end",
        "training_start",
        "training_end",
    }


def encoded(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(payload):
    return hashlib.sha256(encoded(payload).encode()).hexdigest()


class Store:
    def __init__(self, path=None, *, readonly=False, check_same_thread=True):
        self.path = (
            Path(path or os.environ.get("CECEP_DB_PATH", DEFAULT_DB))
            .expanduser()
            .resolve()
        )
        if not readonly:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = (
            sqlite3.connect(
                self.path.as_uri() + "?mode=ro",
                uri=True,
                timeout=15,
                check_same_thread=check_same_thread,
            )
            if readonly
            else sqlite3.connect(
                self.path, timeout=15, check_same_thread=check_same_thread
            )
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=15000")
        if not readonly:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.db.close()

    def initialize(self):
        migrations = []
        for path in sorted((BASE / "storage_sql").glob("[0-9][0-9][0-9]_*.sql")):
            script = path.read_text(encoding="utf-8")
            migrations.append(
                (
                    int(path.name.split("_")[0]),
                    script,
                    hashlib.sha256(script.encode()).hexdigest(),
                )
            )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            exists = self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='schema_migration'"
            ).fetchone()
            if exists:
                rows = self.db.execute(
                    "SELECT version,checksum FROM schema_migration"
                ).fetchall()
                known = {version: checksum for version, _, checksum in migrations}
                if any(known.get(r["version"]) != r["checksum"] for r in rows):
                    raise ValueError(
                        "unsupported schema version or migration checksum changed"
                    )
                applied = {r["version"] for r in rows}
                if applied != set(range(1, max(applied, default=0) + 1)):
                    raise ValueError("migration sequence has gaps")
            elif self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone():
                raise ValueError(
                    "refusing to initialize an unrecognized nonempty database"
                )
            else:
                self.db.execute(
                    "CREATE TABLE schema_migration(version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)"
                )
                applied = set()
            for version, script, checksum in migrations:
                if version in applied:
                    continue
                statement = ""
                for line in script.splitlines(True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        self.db.execute(statement)
                        statement = ""
                if statement.strip():
                    raise ValueError("incomplete migration SQL")
                self.db.execute(
                    "INSERT INTO schema_migration VALUES(?,?,?)",
                    (version, checksum, instant(datetime.now(timezone.utc))),
                )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def append(self, table, row):
        if table in UPPER_TABLES:
            fields = self.db.execute(f"PRAGMA table_info({table})").fetchall()
            spec = {r["name"] for r in fields}
            pk = next(r["name"] for r in fields if r["pk"])
            if not row or not set(row) <= spec or pk not in row:
                raise ValueError("unknown or empty record fields")
            record = {
                k: instant(v) if v is not None and is_instant(k) else v
                for k, v in row.items()
            }
            encoded(record)
            old = self.db.execute(
                f"SELECT * FROM {table} WHERE {pk}=?", (record[pk],)
            ).fetchone()
            if old:
                if any(old[k] != v for k, v in record.items()):
                    raise ValueError("conflicting immutable record")
                return False
            self.db.execute(
                f"INSERT INTO {table} ({','.join(record)}) VALUES ({','.join('?' for _ in record)})",
                list(record.values()),
            )
            return True
        if table not in CATALOG:
            raise ValueError("unknown storage table")
        allowed = set(CATALOG[table]["fields"]) | {CATALOG[table]["pk"]}
        if not row or not set(row) <= allowed:
            raise ValueError("unknown or empty record fields")
        record = {
            k: instant(v) if v is not None and is_instant(k) else v
            for k, v in row.items()
        }
        encoded(record)  # reject NaN/Infinity before SQLite coercion
        if (
            table == "feature_snapshot"
            and digest(json.loads(record["payload_json"])) != record["content_hash"]
        ):
            raise ValueError("snapshot hash mismatch")
        if table == "feature_input":
            source_table = record["table_name"]
            if source_table not in CATALOG:
                raise ValueError("unknown evidence table")
            original = self.db.execute(
                f'SELECT * FROM {source_table} WHERE {CATALOG[source_table]["pk"]}=?',
                (record["record_id"],),
            ).fetchone()
            if (
                original is None
                or dict(original) != json.loads(record["payload_json"])
                or digest(dict(original)) != record["record_hash"]
                or original["available_at"] != record["available_at"]
            ):
                raise ValueError("feature input does not match immutable source record")
        # No ignore/replace: malformed rows and conflicting duplicate IDs must fail.
        old = self.db.execute(
            f'SELECT * FROM {table} WHERE {CATALOG[table]["pk"]}=?',
            (record[CATALOG[table]["pk"]],),
        ).fetchone()
        if old:
            if any(old[k] != v for k, v in record.items()):
                raise ValueError("conflicting immutable record")
            return False
        columns = list(record)
        self.db.execute(
            f"INSERT INTO {table}("
            + ",".join(columns)
            + ") VALUES("
            + ",".join("?" for _ in columns)
            + ")",
            [record[k] for k in columns],
        )
        return True

    def ingest(self, payload):
        """Atomic batch; source and ingestion_batch must precede dependent records."""
        count = 0
        with self.db:
            for table, rows in payload.items():
                for row in rows:
                    count += self.append(table, row)
            if (
                count
                and self.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='serving_interval_wide'"
                ).fetchone()
            ):
                from .serving import refresh_serving_tables

                refresh_serving_tables(self)
        return count

    def as_of(
        self,
        table,
        cutoff,
        *,
        filters=None,
        start=None,
        end=None,
        target=None,
        allow_synthetic=False,
        limit=10000,
    ):
        """Latest visible revision per business key; never collapse independent sources.

        Effective validity and status are applied AFTER revision selection, so an
        obsolete earlier revision cannot be resurrected by a filter.
        """
        if table not in CATALOG or "availability_basis" not in CATALOG[table]["fields"]:
            raise ValueError("table does not support point-in-time queries")
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be 1..10000")
        cutoff = instant(cutoff)
        spec = CATALOG[table]
        fields = spec["fields"]
        filters = filters or {}
        if not set(filters) <= set(fields) | {spec["pk"]}:
            raise ValueError("unknown filter column")
        params = [cutoff]
        conditions = ["available_at<=?"]
        # Rank ALL visible evidence, including unknown-quality or unconfirmed revisions.
        # Eligibility is applied afterwards to avoid falling back to obsolete revisions.
        order = []
        if "issued_at" in fields:
            order.append("issued_at DESC")
        order += ["revision_no DESC", "available_at DESC", spec["pk"] + " DESC"]
        sql = (
            f"WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY "
            + ",".join(spec["keys"])
            + " ORDER BY "
            + ",".join(order)
            + f") AS _rank FROM {table} WHERE "
            + " AND ".join(conditions)
            + ") SELECT * FROM ranked WHERE _rank=1"
        )
        for k, v in filters.items():
            sql += f" AND {k}=?"
            params.append(instant(v) if is_instant(k) else v)
        bases = ["verified_arrival", "verified_publication"] + (
            ["synthetic"] if allow_synthetic else []
        )
        sql += " AND availability_basis IN (" + ",".join("?" for _ in bases) + ")"
        params += bases
        if not allow_synthetic and "source_id" in fields:
            sql += " AND source_id NOT IN (SELECT source_id FROM data_source WHERE source_type='synthetic')"
        if "quality_flag" in fields:
            sql += " AND quality_flag IN ('valid','missing')"
        if table in ("station_actual", "weather_observation", "market_supply_actual"):
            sql += " AND interval_end<=?"
            params.append(cutoff)
        if "issued_at" in fields:
            sql += " AND issued_at<=?"
            params.append(cutoff)
        if target is not None:
            target = instant(target)
            if "effective_from" not in fields:
                raise ValueError("table has no effective validity")
            sql += " AND effective_from<=? AND (effective_to IS NULL OR effective_to>?)"
            params += [target, target]
        a = (
            "target_start"
            if "target_start" in fields
            else "interval_start" if "interval_start" in fields else None
        )
        b = (
            "target_end"
            if "target_end" in fields
            else "interval_end" if "interval_end" in fields else None
        )
        if start is not None or end is not None:
            if not a:
                raise ValueError("table has no target/observation interval")
            if start is not None:
                sql += f" AND {a}>=?"
                params.append(instant(start))
            if end is not None:
                sql += f" AND {b}<=?"
                params.append(instant(end))
        sql += " ORDER BY " + (a + "," if a else "") + spec["pk"] + " LIMIT ?"
        params.append(limit + 1)
        rows = [
            {k: r[k] for k in r.keys() if k != "_rank"}
            for r in self.db.execute(sql, params)
        ]
        if len(rows) > limit:
            raise ValueError("query exceeds row limit; narrow time range")
        return rows

    def bundle(
        self,
        task,
        station_id,
        start,
        end,
        cutoff,
        *,
        allow_synthetic=False,
        persist=False,
        history_hours=168,
    ):
        if task not in TASKS:
            raise ValueError("unknown prediction task")
        start, end, cutoff = instant(start), instant(end), instant(cutoff)
        if start >= end or start < cutoff:
            raise ValueError("future prediction interval required")
        if not 1 <= history_hours <= 720:
            raise ValueError("history_hours must be 1..720")
        history_start = instant(
            datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
            - timedelta(hours=history_hours)
        )
        records = {}
        missing = []

        def get(table, **kwargs):
            rows = self.as_of(table, cutoff, allow_synthetic=allow_synthetic, **kwargs)
            records.setdefault(table, []).extend(rows)
            return rows

        stations = get("station", filters={"station_id": station_id})
        if len(stations) != 1:
            raise ValueError("station is not visible at cutoff")
        configs = get(
            "station_config_version", filters={"station_id": station_id}, target=start
        )
        if len(configs) > 1:
            raise ValueError("ambiguous active station configuration")
        if not configs:
            missing.append("station_config_version")
        if configs and configs[0]["effective_to"] and configs[0]["effective_to"] < end:
            raise ValueError("target crosses configuration change; split interval")
        if task in ("day_ahead_power", "intraday_power"):
            get(
                "station_actual",
                filters={"station_id": station_id},
                start=history_start,
                end=cutoff,
            )
            bindings = get(
                "station_weather_binding",
                filters={"station_id": station_id, "confirmed_status": "confirmed"},
                target=start,
            )
            if not bindings:
                missing.append("confirmed_weather_binding")
            for binding in bindings:
                if binding["effective_to"] and binding["effective_to"] < end:
                    raise ValueError("target crosses weather binding change")
                location = binding["weather_location_id"]
                get(
                    "weather_forecast",
                    filters={"weather_location_id": location},
                    start=start,
                    end=end,
                )
                if task == "intraday_power":
                    get(
                        "weather_observation",
                        filters={"weather_location_id": location},
                        start=history_start,
                        end=cutoff,
                    )
            # Event cancellation/recovery is retained as visible evidence for callers.
            get("station_operation_event", filters={"station_id": station_id})
            if task == "intraday_power":
                get(
                    "station_forecast_snapshot",
                    filters={"station_id": station_id, "forecast_type": "day_ahead"},
                    start=start,
                    end=end,
                )
        else:
            bindings = get(
                "station_market_binding",
                filters={"station_id": station_id, "confirmed_status": "confirmed"},
                target=start,
            )
            price = [b for b in bindings if b["binding_role"] == "price"]
            if len(price) > 1:
                raise ValueError("ambiguous active price mapping")
            if not price:
                missing.append("confirmed_price_binding")
            for binding in bindings:
                if binding["effective_to"] and binding["effective_to"] < end:
                    raise ValueError("target crosses market binding change")
                location = binding["market_location_id"]
                get(
                    "market_supply_forecast",
                    filters={"market_location_id": location},
                    start=start,
                    end=end,
                )
                get(
                    "market_supply_actual",
                    filters={"market_location_id": location},
                    start=history_start,
                    end=cutoff,
                )
                get("market_operation_event", filters={"market_location_id": location})
            for binding in price:
                location = binding["market_location_id"]
                get(
                    "market_price",
                    filters={"market_location_id": location},
                    start=history_start,
                    end=cutoff,
                )
                if task == "intraday_spread":
                    baseline = get(
                        "market_price",
                        filters={
                            "market_location_id": location,
                            "market_stage": "day_ahead",
                        },
                        start=start,
                        end=end,
                    )
                    if not baseline:
                        missing.append("published_day_ahead_price")
        required = (
            ("station_actual", "weather_forecast")
            if task in ("day_ahead_power", "intraday_power")
            else ("market_price", "market_supply_forecast")
        )
        if task == "intraday_power":
            required += ("weather_observation", "station_forecast_snapshot")
        for table in required:
            if not records.get(table):
                missing.append(table)
        if task in ("day_ahead_power", "intraday_power"):
            radiation = ("ghi_wm2", "dni_wm2", "dhi_wm2", "poa_wm2")
            if not any(
                any(r.get(f) is not None for f in radiation)
                for r in records.get("weather_forecast", [])
            ):
                missing.append("weather_forecast.irradiance")
        # All prices stay separated by type/component/location; no implicit pairing.
        for table, rows in records.items():
            records[table] = list({r[CATALOG[table]["pk"]]: r for r in rows}.values())
        payload = {
            "task": task,
            "station_id": station_id,
            "target_start": start,
            "target_end": end,
            "cutoff_at": cutoff,
            "source_mode": "synthetic" if allow_synthetic else "production",
            "feature_version": "pit-evidence-v1",
            "records": records,
            "missing": missing,
            "coverage_status": "not_evaluated",
            "note": "Evidence selection only; no interpolation, fitted features or trained prediction.",
        }
        if persist:
            snapshot_id = str(uuid4())
            with self.db:
                self.append(
                    "feature_snapshot",
                    {
                        "snapshot_id": snapshot_id,
                        "task": task,
                        "station_id": station_id,
                        "target_start": start,
                        "target_end": end,
                        "cutoff_at": cutoff,
                        "created_at": instant(datetime.now(timezone.utc)),
                        "feature_version": payload["feature_version"],
                        "source_mode": payload["source_mode"],
                        "payload_json": encoded(payload),
                        "content_hash": digest(payload),
                    },
                )
                for table, rows in records.items():
                    for row in rows:
                        self.append(
                            "feature_input",
                            {
                                "input_id": str(uuid4()),
                                "snapshot_id": snapshot_id,
                                "table_name": table,
                                "record_id": row[CATALOG[table]["pk"]],
                                "available_at": row["available_at"],
                                "record_hash": digest(row),
                                "payload_json": encoded(row),
                            },
                        )
            return {"snapshot_id": snapshot_id, **payload}
        return payload

    def predictions(
        self, station_id, task, start, end, cutoff, *, allow_synthetic=False
    ):
        if task not in TASKS:
            raise ValueError("unknown prediction task")
        sql = (
            "WITH visible AS (SELECT v.*,r.task,r.station_id,r.cutoff_at,r.issued_at,r.available_at,r.source_mode, "
            "ROW_NUMBER() OVER(PARTITION BY r.model_version_id,r.station_id,v.target_start,v.target_end "
            "ORDER BY r.issued_at DESC,r.run_id DESC) AS rank "
            "FROM prediction_value v JOIN prediction_run r ON r.run_id=v.run_id "
            "WHERE r.station_id=? AND r.task=? AND v.target_start>=? AND v.target_end<=? "
            "AND r.available_at<=? AND r.issued_at<=? AND r.cutoff_at<=? "
            "AND r.status IN ('success','demo')"
        )
        params = [
            station_id,
            task,
            instant(start),
            instant(end),
            instant(cutoff),
            instant(cutoff),
            instant(cutoff),
        ]
        if not allow_synthetic:
            sql += " AND r.source_mode='production'"
        sql += ") SELECT * FROM visible WHERE rank=1 ORDER BY target_start LIMIT 10001"
        rows = [
            {k: r[k] for k in r.keys() if k != "rank"}
            for r in self.db.execute(sql, params)
        ]
        if len(rows) > 10000:
            raise ValueError("query exceeds row limit")
        return rows

    def inspect(self):
        tables = {
            r[0]
            for r in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        return {
            "path": str(self.path),
            "schema_version": self.db.execute(
                "SELECT max(version) FROM schema_migration"
            ).fetchone()[0],
            "tables": {
                t: self.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in list(CATALOG)
                + sorted((UPPER_TABLES | REGISTRY_TABLES) - set(CATALOG))
                + [
                    "serving_interval_wide",
                    "serving_daily_kpi",
                    "serving_version_compare",
                ]
                if t in tables
            },
            "integrity": self.db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_errors": [
                tuple(r) for r in self.db.execute("PRAGMA foreign_key_check")
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("inspect")
    sub.add_parser("seed-demo")
    q = sub.add_parser("query")
    q.add_argument("table")
    q.add_argument("--cutoff", required=True)
    q.add_argument("--filters", default="{}")
    q.add_argument("--start")
    q.add_argument("--end")
    q.add_argument("--demo", action="store_true")
    f = sub.add_parser("features")
    f.add_argument("--task", choices=TASKS, required=True)
    f.add_argument("--station", required=True)
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--cutoff", required=True)
    f.add_argument("--demo", action="store_true")
    f.add_argument("--persist", action="store_true")
    i = sub.add_parser("ingest")
    i.add_argument("file", type=Path)
    args = parser.parse_args()
    with Store(
        args.db,
        readonly=args.command in ("inspect", "query")
        or (args.command == "features" and not args.persist),
    ) as store:
        if args.command == "init":
            store.initialize()
            result = store.inspect()
        elif args.command == "seed-demo":
            store.initialize()
            from .storage_demo import seed_demo

            result = seed_demo(store)
        elif args.command == "inspect":
            result = store.inspect()
        elif args.command == "query":
            result = store.as_of(
                args.table,
                args.cutoff,
                filters=json.loads(args.filters),
                start=args.start,
                end=args.end,
                allow_synthetic=args.demo,
            )
        elif args.command == "features":
            result = store.bundle(
                args.task,
                args.station,
                args.start,
                args.end,
                args.cutoff,
                allow_synthetic=args.demo,
                persist=args.persist,
            )
        else:
            result = {"inserted": store.ingest(json.loads(args.file.read_text()))}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
