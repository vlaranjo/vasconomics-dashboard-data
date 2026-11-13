# vasconomics-dashboard-data

Repo for Vasconomic's Dashboard Data

Scheduled jobs and the published JSON for the Vasconomics macro dashboard (Milestone 1). Public, data only.
`data/` is exactly what GitHub Pages serves. Plans and decisions live in the front-end repo's `docs/`.

## What runs

| Workflow | When (UTC) | What |
|---|---|---|
| `markets` | 17:47, 19:47 and 22:37 Mon-Fri; 05:47 and 11:47 Tue-Sat (five slots because GitHub starts runs hours late; a run with nothing newer keeps the published data); manual | Yahoo -> returns (D7 rule) -> validate -> atomic swap of `data/` -> one commit -> Pages deploy |
| `pe` | Sunday 03:07, manual | worldperatio.com (plain HTTP) -> validate -> atomic swap -> commit -> deploy |
| `yields` | Saturday 06:47 (Friday's closing quotes everywhere), manual | 18 countries (China, Poland, Portugal, Russia, Turkey and South Africa included) from worldgovernmentbonds.com, each page read in a headless Chromium (Playwright; browser defaults, one page at a time, 5 s apart): latest = the table's Last, 1 month, 6 months and 1 year earlier = Last minus its change columns. Per country, `config/yields.yaml` `source:` can switch back to the official adapter (treasuries, central banks; France needs the secret `FR_WEBSTAT_CLIENT_ID`) -> four curves per country -> validate -> atomic swap -> commit -> deploy. One country failing keeps its last good file and marks it stale; a challenge page stops every further page load of the site. |
| `volatility` | the markets slots (22:37 Mon-Fri is the main one); manual | ^VIX, ^SKEW, ^MOVE from Yahoo (completed bars only: the day's bar from 22:15 UTC) and the VIX futures curve from Cboe (plain HTTP: the contract list JSON, the live contracts' settlement CSVs, the day's settlement file) -> summary table, history charts, four curves, daily slope -> validate -> atomic swap -> commit -> deploy. The term-structure source is one config line, `vx_term_source: cboe | yahoo` (default cboe; yahoo = ^VIX9D, ^VIX, ^VIX3M, ^VIX6M, ^VIX1Y by horizon, a ticker without history left out). Files in `data/volatility/`; `vx-history.json` is the job's memory (daily slope since May 2013, last 400 days of curves). A bot check stops every further Cboe request; the last good files are kept, marked stale. |
| `probe-sources` | manual only | Fetches one item from Yahoo, worldperatio, Cboe and every yield-curve source and reports reachability. Publishes nothing. |
| `pages-deploy` | called by the four above; on push to `main` touching `data/**` | Deploys `data/` to Pages. Only ever from `main`. |

Each workflow has its own concurrency group. After a job, `jobs/commit_data.py` commits only when the published data really changed (plus about one heartbeat commit a day, for the 60-day keep-alive; `pe` and `yields` count each successful weekly refresh as a change), merges `manifest.json` and `status.json` by ownership if another job pushed first, and the Pages deploy runs only when something was committed.

A manual run on a branch other than `main` commits to that branch and does not deploy.
No failure emails: staleness is shown on the page. A run fails only on a validation failure or when nothing could be fetched.

## Local use

```
pip install -r requirements-dev.txt
python -m pytest tests -q                 # unit tests, no network
python jobs/run_markets.py --today 2026-11-04
python jobs/run_pe.py
python -m playwright install chromium     # once, for the yields job
python jobs/run_yields.py                 # weekly yield curves (network; --headed shows the browser)
python jobs/run_volatility.py             # volatility indices and VIX futures (network; --cache-dir keeps expired contracts' CSVs locally)
python jobs/probe_sources.py              # reachability from this machine
```

`config/universe.yaml` lists the funds (labels, ISIN, Acc, EUR-hedged); `config/pe_index_map.yaml` lists the P/E indices.
One optional secret, `FR_WEBSTAT_CLIENT_ID` (France's official adapter, off by default since round 17; passed only to the yields step). The built-in `GITHUB_TOKEN` covers commits and Pages.

Price data: Yahoo Finance. P/E data: worldperatio.com. Yield curves: World Government Bonds (worldgovernmentbonds.com). VIX futures: Cboe (published by the owner's decision, knowing Cboe's terms; decisions round 20). Fallback: `vx_term_source: yahoo` in `config/volatility.yaml` uses the VIX indices on Yahoo instead.
