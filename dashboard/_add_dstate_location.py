#!/usr/bin/env python3
# /opt/dstate-monitor-proxy/nginx.conf 에 /dstate/ location 추가 (각 server 블록).
# 백업 후 편집. 멱등(이미 있으면 skip). nginx -t/reload 는 호출측에서.
import re, sys, shutil
P = "/opt/dstate-monitor-proxy/nginx.conf"
BAK = P + ".bak-dstate"
s = open(P).read()
if "/dstate/" in s:
    print("ALREADY_PRESENT"); sys.exit(0)
shutil.copy2(P, BAK)
block = (
    "\n    location /dstate/ {"
    "\n        proxy_pass http://127.0.0.1:8090/;"
    "\n        proxy_set_header Host $host;"
    "\n        proxy_set_header X-Real-IP $remote_addr;"
    "\n    }"
)
new = re.sub(r"(server_name\s+_;)", lambda m: m.group(1) + block, s)
open(P, "w").write(new)
print("INSERTED %d /dstate/ block(s); backup=%s" % (new.count("/dstate/"), BAK))
