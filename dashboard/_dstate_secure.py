#!/usr/bin/env python3
# nginx.conf: /dstate/ 를 http→https 리다이렉트(:80) + Basic인증·보안헤더 프록시(:443)로 설정. 멱등.
import re, shutil
P = "/opt/dstate-monitor-proxy/nginx.conf"
shutil.copy2(P, P + ".bak-auth")
s = open(P).read()
# 기존 /dstate location 제거(멱등 재적용)
s = re.sub(r"\n[ \t]*location[ \t]*=?[ \t]*/dstate/?[ \t]*\{[^}]*\}", "", s)
redirect = ("\n    location = /dstate { return 301 https://$host/dstate/; }"
            "\n    location /dstate/ { return 301 https://$host$request_uri; }")
proxy = ("\n    location /dstate/ {"
         "\n        allow 127.0.0.1;"           # localhost
         "\n        allow 10.0.0.0/8;"          # example private network
         "\n        deny all;"                  # block everything else
         "\n        auth_basic \"D-State Monitor\";"
         "\n        auth_basic_user_file /etc/nginx/dstate.htpasswd;"
         "\n        add_header X-Frame-Options DENY always;"
         "\n        add_header X-Content-Type-Options nosniff always;"
         "\n        add_header Referrer-Policy no-referrer always;"
         "\n        proxy_pass http://127.0.0.1:8090/;"
         "\n        proxy_set_header Host $host;"
         "\n        proxy_set_header X-Real-IP $remote_addr;"
         "\n    }")
cnt = [0]
def repl(m):
    cnt[0] += 1
    return m.group(1) + (redirect if cnt[0] == 1 else proxy)
s = re.sub(r"(server_name\s+_;)", repl, s, count=2)
open(P, "w").write(s)
print("NGINX_OK servers=%d redirect=%d auth=%d" %
      (cnt[0], s.count("$host$request_uri"), s.count("auth_basic_user_file")))

# docker-compose 에 htpasswd 영구 마운트(멱등; 지금 recreate는 안 함, docker cp로 즉시 반영)
CP = "/opt/dstate-monitor-proxy/docker-compose.yml"
c = open(CP).read()
if "dstate.htpasswd" not in c:
    shutil.copy2(CP, CP + ".bak-dstate")
    anchor = "      - /opt/monitor-host/tls:/etc/nginx/tls:ro"
    c = c.replace(anchor, anchor + "\n      - ./dstate.htpasswd:/etc/nginx/dstate.htpasswd:ro", 1)
    open(CP, "w").write(c)
    print("COMPOSE_MOUNT_ADDED")
else:
    print("COMPOSE_MOUNT_PRESENT")
