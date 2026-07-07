import awx_pull as a, time
c = a._cfg()
l = a.api(c, "POST", "/api/v2/job_templates/%s/launch/" % c['jt'], {})
jid = l.get("id") or l.get("job")
print("launched full-fleet job #%s (limit=%r)" % (jid, l.get("limit") or ""))
for _ in range(70):
    d = a.api(c, "GET", "/api/v2/jobs/%s/" % jid)
    st = d.get("status")
    if st in ("successful", "failed", "error", "canceled"):
        hosts = (d.get("artifacts") or {}).get("dstate_hosts") or {}
        hl = [x for h in hosts.values() for x in h.get("lines", [])]
        print("done #%s status=%s hosts=%d LOGINS=%d" % (jid, st, len(hosts), sum(1 for x in hl if x.startswith("LOGINS"))))
        break
    time.sleep(3)
