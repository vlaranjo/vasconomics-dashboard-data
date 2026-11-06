# vasconomics-dashboard-data

Repo for Vasconomic's Dashboard Data

Scheduled jobs and the published JSON for the Vasconomics macro dashboard (Milestone 1). Public, data only.
`data/` is exactly what GitHub Pages serves. Plans and decisions live in the front-end repo's `docs/`.

## What runs

| Workflow | When (UTC) | What |
|---|---|---|
| `markets` | 22:37 Mon-Fri, repair 05:47 Tue-Sat, manual | Yahoo -> returns (D7 rule) -> validate -> atomic swap of `data/` -> one commit -> Pages deploy |
| `pe` | Sunday 03:07, manual | worldperatio.com (plain HTTP) -> validate -> atomic swap -> commit -> deploy |
| `yields` | Monday 15:47, manual | Official yield-curve sources for 8 countries (+ France when the secret `FR_WEBSTAT_CLIENT_ID` exists, adapter untested) -> four curves per country -> validate -> atomic swap -> commit -> deploy. One country failing keeps its last good file and marks it stale. |
| `probe-sources` | manual only | Fetches one item from Yahoo, worldperatio and every yield-curve source and reports reachability. Publishes nothing. |
| `pages-deploy` | called by the three above; on push to `main` touching `data/**` | Deploys `data/` to Pages. Only ever from `main`. |

A manual run on a branch other than `main` commits to that branch and does not deploy.
No failure emails: staleness is shown on the page. A run fails only on a validation failure or when nothing could be fetched.

## Local use

```
pip install -r requirements-dev.txt
python -m pytest tests -q                 # unit tests, no network
python jobs/run_markets.py --today 2026-11-04
python jobs/run_pe.py
python jobs/run_yields.py                 # weekly yield curves (network)
python jobs/probe_sources.py              # reachability from this machine
```

`config/universe.yaml` lists the funds (labels, ISIN, Acc, EUR-hedged); `config/pe_index_map.yaml` lists the P/E indices.
No secrets are used anywhere: the built-in `GITHUB_TOKEN` covers commits and Pages.

Price data: Yahoo Finance. P/E data: worldperatio.com.
