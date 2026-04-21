#!/usr/bin/env python3
import json
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Optional


ROOT = Path(__file__).resolve().parent
INDEX_HTML = ROOT / "index.html"
XAI_API_BASE = "https://api.x.ai/v1"
MAX_UPSTREAM_BODY_BYTES = 24 * 1024 * 1024


def json_dumps(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "GrokImagineStudio/1.0"

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_index()
            return

        if self.path == "/healthz":
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/api/image/generate":
            self._handle_image_generation()
            return

        if self.path == "/api/video/generate":
            self._handle_video_generation()
            return

        if self.path == "/api/video/extend":
            self._handle_video_extension()
            return

        if self.path == "/api/video/status":
            self._handle_video_status()
            return

        self._send_json(404, {"error": "Not found"})

    def _serve_index(self):
        html = INDEX_HTML.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("请求体不能为空")
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败: {exc.msg}") from exc

    def _send_json(self, status: int, payload: dict):
        data = json_dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _require_string(self, payload: dict, key: str, message: Optional[str] = None) -> str:
        value = str(payload.get(key, "")).strip()
        if not value:
            raise ValueError(message or f"{key} 不能为空")
        return value

    def _optional_string(self, payload: dict, key: str) -> Optional[str]:
        value = str(payload.get(key, "")).strip()
        return value or None

    def _optional_string_list(
        self,
        payload: dict,
        key: str,
        *,
        max_items: int,
        message: str,
    ) -> list:
        raw = payload.get(key)
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ValueError(message)
        cleaned: list = []
        for item in raw:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                cleaned.append(text)
        if len(cleaned) > max_items:
            raise ValueError(message)
        return cleaned

    def _parse_int_range(
        self,
        payload: dict,
        key: str,
        *,
        default: int,
        min_value: int,
        max_value: int,
        message: str,
    ) -> int:
        value = payload.get(key, default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(message)
        if value < min_value or value > max_value:
            raise ValueError(message)
        return value

    def _proxy_xai(self, *, method: str, path: str, api_key: str, payload: Optional[dict] = None):
        body = None if payload is None else json_dumps(payload)
        body_size = len(body) if body else 0

        if body_size > MAX_UPSTREAM_BODY_BYTES:
            mb = body_size / (1024 * 1024)
            return 413, {
                "error": (
                    f"请求体过大（约 {mb:.1f} MB，超过 {MAX_UPSTREAM_BODY_BYTES // (1024*1024)} MB 上限）。"
                    f"多张本地图会被转成 base64，体积会放大；建议：改用公网图片 URL，或先压缩图片后再上传。"
                )
            }

        request = Request(
            f"{XAI_API_BASE}{path}",
            method=method,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=300) as response:
                raw = response.read().decode("utf-8")
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = {"raw": raw}
                return response.status, data
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"error": raw or exc.reason}
            return exc.code, data
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLError) or "SSL" in str(reason).upper():
                hint = (
                    f"与 xAI 的 TLS 连接被意外断开（{reason}）。"
                    f"常见原因：请求体过大（本次约 {body_size / (1024 * 1024):.1f} MB）、"
                    f"网络不稳定，或上游临时拒绝。建议：改用公网 URL 传图，或压缩后再试。"
                )
                return 502, {"error": hint}
            return 502, {"error": f"请求 xAI API 失败: {reason}"}

    def _handle_image_generation(self):
        try:
            payload = self._read_json()
            api_key = self._require_string(payload, "api_key", "请输入 xAI API Key")
            prompt = self._require_string(payload, "prompt", "图片提示词不能为空")

            source_images = self._optional_string_list(
                payload,
                "source_images",
                max_items=5,
                message="source_images 最多 5 张",
            )
            if not source_images:
                legacy_single = self._optional_string(payload, "source_image")
                if legacy_single:
                    source_images = [legacy_single]

            upstream_body = {
                "model": "grok-imagine-image",
                "prompt": prompt,
            }

            resolution = self._optional_string(payload, "resolution")
            aspect_ratio = self._optional_string(payload, "aspect_ratio")
            response_format = self._optional_string(payload, "response_format")

            if resolution:
                upstream_body["resolution"] = resolution
            if response_format:
                upstream_body["response_format"] = response_format

            if source_images:
                upstream_path = "/images/edits"
                if aspect_ratio:
                    upstream_body["aspect_ratio"] = aspect_ratio
                if len(source_images) == 1:
                    upstream_body["image"] = {
                        "url": source_images[0],
                        "type": "image_url",
                    }
                else:
                    upstream_body["images"] = [
                        {"url": url, "type": "image_url"}
                        for url in source_images
                    ]
            else:
                upstream_path = "/images/generations"
                if aspect_ratio:
                    upstream_body["aspect_ratio"] = aspect_ratio
                n = payload.get("n", 1)
                try:
                    n = max(1, min(int(n), 4))
                except (TypeError, ValueError):
                    n = 1
                upstream_body["n"] = n

            status, data = self._proxy_xai(
                method="POST",
                path=upstream_path,
                api_key=api_key,
                payload=upstream_body,
            )
            self._send_json(status, {"ok": 200 <= status < 300, "data": data})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})

    def _handle_video_generation(self):
        try:
            payload = self._read_json()
            api_key = self._require_string(payload, "api_key", "请输入 xAI API Key")
            prompt = self._require_string(payload, "prompt", "视频提示词不能为空")
            source_image = self._optional_string(payload, "source_image")
            reference_images = self._optional_string_list(
                payload,
                "reference_images",
                max_items=5,
                message="reference_images 最多 5 张",
            )

            if source_image and reference_images:
                raise ValueError(
                    "起始图（image）与参考图（reference_images）互斥，请只选一种"
                )

            duration = self._parse_int_range(
                payload,
                "duration",
                default=5,
                min_value=1,
                max_value=15,
                message="duration 必须在 1-15 秒之间",
            )

            upstream_body = {
                "model": "grok-imagine-video",
                "prompt": prompt,
                "duration": duration,
            }

            aspect_ratio = self._optional_string(payload, "aspect_ratio")
            resolution = self._optional_string(payload, "resolution")

            if aspect_ratio:
                upstream_body["aspect_ratio"] = aspect_ratio
            if resolution:
                upstream_body["resolution"] = resolution
            if source_image:
                upstream_body["image"] = {"url": source_image}
            elif reference_images:
                upstream_body["reference_images"] = [
                    {"url": url} for url in reference_images
                ]

            status, data = self._proxy_xai(
                method="POST",
                path="/videos/generations",
                api_key=api_key,
                payload=upstream_body,
            )
            self._send_json(status, {"ok": 200 <= status < 300, "data": data})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})

    def _handle_video_extension(self):
        try:
            payload = self._read_json()
            api_key = self._require_string(payload, "api_key", "请输入 xAI API Key")
            prompt = self._require_string(payload, "prompt", "视频扩展提示词不能为空")
            source_video = self._require_string(payload, "source_video", "请提供待扩展的视频 URL")
            duration = self._parse_int_range(
                payload,
                "duration",
                default=6,
                min_value=2,
                max_value=10,
                message="扩展 duration 必须在 2-10 秒之间",
            )

            upstream_body = {
                "model": "grok-imagine-video",
                "prompt": prompt,
                "duration": duration,
                "video": {
                    "url": source_video,
                },
            }

            status, data = self._proxy_xai(
                method="POST",
                path="/videos/extensions",
                api_key=api_key,
                payload=upstream_body,
            )
            self._send_json(status, {"ok": 200 <= status < 300, "data": data})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})

    def _handle_video_status(self):
        try:
            payload = self._read_json()
            api_key = self._require_string(payload, "api_key", "请输入 xAI API Key")
            request_id = self._require_string(payload, "request_id", "request_id 不能为空")

            status, data = self._proxy_xai(
                method="GET",
                path=f"/videos/{request_id}",
                api_key=api_key,
                payload=None,
            )
            self._send_json(status, {"ok": 200 <= status < 300, "data": data})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})


def main():
    port = 8000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    print(f"Grok Imagine Studio running at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
