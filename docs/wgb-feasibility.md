# worldgovernmentbonds.com as a replacement yield source: feasibility check

Checked 11 November 2026 (evening, UTC) from this PC (Portugal). Feasibility only: nothing was built, no job or front-end code
changed. Plain HTTP requests (Python `requests`), one at a time, at least 3.2 seconds apart, User-Agent
`vasconomics-dashboard feasibility check/1.0 (personal, non-commercial; one-off manual check, ~3 s between requests)`, no
cookie jar kept, no browser automation. **4 requests in total**; the check stopped at the first refusal, as instructed.

## Verdict: not feasible

The site's yields are not in its HTML. Every country page loads them from one JSON endpoint,
`POST https://www.worldgovernmentbonds.com/wp-json/country/v1/main`, and that endpoint **refused a plain request with HTTP 403
`{"code":"rest_forbidden","message":"Access denied: invalid origin"}`**. It accepts only requests that carry the site's own
browser origin. Sending that `Origin` header from a script would mean pretending to be the site's own page, which is the kind
of workaround the rules exclude, so the check stopped there. Without that endpoint there is no data to read: no tenors, no
history, no dates.

Even if access were possible, the site would not meet the dashboard's rule of **official sources only**. By its own account
the figures come from Investing.com and TradingEconomics.com, both commercial data vendors (Investing.com was dropped in round 1
for that reason). Its terms state "© 2026 World Government Bonds. All rights reserved" with no reuse permission. So it would
replace official central-bank and treasury figures with a third-party copy of vendor data, under an all-rights-reserved notice.

## Findings, question by question

1. **Access.**
   - `robots.txt` (HTTP 200, 185 bytes, a Yoast block): `User-agent: *` with an empty `Disallow:`, so nothing is disallowed.
     It points to `http://www.worldgovernmentbonds.com/sitemap_index.xml` (not fetched).
   - The country page `https://www.worldgovernmentbonds.com/country/united-states/` answers a plain GET (HTTP 200, 48 KB,
     Apache, `Cache-Control: max-age=60, private, proxy-revalidate`, `X-Cache: MISS`). It has no challenge page, but it
     **contains no yields**: every data block reads "Loading data / Please wait". The numbers are filled in by JavaScript.
   - The page sets `jsGlobalVars = {"FUNCTION":"Country","DOMESTIC":true,"ENDPOINT":".../wp-json/country/v1/main",
     "DATE_RIF":"2099-12-31","COUNTRY1":{"SYMBOL":"6","PAESE":"United States",...}}` and its script `country_main()` posts
     `{"GLOBALVAR": jsGlobalVars}`. That call is made by `ac_callJsonPost` / `ac_fetchJsonPost` in
     `/wp-content/themes/acgpt-child/js/myLayout.js` (`fetch(endpoint, {method: "POST", body: JSON.stringify(...),
     headers: {"Content-type": "application/json; charset=UTF-8"}})`). There is no token or nonce in the page or the script.
   - That same POST from a plain client returned **HTTP 403, "Access denied: invalid origin"**: the server checks the request's
     origin. **Blocking response, stopped.**
   - Rate-limit headers: none seen (no `RateLimit-*`, `Retry-After` or Cloudflare headers on any response). The site runs on
     Apache with a page cache (`X-Cache`, `X-Cache-Hits`).
   - `DATE_RIF: "2099-12-31"` suggests the same endpoint serves past dates when given another reference date. That would be the
     history mechanism, but it could not be tested.
2. **Coverage (our 13 countries x 8 tenors): unknown.** The tenor list, the values and the bond list all come from the refused
   endpoint. The static page names only the sections ("United States Yield Curve", "Yield History", "Government Bonds Prices",
   "Credit Ratings", "10 Year Bond Yield Spread"). The sitemap might list per-bond pages, but it was not read after the refusal.
3. **History: unknown.** The page's "Yield History" table is described as "historical values of the yield curve, with data
   points collected at the end of each year" (yearly, not monthly or daily). That alone would not give the 1-month and
   3-month-earlier curves. Any finer history would come from the refused endpoint (`DATE_RIF`) or from chart data, also loaded
   by script.
4. **Freshness: unknown.** No date or time is in the static HTML. The page's meta text says only "Updated Government Bonds
   data and yield curves". Whether values are intraday quotes or closes could not be seen.
5. **Quality against our official values for 30 Oct 2026: not possible.** No value was obtained from the site, so there is
   nothing to compare.
6. **Cost of a weekly job: not applicable** (the endpoint refuses plain requests). For scale only: with the endpoint open, the
   current curves would cost at least one POST per country (13), and the three earlier curves possibly one POST per country per
   date (about 52 in all), all parsed from the site's private JSON, which is undocumented and could change without notice.
7. **Credits: nothing found on the page.** The static HTML carries no source or credit line for the figures, and no clause on
   crediting or linking. The terms page (as you read it) says "© 2026 World Government Bonds. All rights reserved" and credits
   Investing.com and TradingEconomics.com. The right source line would have been "Source: World Government Bonds (data from
   Investing.com and TradingEconomics.com)", but an all-rights-reserved notice gives no permission to republish at all.

## Request log

No cookies or request headers are recorded here. "Size" is the response body in bytes.

| # | Request | Status | Size | Type | Notes |
|---|---|---|---|---|---|
| 1 | `GET https://www.worldgovernmentbonds.com/robots.txt` | 200 | 185 | text/plain | Allows everything |
| 2 | `GET https://www.worldgovernmentbonds.com/country/united-states/` | 200 | 47,990 | text/html | No yields in the HTML; data loaded by script |
| 3 | `GET https://www.worldgovernmentbonds.com/wp-content/themes/acgpt-child/js/myLayout.js?ver=2.2.11` | 200 | 23,855 | text/javascript | Shows how the page calls the endpoint (plain JSON POST, no token) |
| 4 | `POST https://www.worldgovernmentbonds.com/wp-json/country/v1/main` with `{"GLOBALVAR": <the page's jsGlobalVars>}` | **403** | 89 | application/json | `rest_forbidden`, "Access denied: invalid origin". **Stopped here.** |

## What would change the verdict

Only written permission from the site's owner together with a supported way in (an API or a file meant for reuse). Even then,
the data would be a copy of Investing.com and TradingEconomics.com figures, not official ones. The official sources already in
the job (treasuries, central banks and debt offices) remain the right basis. Their gaps (UK 1M/3M, France 1M/6M, Australia
1M-6M, China) are documented in `yield-sources.md` on the front-end repo.
