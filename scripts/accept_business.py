"""Exercise the saved public-data business chain through the deployed API."""
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from uuid import uuid4

BASE = "http://10.21.179.91:8503"
DAY = "2025-11-29"
ACTOR = "Codex技术验收（用户授权）"
OPENER = build_opener(ProxyHandler({}))


def api(path, body=None):
    request = Request(BASE + path, data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"{path}: {exc.code} {exc.read().decode()[:500]}") from None


def main():
    receipt = dict(date=DAY, source="market:shandong", actor=ACTOR, checks=[])
    predictions = {}
    for role, task in dict(pv="pv_day_ahead_reference", da="da_price_reference", rt="rt_price_day_ahead_reference").items():
        scope = dict(source_key="market:shandong", task_id=task, trading_date=DAY)
        context = api("/api/v1/workspace/context?" + urlencode(scope))
        model = next(m for m in context["models"] if m["state"] == "research_active")
        existing = next((r for r in context["records"] if r["model_id"] == model["id"]), None)
        if existing:
            rid = existing["id"]
        else:
            result = api("/api/v1/workspace/commands", dict(action="predict", source_key=scope["source_key"], task_id=task,
                         date=DAY, model_id=model["id"], actor=ACTOR, reason="技术验收复用既有模型生成业务链输入，不训练或启封终评"))
            rid = result["id"]
        predictions[role] = rid
    receipt["predictions"] = predictions
    common = dict(source_key="market:shandong", trading_date=DAY, record_id=predictions["pv"], actor=ACTOR,
                  reason="技术验收历史研究方案与结算，不构成正式交易申报", da_record_id=predictions["da"], rt_record_id=predictions["rt"])
    catalog = api("/api/v1/business/catalog?" + urlencode(dict(source_key=common["source_key"], trading_date=DAY, record_id=predictions["pv"])))
    common["context_version"] = catalog["context_version"]
    first = api("/api/v1/business/commands", dict(common, action="create_plan", parameters=dict(bid_ratio=1), key=uuid4().hex))
    plan = first["plan"]
    assert plan["estimated"]["priced_hours"] == 24
    receipt["checks"].append("saved_prediction_to_priced_plan")
    observation = catalog["observations"][0]["id"]
    def settle(pid):
        result = api("/api/v1/business/commands", dict(common, action="settle", plan_id=pid, observation_id=observation, key=uuid4().hex))
        s = result["settlement"]
        c = s["comparison"]
        assert s["actual"]["settled_hours"] == 24
        assert abs(c["delta"] - c["power_effect"] - c["price_effect"] - c["fee_effect"]) < 1e-6
        return s
    original = settle(plan["id"])
    second = api("/api/v1/business/commands", dict(common, action="derive_plan", plan_id=plan["id"], parameters=dict(bid_ratio=.7), key=uuid4().hex))
    derived = second["plan"]
    comparison = settle(derived["id"])
    receipt["checks"].append("plan_derived_and_two_versioned_settlements")
    review = dict(source_key=common["source_key"], date=DAY, plan_id=plan["id"], settlement_id=original["id"],
                  actor=ACTOR, reason="技术验收同观测方案对照与处理记录，不确认业务因果", category="strategy", owner=ACTOR)
    issue = api("/api/v1/business/review-commands", dict(review, action="create"))
    review["issue_id"] = issue["id"]
    api("/api/v1/business/review-commands", dict(review, action="start"))
    api("/api/v1/business/review-commands", dict(review, action="resolve", evidence="已保存申报系数由1调整至0.7的派生方案，按同一实际观测分别结算，等待定量核对"))
    verified = api("/api/v1/business/review-commands", dict(review, action="verify", verification=dict(kind="settlement_comparison", comparison_object_id=comparison["id"])))
    assert verified["state"] == "verified"
    assert abs(verified["verification"]["delta"] - comparison["actual"]["value"] + original["actual"]["value"]) < 1e-6
    receipt["checks"].append("issue_processed_and_quantitatively_verified")
    analysis = api("/api/v1/workspace/commands", dict(action="analyze", source_key=common["source_key"], task_id="pv_day_ahead_reference",
                   date=DAY, model_id=plan["model_id"], record_id=predictions["pv"], business_object_id=issue["id"],
                   actor=ACTOR, reason="分析这个已保存处理事项，核对方案参数、实际结算和验证结果"))
    assert analysis.get("business_object_id") == issue["id"] or any(t["name"] == "核对业务对象快照" for t in analysis["tools"])
    receipt["checks"].append("assistant_restores_issue_and_saved_plan_parameters")
    receipt.update(status="passed", plan_id=plan["id"], derived_plan_id=derived["id"], settlement_id=original["id"],
                   comparison_settlement_id=comparison["id"], issue_id=issue["id"], verification=verified["verification"],
                   estimate=plan["estimated"], actual=original["actual"], decomposition=original["comparison"], analysis_id=analysis["id"])
    target = Path(__file__).resolve().parents[1] / "runtime/business-live-acceptance.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(status=receipt["status"], checks=receipt["checks"], verification=receipt["verification"], receipt=str(target)), ensure_ascii=False))


if __name__ == "__main__":
    main()
