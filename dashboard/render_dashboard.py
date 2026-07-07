#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_dashboard.py — D-State Fleet Monitor (표준 라이브러리만, 오프라인 안전)
디자인: 모던 다크 대시보드(클린 sans UI + 데이터만 mono · 둥근 카드 · 여백 · 부드러운 모션).
입력 report.json → 자기완결 index.html (외부 폰트/JS/CDN 0).

해석: etimes = 프로세스 "나이" ≠ "D 대기시간". 즉시 끝나야 할 명령(git/ls/du/sync)이 나이 크면 = 진짜 stuck.
접속 정보(서버별): LOGINS\\t<횟수>\\t<유저> = 주 접속자(로그인 빈도) · LASTHOST\\t<last -F 한 줄> = 마지막 접속자(누가·언제).
"""
import sys, os, json, re, html
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

def _to_kst(ts):
    """UTC ISO 타임스탬프 → 한국시간 문자열 (예: 2026-06-09 17:40)."""
    if not ts:
        return '-'
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.astimezone(KST).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return ts

STUCK_AGE = 120
RED_STUCK, ORANGE_STUCK = 10, 3
RED_DCOUNT, ORANGE_DCOUNT = 20, 5
WD = {'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'}
EXCLUDE_USERS = {'scanner'}  # 관리자/스캐너 계정 — 접속자 표시에서 제외

QUICK_RE = re.compile(r'^\[?(git|/usr/bin/git|/usr/lib/git-core/git|ls|du|find|ugrep|grep|stat|sync|/bin/sync|cat|head|tail|cp|mv|rm)\b', re.I)
SENS = re.compile(r'((?:pass(?:word|wd)?|pwd|secret|token|api[-_]?key|access[-_]?key|auth|connection-token)[=\s:]+)\S+', re.I)
URLCRED = re.compile(r'(://[^:/@\s]+:)[^@/\s]+@')
DISK_STALL = re.compile(r'jbd2|wait_on_buffer|io_schedule|blk_')


def redact(s):
    s = SENS.sub(lambda m: m.group(1).rstrip('=: \t') + '=***', s)
    return URLCRED.sub(r'\1***@', s)


def mask_tsv_line(line):
    if not line or line.startswith(('RC=', 'LOGINS\t', 'LASTHOST\t')) or '\t' not in line:
        return line
    f = line.split('\t')
    if len(f) < 7:
        return line
    return '\t'.join(f[:6] + [redact('\t'.join(f[6:]))])


def wchan_cat(w):
    if re.search(r'^nfs|nfs_|rpc_wait', w): return ('NFS/RPC', 'nfs')
    if re.search(r'walk_component|d_alloc|lookup_slow|open_last_lookups|iterate_dir', w): return ('VFS·조회', 'nfs')
    if re.search(r'page_bit|wait_on_buffer|jbd2|buffered_read|lock_page|nfs_start_io|submit_bio|io_schedule|blk', w): return ('디스크', 'disk')
    if re.search(r'rwsem|mutex|down_', w): return ('lock', 'lock')
    if re.search(r'cv_wait|cv_timedwait|txg', w): return ('ZFS', 'zfs')
    return ('기타', 'etc')


def human_age(sec):
    if sec < 0: return '-'
    d, r = divmod(sec, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
    if d: return f'{d}일 {h}시간'
    if h: return f'{h}시간 {m}분'
    if m: return f'{m}분'
    return f'{sec}초'


def short_cmd(args):
    a = args.strip()
    if a.startswith('['): return a.split()[0]
    tok = a.split()
    if not tok: return a
    prog = tok[0].rsplit('/', 1)[-1]
    if prog.startswith('git') and len(tok) > 1:
        sub = next((t for t in tok[1:] if not t.startswith('-')), '')
        return f'git {sub}'.strip()
    if 'vscode-server' in a or 'server.bundle.js' in a: return 'vscode-server'
    if 'cursor-server' in a: return 'cursor-server'
    return prog


def when_from(tokens):
    """last/lastlog 토큰에서 로그인 시각 추출(요일~연도)."""
    out, started = [], False
    for t in tokens:
        if not started and t in WD: started = True
        if started:
            if t in ('-', 'still', 'gone'): break
            out.append(t)
    return ' '.join(out)


def parse_proc(line):
    f = line.split('\t')
    if len(f) < 7: return None
    stat, pid, ppid, user, et, wchan = f[0], f[1], f[2], f[3], f[4], f[5]
    args = redact('\t'.join(f[6:]))
    try: et = int(et)
    except Exception: et = -1
    quick = bool(QUICK_RE.match(args))
    return {'stat': stat, 'pid': pid, 'user': user, 'etimes': et, 'wchan': wchan,
            'args': args, 'quick': quick, 'stuck': quick and et > STUCK_AGE}


def host_summary(name, h):
    rc = h.get('rc')
    procs, login_freq = [], []
    last_user, last_when = '', ''
    for ln in h.get('lines', []) or []:
        if ln.startswith('RC='):
            try: rc = int(ln[3:].strip())
            except Exception: pass
            continue
        if ln.startswith('LOGINS\t'):
            p = ln.split('\t')
            if len(p) >= 3:
                try: login_freq.append((int(p[1]), p[2]))
                except Exception: pass
            continue
        if ln.startswith('LASTHOST\t'):
            raw = ln[len('LASTHOST\t'):].split()
            if raw:
                last_user, last_when = raw[0], when_from(raw)
            continue
        if not ln.strip(): continue
        pp = parse_proc(ln)
        if pp: procs.append(pp)

    login_freq = sorted((nu for nu in login_freq if nu[1] not in EXCLUDE_USERS), reverse=True)
    if last_user in EXCLUDE_USERS:
        last_user, last_when = '', ''
    regular_user = login_freq[0][1] if login_freq else ''

    dcount = len(procs)
    stuck = [p for p in procs if p['stuck']]
    stuck_n = len(stuck)
    oldest_stuck = max((p['etimes'] for p in stuck), default=-1)
    cats = {}
    for p in procs:
        c, _ = wchan_cat(p['wchan']); cats[c] = cats.get(c, 0) + 1
    top_cat = max(cats, key=cats.get) if cats else '-'

    if rc == 124:
        status, sev = 'PS_TIMEOUT', 4
    elif rc not in (0, None):
        status, sev = 'SCAN_ERR', 2
    elif dcount == 0:
        status, sev = 'OK', 0
    else:
        status = 'D'
        disk_stall = any(DISK_STALL.search(p['wchan']) for p in procs)
        if stuck_n >= RED_STUCK or dcount >= RED_DCOUNT or oldest_stuck > 3600: sev = 4
        elif stuck_n >= ORANGE_STUCK or dcount >= ORANGE_DCOUNT or disk_stall: sev = 3
        else: sev = 2
        if disk_stall: top_cat = '디스크'

    rep = max(stuck, key=lambda p: p['etimes'], default=None) or (max(procs, key=lambda p: p['etimes']) if procs else None)
    return {'name': name, 'ansible_host': h.get('ansible_host', name), 'rc': rc,
            'dcount': dcount, 'stuck_n': stuck_n, 'oldest_stuck': oldest_stuck,
            'top_cat': top_cat, 'status': status, 'sev': sev,
            'rep': short_cmd(rep['args']) if rep else '-',
            'regular_user': regular_user, 'login_freq': login_freq[:5],
            'last_user': last_user, 'last_when': last_when, 'procs': procs, 'cats': cats}


SEV = {0: 'ok', 2: 'warn', 3: 'high', 4: 'crit', 5: 'crit'}
SEV_LABEL = {'OK': '정상', 'D': 'D 누적', 'PS_TIMEOUT': 'PS 멈춤', 'SCAN_ERR': '스캔오류'}
CAT_KEY = {'NFS/RPC': 'nfs', 'VFS·조회': 'nfs', '디스크': 'disk', 'lock': 'lock', 'ZFS': 'zfs'}


def esc(x): return html.escape(str(x))


def build(report):
    hosts = report.get('hosts', {})
    unreachable = sorted(report.get('unreachable', []) or [])
    rows = [host_summary(n, h) for n, h in hosts.items()]
    scanned = len(rows)
    affected = sum(1 for r in rows if r['dcount'] > 0)
    total_d = sum(r['dcount'] for r in rows)
    total_stuck = sum(r['stuck_n'] for r in rows)

    catall = {}
    for r in rows:
        for c, n in r['cats'].items(): catall[c] = catall.get(c, 0) + n
    cat_total = sum(catall.values()) or 1
    bars = ''.join(
        f'<div class="bar"><span class="bn"><i class="bk {CAT_KEY.get(c,"etc")}"></i>{esc(c)}</span>'
        f'<span class="btrack"><i class="bf {CAT_KEY.get(c,"etc")}" style="width:{max(3,round(n*100/cat_total))}%"></i></span>'
        f'<span class="bv">{n}</span></div>'
        for c, n in sorted(catall.items(), key=lambda kv: -kv[1])[:6]) or '<div class="muted">D-state 프로세스 없음</div>'

    # fleet: 접속 많은 사용자(여러 서버에 자주 로그인)
    fu = {}
    for r in rows:
        for cnt, u in r['login_freq']:
            d = fu.setdefault(u, {'n': 0, 'hosts': 0}); d['n'] += cnt; d['hosts'] += 1
    top_users = sorted(fu.items(), key=lambda kv: -kv[1]['n'])[:8]
    umax = max((v['n'] for _, v in top_users), default=1)
    users_panel = ''.join(
        f'<div class="urow"><span class="un">{esc(u)}</span>'
        f'<span class="utrack"><i style="width:{max(5,round(v["n"]*100/umax))}%"></i></span>'
        f'<span class="uv">{v["n"]}<small> · {v["hosts"]}대</small></span></div>'
        for u, v in top_users) or '<div class="muted">로그인 데이터 없음 — 플레이북 재배포 후 수집</div>'

    rows.sort(key=lambda r: (-r['sev'], -r['stuck_n'], -r['dcount'], r['name']))

    det_data = {}
    trs = []
    for r in rows:
        cls = SEV.get(r['sev'], 'ok')
        last = f"<b>{esc(r['last_user'])}</b><span class='when'>{esc(r['last_when'])}</span>" if r['last_user'] else "<span class='muted'>—</span>"
        reg = f"{esc(r['regular_user'])}" if r['regular_user'] else "<span class='muted'>—</span>"
        if r['procs']:
            det_data[r['name']] = {
                'ip': r['ansible_host'],
                'dc': r['dcount'], 'sk': r['stuck_n'],
                'freq': ' · '.join(f"{u} {n}회" for n, u in r['login_freq']) or '데이터 없음',
                'rep': r['rep'] or '',
                'ps': [{'st': p['stuck'], 'ag': human_age(p['etimes']),
                        'wc': p['wchan'], 'us': p['user'], 'ar': p['args'][:400]}
                       for p in sorted(r['procs'], key=lambda p: (not p['stuck'], -p['etimes']))]
            }
            det = f"<button class='db' onclick=\"openDet('{esc(r['name'])}')\" title='상세 보기'>D {r['dcount']}개 상세</button>"
        else:
            det = f"<span class='muted mono'>{esc(r['ansible_host'])}</span>"
        trs.append(
            f"<tr class='{cls}' data-host='{esc(r['name'])}' data-sev='{r['sev']}' data-stuck='{r['stuck_n']}' data-d='{r['dcount']}' data-age='{r['oldest_stuck']}'>"
            f"<td><span class='pill {cls}'>{esc(SEV_LABEL.get(r['status'], r['status']))}</span></td>"
            f"<td class='h'>{esc(r['name'])}<button class='rb' onclick=\"rescan(this,'{esc(r['name'])}')\" title='이 호스트만 지금 재스캔'>↻</button></td>"
            f"<td class='reg'>{reg}</td>"
            f"<td class='last'>{last}</td>"
            f"<td class='num'>{r['dcount'] or ''}</td>"
            f"<td class='num sn'>{r['stuck_n'] or ''}</td>"
            f"<td>{'<span class=chip data-k='+CAT_KEY.get(r['top_cat'],'etc')+'>'+esc(r['top_cat'])+'</span>' if r['dcount'] else ''}</td>"
            f"<td class='det'>{det}</td></tr>")
    for u in unreachable:
        trs.append(
            f"<tr class='crit unreach' data-host='{esc(u)}' data-sev='5' data-stuck='0' data-d='0' data-age='-1'>"
            f"<td><span class='pill crit'>도달불가</span></td><td class='h'>{esc(u)}</td>"
            f"<td class='reg'><span class='muted'>—</span></td><td class='last'><span class='muted'>SSH 무응답</span></td>"
            f"<td class='num'></td><td class='num'></td><td><span class='chip' data-k='etc'>꺼짐/네트워크 확인</span></td><td class='det'>—</td></tr>")

    health = 'crit' if (len(unreachable) or any(r['sev'] >= 4 for r in rows)) else ('high' if any(r['sev'] >= 3 for r in rows) else ('warn' if affected else 'ok'))
    health_txt = {'ok': '정상', 'warn': '주의', 'high': '경고', 'crit': '위험'}[health]

    return (HEAD + f"""
<header>
  <div class="title"><span class="logo">◆</span><h1>D-State Fleet Monitor</h1>
    <span class="hb {health}">{health_txt}</span></div>
  <div class="meta">갱신: {esc(_to_kst(report.get('generated_at','')))}<span class="sep">·</span>주기 {esc(report.get('interval_min',30))}분</div>
</header>
<main>
<section class="cards">
  <div class="card"><div class="cl">스캔 호스트</div><div class="cv">{scanned}</div></div>
  <div class="card warn"><div class="cl">D 발생 호스트</div><div class="cv">{affected}</div></div>
  <div class="card crit"><div class="cl">도달불가</div><div class="cv">{len(unreachable)}</div></div>
  <div class="card"><div class="cl">총 D 프로세스</div><div class="cv">{total_d}</div></div>
  <div class="card crit"><div class="cl">확실히 stuck<span class="sub">즉시명령 · 2분+</span></div><div class="cv">{total_stuck}</div></div>
</section>
<section class="split">
  <div class="panel"><h3>원인 분포 <span class="muted2">wchan</span></h3><div class="bars">{bars}</div></div>
  <div class="panel"><h3>접속 많은 사용자 <span class="muted2">서버 로그인 기준</span></h3><div class="users">{users_panel}</div></div>
</section>
<div class="tools"><input id="f" placeholder="호스트 검색…" oninput="flt()"><span id="cnt" class="muted2"></span></div>
<div class="tablewrap"><table id="t"><thead><tr>
<th onclick="srt('s',1)">상태</th><th onclick="srt('t',1)">호스트</th>
<th>주 접속자</th><th>마지막 접속</th>
<th onclick="srt('d',0)" class="num">D수</th><th onclick="srt('k',0)" class="num">stuck</th>
<th>원인</th><th>상세</th>
</tr></thead><tbody>
{''.join(trs)}
</tbody></table></div>
<footer>"확실히 stuck" = 즉시 끝나야 할 명령(git/ls/du/sync)이 D로 머문 시간(데몬의 큰 나이는 제외). ·
주 접속자/마지막 접속은 서버 로그인 이력(last) 기준. · 원인이 NFS/VFS면 NFS 서버·마운트, 디스크면 dmesg·smartctl·df. · D 프로세스는 kill 불가 → 근본원인 회복 필요.</footer>
</main>
<div id="ov" onclick="closeDet()">
 <div id="dm" onclick="event.stopPropagation()">
  <div class="dh">
   <span id="dh-host"></span><span id="dh-ip" class="mono"></span>
   <span id="dh-cnt"></span>
   <button class="dc" onclick="closeDet()">✕</button>
  </div>
  <div class="di" id="di"></div>
  <div id="dp">
   <div class="dp-hdr"><span>나이</span><span>wchan</span><span>사용자</span><span>명령</span></div>
   <div id="dp-rows"></div>
  </div>
 </div>
</div>
""" + f"<script>var DET={json.dumps(det_data, ensure_ascii=False)};</script>" + SCRIPT)


HEAD = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><title>D-State Fleet Monitor</title>
<style>
:root{
 --bg:#0b0d11;--bg2:#0e1116;--surf:#14181f;--surf2:#171c24;--line:#222934;--line2:#2e3744;
 --txt:#e7eaf0;--mut:#8a93a3;--dim:#5b6573;
 --acc:#5b8def;--acc2:#3f6fd6;
 --ok:#34d399;--warn:#fbbf24;--high:#fb923c;--crit:#f87171;
 --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,"Helvetica Neue",sans-serif;
 --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
 --r:14px;--sh:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.22)}
*{box-sizing:border-box}
body{margin:0;background:
 radial-gradient(1100px 600px at 90% -10%,rgba(91,141,239,.10),transparent 60%),
 radial-gradient(800px 500px at -5% 0%,rgba(52,211,153,.05),transparent 55%),var(--bg);
 background-attachment:fixed;color:var(--txt);font-family:var(--sans);font-size:14px;line-height:1.55;
 -webkit-font-smoothing:antialiased;letter-spacing:.1px}
main{max-width:1280px;margin:0 auto;padding:0 26px 40px}
.mono{font-family:var(--mono)}
header{max-width:1280px;margin:0 auto;padding:26px 26px 18px}
.title{display:flex;align-items:center;gap:12px}
.logo{color:var(--acc);font-size:18px;filter:drop-shadow(0 0 8px rgba(91,141,239,.6))}
h1{font-size:19px;font-weight:650;margin:0;letter-spacing:-.2px}
.hb{font-size:12px;font-weight:600;padding:3px 12px;border-radius:999px;margin-left:4px}
.hb.ok{color:var(--ok);background:rgba(52,211,153,.12)}
.hb.warn{color:var(--warn);background:rgba(251,191,36,.12)}
.hb.high{color:var(--high);background:rgba(251,146,60,.13)}
.hb.crit{color:var(--crit);background:rgba(248,113,113,.14)}
.meta{color:var(--mut);font-size:12.5px;margin-top:8px}.meta .sep{margin:0 9px;color:var(--dim)}
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:8px 0 18px}
.card{background:var(--surf);border:1px solid var(--line);border-radius:var(--r);padding:18px 20px;
 box-shadow:var(--sh);transition:border-color .2s,transform .2s;animation:rise .5s both}
.card:hover{border-color:var(--line2);transform:translateY(-2px)}
.card .cl{color:var(--mut);font-size:12px;font-weight:500}.card .cl .sub{display:block;color:var(--dim);font-size:10.5px;margin-top:1px}
.card .cv{font-size:34px;font-weight:680;margin-top:8px;letter-spacing:-1px;font-variant-numeric:tabular-nums}
.card.warn .cv{color:var(--warn)}.card.crit .cv{color:var(--crit)}
.cards .card:nth-child(2){animation-delay:.05s}.cards .card:nth-child(3){animation-delay:.1s}
.cards .card:nth-child(4){animation-delay:.15s}.cards .card:nth-child(5){animation-delay:.2s}
@keyframes rise{from{opacity:0;transform:translateY(10px)}}
.split{display:grid;grid-template-columns:1.25fr 1fr;gap:14px;margin-bottom:18px}
.panel{background:var(--surf);border:1px solid var(--line);border-radius:var(--r);padding:18px 20px;box-shadow:var(--sh);animation:rise .5s .12s both}
.panel h3{margin:0 0 14px;font-size:13px;font-weight:600;color:var(--txt)}
.muted2{color:var(--dim);font-weight:400;font-size:11.5px}
.bar{display:grid;grid-template-columns:120px 1fr 40px;align-items:center;gap:12px;padding:5px 0}
.bn{color:var(--mut);font-size:12.5px;display:flex;align-items:center;gap:7px}
.bk{width:9px;height:9px;border-radius:3px;flex:none}
.btrack,.utrack{height:8px;background:var(--bg2);border-radius:999px;overflow:hidden;border:1px solid var(--line)}
.bf{display:block;height:100%;border-radius:999px}
.bv,.uv{text-align:right;font-variant-numeric:tabular-nums;color:var(--txt);font-size:12.5px}
.nfs{background:var(--acc)}.disk{background:var(--high)}.lock{background:#a78bfa}.zfs{background:var(--ok)}.etc{background:var(--dim)}
.users{display:flex;flex-direction:column;gap:8px}
.urow{display:grid;grid-template-columns:140px 1fr 64px;align-items:center;gap:12px}
.un{font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.utrack i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--acc2),var(--acc))}
.uv small{color:var(--dim)}
.tools{display:flex;align-items:center;gap:14px;margin-bottom:10px}
#f{background:var(--surf);border:1px solid var(--line2);color:var(--txt);font-family:var(--sans);font-size:13px;
 padding:9px 14px;border-radius:10px;width:280px;outline:none;transition:border-color .2s}
#f:focus{border-color:var(--acc)}#f::placeholder{color:var(--dim)}
.tablewrap{background:var(--surf);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;box-shadow:var(--sh)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:11px 16px;vertical-align:middle}
th{position:sticky;top:0;background:var(--surf2);color:var(--mut);font-weight:600;font-size:11.5px;
 cursor:pointer;user-select:none;border-bottom:1px solid var(--line2);letter-spacing:.2px}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
tbody tr{border-top:1px solid var(--line);transition:background .15s}
tbody tr:first-child{border-top:none}
tbody tr:hover{background:var(--surf2)}
td.h{font-weight:650}
td.reg{color:var(--txt)}td.last b{font-weight:600}td.last .when{display:block;color:var(--dim);font-size:11px;margin-top:1px}
td.sn{color:var(--crit);font-weight:700}
.pill{font-size:11px;font-weight:600;padding:3px 11px;border-radius:999px;white-space:nowrap;display:inline-block}
.pill.ok{color:var(--ok);background:rgba(52,211,153,.12)}
.pill.warn{color:var(--warn);background:rgba(251,191,36,.12)}
.pill.high{color:var(--high);background:rgba(251,146,60,.13)}
.pill.crit{color:var(--crit);background:rgba(248,113,113,.14)}
.chip{font-size:11px;font-weight:500;padding:3px 10px;border-radius:8px;background:var(--bg2);color:var(--mut);white-space:nowrap;border:1px solid var(--line)}
.chip[data-k=nfs]{color:var(--acc);background:rgba(91,141,239,.1);border-color:transparent}
.chip[data-k=disk]{color:var(--high);background:rgba(251,146,60,.1);border-color:transparent}
.chip[data-k=lock]{color:#a78bfa;background:rgba(167,139,250,.1);border-color:transparent}
.rb{margin-left:9px;background:transparent;border:1px solid var(--line2);color:var(--acc);border-radius:7px;
 cursor:pointer;font-size:12px;padding:2px 8px;transition:all .15s}.rb:hover{background:rgba(91,141,239,.12);border-color:var(--acc)}
.muted{color:var(--dim)}
footer{color:var(--dim);font-size:11.5px;margin-top:18px;line-height:1.8;padding:0 2px}
@media(max-width:880px){.cards{grid-template-columns:repeat(2,1fr)}.split{grid-template-columns:1fr}}
.db{background:transparent;border:1px solid var(--acc);color:var(--acc);border-radius:7px;cursor:pointer;font-size:12px;padding:3px 10px;font-weight:500;transition:all .15s}.db:hover{background:rgba(91,141,239,.12)}
#ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:200;align-items:center;justify-content:center}
#ov.open{display:flex}
#dm{background:var(--surf);border-radius:var(--r);border:1px solid var(--line);width:min(940px,96vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 28px 80px rgba(0,0,0,.5)}
.dh{display:flex;align-items:center;gap:12px;padding:16px 22px;border-bottom:1px solid var(--line);flex-shrink:0}
#dh-host{font-weight:700;font-size:16px}#dh-ip{font-size:12px;color:var(--dim)}
#dh-cnt{margin-left:auto;font-size:12px;color:var(--mut)}
.dc{background:transparent;border:none;color:var(--dim);cursor:pointer;font-size:20px;padding:4px 8px;line-height:1;transition:color .1s}.dc:hover{color:var(--txt)}
.di{display:grid;grid-template-columns:130px 1fr;gap:5px 16px;padding:14px 22px;font-size:12.5px;border-bottom:1px solid var(--line);flex-shrink:0}
.di .dl{color:var(--dim)}.di .dv{color:var(--txt)}
#dp{overflow:auto;flex:1}
.dp-hdr,.dp-row{display:grid;grid-template-columns:80px 200px 120px 1fr;gap:10px;padding:5px 18px;font-family:var(--mono);font-size:11px;border-bottom:1px solid var(--line)}
.dp-hdr{font-size:10px;color:var(--dim);position:sticky;top:0;background:var(--surf);text-transform:uppercase;letter-spacing:.05em}
.dp-row{color:var(--mut)}.dp-row:last-child{border-bottom:none}.dp-row.st{background:rgba(248,113,113,.06)}
.dp-age{color:var(--high);text-align:right}.dp-wch{color:var(--acc)}.dp-usr{color:var(--txt)}.dp-ar{word-break:break-all}
</style></head><body>"""

SCRIPT = """<script>
function flt(){var q=document.getElementById('f').value.toLowerCase(),n=0,rs=document.querySelectorAll('#t tbody tr');
rs.forEach(function(r){var m=r.getAttribute('data-host').toLowerCase().indexOf(q)>=0;r.style.display=m?'':'none';if(m)n++;});
document.getElementById('cnt').textContent=n+' / '+rs.length+' 호스트';}
var _sd={};
function srt(key,txt){var tb=document.querySelector('#t tbody'),rs=[].slice.call(tb.querySelectorAll('tr'));
var a={s:'data-sev',t:'data-host',d:'data-d',k:'data-stuck'}[key];_sd[key]=!_sd[key];var dir=_sd[key]?1:-1;
rs.sort(function(x,y){var vx=x.getAttribute(a),vy=y.getAttribute(a);return txt?dir*vx.localeCompare(vy):dir*((+vx)-(+vy));});
rs.forEach(function(r){tb.appendChild(r);});}
function rescan(btn,host){btn.textContent='…';btn.disabled=true;
fetch('api/rescan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({host:host})})
.then(function(r){return r.json();}).then(function(d){
if(d.error){btn.textContent='!';btn.title=d.error;btn.disabled=false;return;}
if(d.timeout){btn.textContent='⏱';btn.title='타임아웃';btn.disabled=false;return;}
window.location.reload();
}).catch(function(e){btn.textContent='!';btn.title=''+e;btn.disabled=false;});}
function _e(s){var d=document.createElement('div');d.textContent=String(s||'');return d.innerHTML;}
function openDet(h){
var d=DET[h];if(!d)return;
document.getElementById('dh-host').textContent=h;
document.getElementById('dh-ip').textContent=' '+d.ip;
document.getElementById('dh-cnt').textContent='D '+d.dc+'개  stuck '+d.sk+'개';
document.getElementById('di').innerHTML=
 '<span class="dl">주 접속자</span><span class="dv">'+_e(d.freq)+'</span>'+
 '<span class="dl">대표 명령</span><span class="dv mono">'+_e(d.rep)+'</span>';
document.getElementById('dp-rows').innerHTML=d.ps.map(function(p){
 return '<div class="dp-row'+(p.st?' st':'')+'"><span class="dp-age">'+_e(p.ag)+'</span>'+
  '<span class="dp-wch">'+_e(p.wc)+'</span><span class="dp-usr">'+_e(p.us)+'</span>'+
  '<span class="dp-ar">'+_e(p.ar)+'</span></div>';
}).join('');
document.getElementById('ov').classList.add('open');}
function closeDet(){document.getElementById('ov').classList.remove('open');}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDet();});
flt();
</script></body></html>"""


def main():
    rp = sys.argv[1] if len(sys.argv) > 1 else 'report.json'
    out = sys.argv[2] if len(sys.argv) > 2 else 'index.html'
    with open(rp, encoding='utf-8') as f:
        report = json.load(f)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(build(report))
    print(f"rendered {out} (hosts={len(report.get('hosts',{}))} unreachable={len(report.get('unreachable',[]))})")


if __name__ == '__main__':
    main()
