"""显式接入固定版本的开源计算组件，不修改上游代码。"""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def solar_components():
    source = ROOT / "vendor/solar-forecast/src"
    if not source.is_dir():
        raise RuntimeError("缺少 solar-forecast，请运行 git submodule update --init")
    # 上游包入口会同时导入训练依赖。独立加载物理模块及其配置。
    namespace = "cecep_solar_upstream"
    package = ModuleType(namespace)
    package.__path__ = [str(source / "solar_forecast")]
    sys.modules[namespace] = package
    loaded = {}
    for name in ("config", "physics"):
        module_name = f"{namespace}.{name}"
        spec = importlib.util.spec_from_file_location(module_name, source / "solar_forecast" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        loaded[name] = module
    return loaded["config"].Site, loaded["physics"].clear_sky_power


def evaluate_predictions(actual: list[float], predicted: list[float]) -> dict:
    """复用能源交易开源项目的评估器，界面只选用 MAE/RMSE。"""
    path = ROOT / "vendor/ai-energy-trading-platform/src/forecast/evaluate.py"
    if not path.is_file():
        raise RuntimeError("缺少开源评估器，请运行 git submodule update --init")
    spec = importlib.util.spec_from_file_location("cecep_upstream_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class StoredPredictions:
        def predict(self, samples):
            return predicted

    return module.ModelEvaluator().evaluate(StoredPredictions(), actual, actual)["metrics"]

