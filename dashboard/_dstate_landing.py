#!/usr/bin/env python3
# landing.html 에 D-State 카드 추가 (기존 카드 양식 복제). 멱등.
import shutil
P = "/opt/dstate-monitor-proxy/landing.html"
s = open(P).read()
if "/dstate/" in s:
    print("LANDING_ALREADY"); raise SystemExit
shutil.copy2(P, P + ".bak-dstate")
card = (
    '      <a class="service dstate" href="https://monitor.example.com/dstate/">\n'
    '        <span class="icon" aria-hidden="true">D</span>\n'
    '        <span>\n'
    '          <h2>D-State Fleet Monitor</h2>\n'
    '          <p>전 서버 D-state(I/O hang) 프로세스를 30분 주기로 보는 모니터링 대시보드입니다.</p>\n'
    '        </span>\n'
    '        <span class="target">https://monitor.example.com/dstate/</span>\n'
    '      </a>\n\n'
)
s = s.replace("    </section>", card + "    </section>", 1)
open(P, "w").write(s)
print("LANDING_OK")
