import awx_pull as a
c = a._cfg()
d = a.api(c, "GET", "/api/v2/jobs/335/")
print("status:", d.get("status"), "| explanation:", (d.get("job_explanation") or "")[:200])
tb = d.get("result_traceback") or ""
if tb: print("traceback:", tb[:600])
