import json, render_dashboard as r
d = json.load(open("report.json"))
print("source:", d.get("source"))
hl = [l for h in d["hosts"].values() for l in h.get("lines", [])]
print("LOGINS 라인 총:", sum(1 for l in hl if l.startswith("LOGINS")),
      "LASTHOST:", sum(1 for l in hl if l.startswith("LASTHOST")))
# LOGINS 샘플 5줄
print("LOGINS 샘플:", [l for l in hl if l.startswith("LOGINS")][:6])
# 한 호스트 host_summary
for name, h in d["hosts"].items():
    if any(l.startswith("LOGINS") for l in h.get("lines", [])):
        s = r.host_summary(name, h)
        print("host", name, "regular_user=", repr(s["regular_user"]), "login_freq=", s["login_freq"], "last_user=", repr(s["last_user"]))
        break
