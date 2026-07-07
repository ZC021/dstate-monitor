# AWX setup

This directory contains the read-only scan playbook and a synthetic demo inventory.

## Demo inventory

`inventory.demo.yml` is safe sample data:

```bash
ansible-inventory -i awx/inventory.demo.yml --list
```

In production, use your private AWX inventory and machine credential. Do not commit real inventory files, hostnames, IPs, SSH keys, or vault files.

## Job Template

Create an AWX Job Template similar to:

| Field | Example |
|---|---|
| Name | `dstate-fleet-scan` |
| Inventory | demo inventory or your private fleet inventory |
| Project | project containing `awx/dstate_scan.yml` |
| Playbook | `awx/dstate_scan.yml` |
| Credential | normal SSH machine credential |
| Privilege Escalation | off |
| Concurrent jobs | off |
| Forks | `30` or suitable for your fleet |
| Job timeout | `600` seconds |
| Prompt on launch: Limit | on, if using single-host rescan |

Schedule it every 30 minutes or whatever cadence fits your fleet.

## Validate one launch

After launching once, check the job detail API for:

```text
artifacts.dstate_hosts
```

Each host should contain `lines` beginning with `RC=0` or `RC=124` when the local `ps` command timed out.

## Dashboard values

The dashboard host needs private config like:

```bash
AWX_BASE_URL=https://awx.example.com
AWX_TOKEN=<redacted>
AWX_VERIFY_SSL=true
DSTATE_JT_ID=123
```

Keep that in `dashboard/config.env` and out of git.
