# Dashboard

The dashboard host pulls AWX job output and renders a static page.

## Files

| File | Purpose |
|---|---|
| `awx_pull.py` | Reads AWX job artifacts and writes `report.json` + `index.html` |
| `render_dashboard.py` | Converts a report JSON document into self-contained HTML |
| `dstate_web.py` | Optional localhost service for `/` and `/api/rescan` |
| `report.sample.json` | Synthetic demo report for local preview |

## Private config

Copy `config.env.example` to `config.env` and keep it private:

```bash
AWX_BASE_URL=https://awx.example.com
AWX_TOKEN=<redacted>
AWX_VERIFY_SSL=true
DSTATE_JT_ID=123
INTERVAL_MIN=30
DSTATE_ALLOWED_ORIGIN=https://monitor.example.com
```

`config.env` is ignored by git.

## Render from AWX

```bash
cd dashboard
set -a && . ./config.env && set +a
python3 awx_pull.py
```

## Preview demo data

```bash
python3 render_dashboard.py report.sample.json index.html
python3 -m http.server 8099
```

Open `http://127.0.0.1:8099/index.html`.

## nginx sketch

Serve the dashboard behind TLS and Basic auth, for example:

```nginx
location /dstate/ {
    auth_basic "D-State Monitor";
    auth_basic_user_file /etc/nginx/dstate.htpasswd;
    proxy_pass http://127.0.0.1:8090/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

Public example URL: `https://monitor.example.com/dstate/`.
