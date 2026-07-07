#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
awx_pull.py — AWX read-only connector for the dashboard host.

Authentication can use a bearer token or basic auth:
  AWX_BASE_URL  예) https://awx.example.com
  AWX_TOKEN     (Bearer)  또는  AWX_USERNAME / AWX_PASSWORD (Basic)
  AWX_VERIFY_SSL=true
  DSTATE_JT_ID  = dstate-fleet-scan Job Template id

동작:
  pull_report()  : 최신 job 의 artifacts.dstate_hosts + job_host_summaries(dark=도달불가) → report dict
  rescan_host(h) : (v2) limit=h 로 JT launch → 그 job 폴링 → 그 호스트 최신 결과   ※ Execute 토큰 필요
  main()         : pull_report() → render_dashboard.build → report.json + index.html
"""
import os, ssl, json, time, base64
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import render_dashboard  # mask_tsv_line 재사용(report 저장 전 마스킹)

def env(k, d=""): return os.environ.get(k, d)

def _cfg():
    base = env("AWX_BASE_URL").rstrip("/")
    if not base: raise RuntimeError("AWX_BASE_URL 필요")
    return {
        "base": base,
        "token": env("AWX_TOKEN"),
        "user": env("AWX_USERNAME"), "pw": env("AWX_PASSWORD"),
        "verify": env("AWX_VERIFY_SSL", "false").lower() not in ("0", "false", "no"),
        "jt": env("DSTATE_JT_ID"),
        "timeout": int(env("AWX_TIMEOUT_SECONDS", "30") or 30),
        "interval": int(env("INTERVAL_MIN", "30") or 30),
    }

def _auth(c):
    if c["token"]: return f"Bearer {c['token']}"
    raw = f"{c['user']}:{c['pw']}".encode()
    return "Basic " + base64.b64encode(raw).decode()

def _ctx(c): return None if c["verify"] else ssl._create_unverified_context()

def api(c, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(c["base"] + path, data=data, method=method, headers={
        "Authorization": _auth(c), "Content-Type": "application/json",
        "Accept": "application/json"})
    try:
        with urlopen(req, timeout=c["timeout"], context=_ctx(c)) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        raise RuntimeError(f"AWX HTTP {e.code}: {e.read().decode('utf-8','replace')[:300]}") from e
    except URLError as e:
        raise RuntimeError(f"AWX 연결 오류: {e.reason}") from e

def _dark_hosts(c, job_id):
    """job_host_summaries 페이지네이션 → dark(SSH 도달불가) 호스트명 목록."""
    out, path = [], f"/api/v2/jobs/{job_id}/job_host_summaries/?page_size=200"
    while path:
        page = api(c, "GET", path)
        for s in page.get("results", []):
            if s.get("dark"):
                nm = (s.get("summary_fields", {}).get("host", {}) or {}).get("name") or s.get("host_name")
                if nm: out.append(nm)
        nxt = page.get("next")
        path = nxt if nxt else None
    return sorted(set(out))

def _latest_job(c):
    """artifact(dstate_hosts) 가 있는 최신 전체-fleet job. 단일 재스캔(limit 지정)·빈/실패 job 건너뜀
    → '재스캔이 대시보드를 1대로 덮음' + '실패 스캔이 대시보드를 비움' 둘 다 방지."""
    if not c["jt"]: raise RuntimeError("DSTATE_JT_ID 필요")
    r = api(c, "GET", f"/api/v2/job_templates/{c['jt']}/jobs/?order_by=-id&page_size=25")
    for j in (r.get("results") or []):
        if (j.get("limit") or "").strip():
            continue
        d = api(c, "GET", f"/api/v2/jobs/{j['id']}/")
        hosts = (d.get("artifacts") or {}).get("dstate_hosts") or {}
        if hosts:
            return j, d, hosts
    raise RuntimeError("artifact 있는 전체-fleet job 없음 (최근 25건)")

def _mask_hosts(hosts):
    for hd in hosts.values():
        if hd and hd.get("lines"):
            hd["lines"] = [render_dashboard.mask_tsv_line(l) for l in hd["lines"]]
    return hosts

def _include_set():
    """DSTATE_INCLUDE_HOSTS 쉼표/공백 구분 목록 → frozenset. 미설정이면 None(전체)."""
    raw = os.environ.get("DSTATE_INCLUDE_HOSTS", "").strip()
    if not raw:
        return None
    return frozenset(h.strip() for h in raw.replace(",", " ").split() if h.strip())

def pull_report():
    c = _cfg()
    job, detail, hosts = _latest_job(c)
    jid = job["id"]
    hosts = _mask_hosts(hosts)
    inc = _include_set()
    if inc:
        hosts = {h: d for h, d in hosts.items() if h in inc}
    dark = _dark_hosts(c, jid)
    if inc:
        dark = [h for h in dark if h in inc]
    return {
        "generated_at": job.get("finished") or detail.get("finished") or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": f"AWX job #{jid}",
        "interval_min": c["interval"],
        "hosts": hosts,
        "unreachable": dark,
    }

# ---- v2: 단일 호스트 온디맨드 재스캔 (Execute 토큰 필요) ----
_DONE = {"successful", "failed", "error", "canceled"}

def rescan_host(h):
    c = _cfg()
    if not h or "/" in h or " " in h:
        raise ValueError("호스트명이 올바르지 않음")
    launch = api(c, "POST", f"/api/v2/job_templates/{c['jt']}/launch/", {"limit": h})
    jid = launch.get("id") or launch.get("job")
    if not jid: raise RuntimeError(f"launch 실패: {launch}")
    poll_to = int(env("RESCAN_POLL_TIMEOUT", "90") or 90)
    step = float(env("RESCAN_POLL_SECONDS", "2") or 2)
    # 초기 10초는 1초 간격으로 폴링 → 빠른 호스트 체감 개선
    waited, status = 0.0, "pending"
    while waited < poll_to:
        d = api(c, "GET", f"/api/v2/jobs/{jid}/")
        status = d.get("status")
        if status in _DONE:
            hosts = _mask_hosts((d.get("artifacts") or {}).get("dstate_hosts") or {})
            # artifact에 호스트가 있으면 도달 성공 확정 → dark 조회(추가 API 왕복) 생략
            unreachable = False if hosts.get(h) else (h in _dark_hosts(c, jid))
            return {"host": h, "job_id": jid, "status": status,
                    "unreachable": unreachable, "data": hosts.get(h)}
        interval = 1.0 if waited < 10 else step
        time.sleep(interval); waited += interval
    return {"host": h, "job_id": jid, "status": status, "timeout": True}

def merge_rescan_result(host, host_data):
    """재스캔 결과 한 호스트를 report.json에 반영하고 index.html 재생성."""
    out = os.environ.get("OUT_HTML", "index.html")
    rj = os.environ.get("OUT_JSON", "report.json")
    try:
        with open(rj, encoding="utf-8") as f:
            report = json.load(f)
    except Exception:
        return
    if host_data:
        report["hosts"][host] = host_data
    with open(rj, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_dashboard.build(report))
    try:
        os.chmod(rj, 0o600); os.chmod(out, 0o640)
    except Exception:
        pass


def main():
    import render_dashboard
    out = os.environ.get("OUT_HTML", "index.html")
    rj = os.environ.get("OUT_JSON", "report.json")
    report = pull_report()
    with open(rj, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_dashboard.build(report))
    try:  # 권한 고정(cron 재실행마다 유지) — report.json은 민감, index.html은 nginx(프록시)용
        os.chmod(rj, 0o600); os.chmod(out, 0o640)
    except Exception:
        pass
    print(f"pulled {report['source']}: hosts={len(report['hosts'])} unreachable={len(report['unreachable'])} -> {out}")

if __name__ == "__main__":
    main()
