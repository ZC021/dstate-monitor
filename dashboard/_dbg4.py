import json, render_dashboard as r
d = json.load(open("report.json"))
for name, h in d["hosts"].items():
    s = r.host_summary(name, h)
    if "scanner" in (s["regular_user"] or "") or any("scanner"==u for _,u in s["login_freq"]):
        print("host:", name, "regular_user:", repr(s["regular_user"]), "login_freq:", s["login_freq"])
