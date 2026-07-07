# D-State Fleet Monitor

Fleet dashboard for Linux processes stuck in `D` (uninterruptible sleep). A rising count usually means storage, NFS, or block I/O is hanging; these processes often cannot be killed until the underlying I/O recovers.

## Architecture

AWX scheduled scan -> pull cron/timer on the dashboard host -> static dashboard behind nginx Basic auth.

- `awx/dstate_scan.yml` runs read-only `ps` collection across the inventory.
- `dashboard/awx_pull.py` pulls the latest AWX job artifact and host reachability.
- `dashboard/render_dashboard.py` renders `report.json` to a self-contained `index.html`.
- `dashboard/dstate_web.py` optionally serves the dashboard and supports one-host rescan via AWX.

## Setup

1. Add `awx/dstate_scan.yml` to an AWX project.
2. Create a Job Template with a demo or real inventory, normal SSH credential, `become: false`, no concurrent jobs, and a finite timeout.
3. Copy `dashboard/config.env.example` values into a private `dashboard/config.env` (do not commit it):
   ```bash
   AWX_BASE_URL=https://awx.example.com
   AWX_TOKEN=<redacted>
   AWX_VERIFY_SSL=true
   DSTATE_JT_ID=123
   ```
4. Generate the dashboard:
   ```bash
   cd dashboard
   set -a && . ./config.env && set +a
   python3 awx_pull.py
   ```
5. Serve `/dstate/` with nginx and Basic auth, for example `https://monitor.example.com/dstate/`.

## Demo data

`dashboard/report.sample.json` is synthetic. To preview locally:

```bash
cd dashboard
python3 render_dashboard.py report.sample.json index.html
python3 -m http.server 8099
```

Generated reports, local tokens, logs, and secrets are ignored by git.

## Sanitization / 공개 범위

사내 프로젝트를 공개용으로 정리(비식별화)한 저장소입니다. 회사명·내부 데이터·운영 환경 정보(호스트명·내부 주소·계정)는 포함하지 않으며, 예시 데이터는 전부 합성(synthetic)입니다. 세부 구현과 운영 경험은 면접에서 상세히 설명할 수 있습니다.

This is a sanitized public export of an internal project. It contains no company names, internal data, or production environment details (hostnames, internal addresses, accounts); all sample data is synthetic.
