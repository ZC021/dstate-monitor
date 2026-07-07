#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dstate_web.py — optional localhost web service for nginx proxying.

역할:
  GET  /              → index.html 서빙 (30분 타이머가 awx_pull.main 으로 갱신한 정적 파일)
  GET  /api/rescan?host=H  → (v2) 그 호스트만 즉시 AWX 재스캔 → JSON 결과   ※ Execute 토큰 필요

스캔(30분) 자체는 별도 systemd timer 가 `awx_pull.py` 실행해 index.html 갱신.
이 서비스는 서빙 + 온디맨드 재스캔만 담당. AWX 는 무수정(잡 실행만).
"""
import os, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("BIND_HOST", "127.0.0.1")
PORT = int(os.environ.get("BIND_PORT", "8090"))
GLOBAL_COOLDOWN = 8        # 전역 재스캔 최소 간격(초)
HOST_COOLDOWN = 60         # 호스트별 재스캔 최소 간격(초)
_job_lock = threading.Lock()       # AWX launch 동시성 1개
_rl_lock = threading.Lock()
_rl = {"any": 0.0, "host": {}}
AUDIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dstate_audit.log")

def _client_ip(h):
    return h.headers.get("X-Real-IP") or h.client_address[0]

def _audit(h, host, result):
    try:
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write("%s ip=%s host=%s result=%s\n" % (
                time.strftime("%Y-%m-%dT%H:%M:%S"), _client_ip(h), host, result))
    except Exception:
        pass

def _known_hosts():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        return set(rep.get("hosts", {})) | set(rep.get("unreachable", []))
    except Exception:
        return set()

def _send(h, code, body, ctype="application/json; charset=utf-8"):
    b = body.encode("utf-8") if isinstance(body, str) else body
    h.send_response(code)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(b)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(b)

def _file(h, name, ctype):
    p = os.path.join(DIR, name)
    if not os.path.exists(p):
        _send(h, 404, "not generated yet — run awx_pull.py", "text/plain; charset=utf-8"); return
    with open(p, "rb") as f:
        _send(h, 200, f.read(), ctype)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # 조용히

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return _file(self, "index.html", "text/html; charset=utf-8")
        if u.path == "/api/rescan":   # 재스캔은 상태변경 → POST 전용
            return _send(self, 405, json.dumps({"error": "POST만 허용"}))
        # /report.json 등 그 외 일절 서빙 안 함(민감정보 노출 방지)
        _send(self, 404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if urlparse(self.path).path == "/api/rescan":
            return self._rescan()
        _send(self, 404, json.dumps({"error": "not found"}))

    def _rescan(self):
        # CSRF/오용 방지: application/json POST 만(cross-site form 은 json 못 보냄), Origin 검증
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return _send(self, 415, json.dumps({"error": "application/json 필요"}))
        origin = self.headers.get("Origin") or ""
        if origin:
            allowed = os.environ.get("DSTATE_ALLOWED_ORIGIN", "").rstrip("/")
            host = self.headers.get('Host', '')
            host_origins = {f"http://{host}".rstrip("/"), f"https://{host}".rstrip("/")}
            if origin.rstrip("/") not in ({allowed} | host_origins):
                _audit(self, "-", "reject-origin")
                return _send(self, 403, json.dumps({"error": "origin 거부"}))
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 1000:
            return _send(self, 400, json.dumps({"error": "본문 없음/과대"}))
        try:
            host = (json.loads(self.rfile.read(n).decode("utf-8")) or {}).get("host", "")
        except Exception:
            return _send(self, 400, json.dumps({"error": "JSON 파싱 실패"}))
        if host not in _known_hosts():   # report.json 실재 호스트만(임의 limit 차단)
            _audit(self, host, "reject-unknown")
            return _send(self, 400, json.dumps({"error": "알 수 없는 호스트"}))
        now = time.time()                # rate limit
        with _rl_lock:
            if now - _rl["any"] < GLOBAL_COOLDOWN:
                _audit(self, host, "reject-rate-global")
                return _send(self, 429, json.dumps({"error": "잠시 후 다시(전역 쿨다운)"}))
            if now - _rl["host"].get(host, 0) < HOST_COOLDOWN:
                _audit(self, host, "reject-rate-host")
                return _send(self, 429, json.dumps({"error": "이 호스트는 잠시 후 다시"}))
            _rl["any"] = now; _rl["host"][host] = now
        if not _job_lock.acquire(blocking=False):
            return _send(self, 429, json.dumps({"error": "다른 재스캔 진행 중"}))
        try:
            import awx_pull
            res = awx_pull.rescan_host(host)
            if res.get("data") and not res.get("unreachable") and not res.get("timeout"):
                try:
                    awx_pull.merge_rescan_result(host, res["data"])
                except Exception:
                    pass
            _audit(self, host, "ok job=%s" % res.get("job_id"))
            _send(self, 200, json.dumps(res, ensure_ascii=False))
        except Exception as e:
            _audit(self, host, "error %s" % e)
            _send(self, 502, json.dumps({"error": str(e)}))
        finally:
            _job_lock.release()

def main():
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print(f"dstate_web on http://{HOST}:{PORT}  (dir={DIR})")
    srv.serve_forever()

if __name__ == "__main__":
    main()
