import awx_pull as a
c = a._cfg(); jt = c['jt']
r = a.api(c, "GET", "/api/v2/job_templates/%s/jobs/?order_by=-id&page_size=12" % jt)
print("recent JT#%s jobs (id status limit finished):" % jt)
for j in r.get("results", []):
    print("  ", j["id"], j.get("status"), "limit=%r" % (j.get("limit") or ""), j.get("finished"))
for j in r.get("results", []):
    d = a.api(c, "GET", "/api/v2/jobs/%s/" % j["id"])
    hosts = (d.get("artifacts") or {}).get("dstate_hosts") or {}
    hl = [l for h in hosts.values() for l in h.get("lines", [])]
    nlog = sum(1 for l in hl if l.startswith("LOGINS"))
    print("  job#%s hosts=%d LOGINS=%d limit=%r" % (j["id"], len(hosts), nlog, j.get("limit") or ""))
