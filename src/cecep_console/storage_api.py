"""Read-only JSON facade for the persistent store; synthetic queries are explicit."""

import json
from .storage import Store, instant


def response(path, query):
    def arg(name, default=None):
        value = query.get(name, [default])[0]
        if value is None:
            raise ValueError("missing parameter: " + name)
        return value

    with Store(readonly=True) as store:
        if path == "/api/storage/health":
            return {
                "status": "ok",
                "service": "cecep-storage",
                "synthetic_requires_opt_in": True,
                **store.inspect(),
            }
        cutoff = instant(arg("cutoff"))
        demo = arg("demo", "0") == "1"
        if path == "/api/storage/query":
            filters = json.loads(arg("filters", "{}"))
            if not isinstance(filters, dict):
                raise ValueError("filters must be an object")
            rows = store.as_of(
                arg("table"),
                cutoff,
                filters=filters,
                start=arg("start", "") or None,
                end=arg("end", "") or None,
                target=arg("target", "") or None,
                allow_synthetic=demo,
                limit=int(arg("limit", "10000")),
            )
            return {
                "rows": rows,
                "count": len(rows),
                "cutoff_at": cutoff,
                "allow_synthetic": demo,
            }
        if path == "/api/storage/features":
            return store.bundle(
                arg("task"),
                arg("station"),
                arg("start"),
                arg("end"),
                cutoff,
                allow_synthetic=demo,
            )
        if path == "/api/storage/predictions":
            rows = store.predictions(
                arg("station"),
                arg("task"),
                arg("start"),
                arg("end"),
                cutoff,
                allow_synthetic=demo,
            )
            return {
                "rows": rows,
                "count": len(rows),
                "cutoff_at": cutoff,
                "allow_synthetic": demo,
            }
        raise ValueError("unknown storage endpoint")
