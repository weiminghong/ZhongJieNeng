"""只读展示 API 与静态前端，所有静态资源从 GB10 本地提供。"""

from __future__ import annotations

import argparse
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from plotly.offline import get_plotlyjs

from .analysis import answer_question, dataset
from .data import DATES, STATIONS, available_context
from .storage_api import response as storage_response

LOGGER = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}


class Handler(BaseHTTPRequestHandler):
    def send_body(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store" if content_type == "application/json" else "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict, status: int = 200):
        self.send_body(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(), "application/json", status)

    def context(self, query: dict) -> dict:
        station = query.get("station", ["lanneng"])[0]
        selected_date = query.get("date", [DATES[0]])[0]
        if station not in STATIONS or selected_date not in DATES:
            raise ValueError("请选择已提供的场站和演示日期")
        return dataset(station, selected_date, query.get("daylight", ["0"])[0] == "1")

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path in ASSETS:
                filename, mime = ASSETS[url.path]
                self.send_body((STATIC / filename).read_bytes(), mime)
            elif url.path == "/plotly.js":
                self.send_body(get_plotlyjs().encode(), "text/javascript")
            elif url.path.startswith("/api/storage/"):
                self.send_json(storage_response(url.path, parse_qs(url.query)))
            elif url.path == "/api/health":
                self.send_json({"status": "ok", "service": "cecep-agent-workbench"})
            elif url.path == "/api/context":
                self.send_json(available_context())
            elif url.path == "/api/data":
                self.send_json(self.context(parse_qs(url.query)))
            else:
                self.send_json({"error": "页面不存在"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            LOGGER.exception("Request failed")
            self.send_json({"error": "数据服务暂不可用，请刷新重试"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        if self.path != "/api/analyze":
            self.send_json({"error": "接口不存在"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError("请求大小超出限制")
            body = json.loads(self.rfile.read(length))
            question = str(body.get("question", "")).strip()
            if not question or len(question) > 1000:
                raise ValueError("请输入 1 至 1000 字的问题")
            query = {key: [str(body[key])] for key in ("station", "date", "daylight") if key in body}
            self.send_json(answer_question(question, self.context(query)))
        except (ValueError, TypeError, KeyError):
            self.send_json({"error": "问题或场站参数有误，请检查后重试"}, 400)
        except Exception:
            LOGGER.exception("Analysis failed")
            self.send_json({"error": "分析暂不可用，请稍后重试"}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    LOGGER.info("Serving on %s:%s", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
