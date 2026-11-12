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

## Round 2: browser (11 November 2026, evening)

Your new rules applied:
- a real Chromium (Playwright 1.62.0), each country page loaded normally, and the table the page itself displays read from
  the rendered HTML;
- the site's JSON endpoint never called directly;
- no header, user agent or cookie set by us: the browser's defaults only, with a fresh profile per run;
- one page at a time, at least 5 seconds apart;
- stop at any challenge, captcha or 403.

`robots.txt` was re-checked in the browser first and is unchanged (`User-agent: *`, empty `Disallow:`).

**Result: pass.**
- Every page loaded without a challenge, captcha or 403, both headed and headless. The page's own data request answered 200
  every time.
- 11 of 13 countries give 6 or more of our 8 tenors.
- The quality check shows two values just above 15 bp at 2Y or longer: UK 3Y and France 3Y, both +17 bp. Both are explained
  by what is being compared: a single benchmark bond against a fitted or interpolated official curve, plus a one-day date
  difference. Nothing is unexplained.

Part 2 was built.

### Page loads

| # | Mode | Pages | Result |
|---|---|---|---|
| 1-14 | headed | `robots.txt`, then the 13 country pages | all HTTP 200, no challenge text, page data request 200 |
| 15-16 | headed | `bond-historical-data/united-states/10-years/`, `.../germany/10-years/` | HTTP 200; their history is an interactive chart filled by script, not a table, so they were not used |
| 17-29 | headless | the 13 country pages | all HTTP 200, no challenge; tables identical to the headed run |
| 30-42 | headless | the 13 country pages, loaded by the new job into `data-local/` | all HTTP 200, 13 countries published |

For the official comparison data, the check made plain requests, as the job's own adapters make them:
- the Ministry of Finance Japan's current-month curve file (`jgbcme.csv`), twice;
- the SNB cube for October, twice.

### a. Coverage of our 8 tenors

| Country | Tenors | Ours | Other rows on the page |
|---|---|---|---|
| United States | 1M 3M 6M 1Y 3Y 5Y 10Y 30Y | 8 | 2M, 4M, 2Y, 7Y, 20Y |
| United Kingdom | 1M 3M 6M 1Y 3Y 5Y 10Y 30Y | 8 | 2Y, 4Y, 6-9Y, 12Y, 15Y, 20Y, 25Y, 40Y, 50Y |
| Canada | 1M 3M 6M 1Y 3Y 5Y 10Y 30Y | 8 | 2M, 2Y, 4Y, 7Y, 20Y |
| Japan | 1M 3M 6M 1Y 3Y 5Y 10Y 30Y | 8 | 9M, 2Y, 4Y, 6-9Y, 15Y, 20Y, 40Y |
| Germany | 3M 6M 1Y 3Y 5Y 10Y 30Y | 7 (no 1M) | 9M, 2Y, 4Y, 6-9Y, 15Y, 20Y, 25Y |
| France | 1M 3M 6M 1Y 3Y 5Y 10Y 30Y | 8 | 9M, 2Y, 4Y, 6-9Y, 15Y, 20Y, 25Y, 50Y |
| Spain | 1M 3M 6M 1Y 3Y 5Y 10Y 30Y | 8 | 9M, 2Y, 4Y, 6-9Y, 15Y, 20Y, 25Y |
| Switzerland | 1M 3M 6M 1Y 3Y 5Y 10Y 30Y | 8 | 2M, 2Y, 4Y, 6-9Y, 15Y, 20Y, 40Y |
| Brazil | 3M 6M 1Y 3Y 5Y 10Y | 6 (no 1M, 30Y) | 9M, 2Y, 8Y |
| Italy | 1M 3M 6M 1Y 3Y 5Y 10Y 30Y | 8 | 9M, 2Y, 4Y, 6-9Y, 15Y, 20Y, 25Y, 50Y |
| Australia | 1Y 3Y 5Y 10Y 30Y | 5 (no 1M, 3M, 6M) | 2Y, 4Y, 6-9Y, 12Y, 15Y, 20Y |
| India | 3M 6M 1Y 3Y 5Y 10Y 30Y | 7 (no 1M) | 2Y, 4Y, 6-9Y, 11-15Y, 19Y, 24Y, 40Y |
| China | 1Y 3Y 5Y 10Y 30Y | 5 (no 1M, 3M, 6M) | 2Y, 7Y, 15Y, 20Y |

One oddity on the site, in a tenor we don't use: Japan's 15Y row read 4.182%, between a 10Y of 2.779% and a 20Y of 3.674%.

### b. Units and sign of the change columns

The cells state their unit ("-7.2 bp", "+29.0 bp"), so the changes are in **basis points**.

The sign convention was tested on every tenor where we hold an official value for the earlier date (our own curves of 9-11
October 2026 and 9-11 November 2025). **Chg = Last minus the value that long ago**, so earlier = Last - Chg. The table gives
the error in bp of "Last - Chg" and of "Last + Chg" against the official value:

| Country, horizon | Tenors (Last - Chg / Last + Chg) |
|---|---|
| US, 1 month (Treasury, 9 Oct) | 6M +0/+19, 1Y -1/+18, 3Y +4/-23, 5Y +0/-38, **10Y +2/-51**, 30Y -0/-48 |
| US, 12 months (Treasury, 10 Nov 2025) | 1Y +1/+178, 3Y +4/+242, 5Y -0/+222, **10Y -6/+180**, 30Y +0/+129 |
| Germany, 1 month (Bundesbank, 9 Oct) | 6M -4/+14, 1Y -11/+32, **3Y +1/-5**, 5Y +3/-16, 10Y -4/-37, 30Y -8/-46 |
| Germany, 12 months (Bundesbank, 11 Nov 2025) | 6M -1/+172, 1Y -6/+223, 3Y -3/+211, **5Y +1/+178**, 10Y -9/+125 |
| Canada, 1 month (Bank of Canada, 9 Oct) | 1M +2/+42, 3M +0/+42, 6M +1/+45, 1Y +0/+29, 3Y -2/+3, 5Y +1/-17, 10Y +2/-30 |
| Spain, 12 months (Banco de Espana, Nov 2025) | 6M +3/+178, 3Y +1/+225, 5Y -8/+196, 10Y -2/+142 |
| UK, 12 months (Bank of England, 10 Nov 2025) | 1Y -1/+199, 3Y +2/+239, 5Y -4/+210, 10Y -14/+156, 30Y -20/+72 |

The unit tests use these worked examples:
- **US 10Y, Chg 1M:** Last 4.998%, Chg 1M -26.4 bp gives 5.262% one month earlier. The Treasury's 10-year par yield on 9 Oct
  2026 was 5.24%. Last + Chg would give 4.734%.
- **US 10Y, Chg 12M:** Chg 12M +92.9 bp gives 4.069%. The Treasury's value on 10 Nov 2025 was 4.13%.
- **Germany 3Y, Chg 1M:** Last 3.099%, Chg 1M -2.7 bp gives 3.126%. The Bundesbank's value was 3.12%.
- **Germany 5Y, Chg 12M:** Last 3.144%, Chg 12M +88.6 bp gives 2.258%. The Bundesbank's value was 2.25%.

The 6-month column could not be checked against official data, because we hold no official 6-month-earlier curve. It is
labelled and formatted like the other change columns, and it uses the page's own sign convention.

### c. As-of date and time

Each page shows "Last Update: 11 Nov 2026, HH:15 GMT+0". Each row also has its own date ("10 Nov" or "11 Nov"), with no year
and no time.

Update times seen:

| Time (GMT) | Countries |
|---|---|
| 0:15 | US |
| 3:15 | Canada |
| 6:15 | Japan, China |
| 9:15 | India |
| 18:15 | Germany, Spain, Italy, Brazil |
| 21:15 | UK, France, Switzerland, Australia |

So the page is refreshed hourly at :15, and the figures are the site's last quotes, not an official close. For some markets
they come after the local close; for others, late in the GMT evening.

On 11 Nov, a US bond-market holiday, the US rows were dated 10 Nov except the 10Y, which was dated 11 Nov.

The weekly run on Monday at 15:47 UTC will see Monday's quotes so far for Europe, and the last close for the US and Asia.

### d. Quality: Last against our official values (bp)

Values are compared on the same date where the official source has it. The site's rows are dated 11 Nov unless stated.

| Tenor | US (both 10 Nov) | Germany (both 11 Nov) | UK (BoE 10 Nov) | Japan (MOF 10 Nov) | France (TEC 10 Nov) | Switzerland (SNB 30 Oct) |
|---|---|---|---|---|---|---|
| 1M | -10.0 | - | - | - | - | - |
| 3M | -7.9 | -10.9 (Bubill auction 2 Nov) | - | -8.6 (auction 29 Oct) | -1.0 (October average) | +4.1 (auction 27 Oct) |
| 6M | +3.4 | -1.6 | +19.6 | +2.7 (auction 8 Oct) | - | +11.2 (auction 22 Sep) |
| 1Y | -0.7 | +5.4 | +26.2 | +7.3 | +11.5 | +11.2 |
| 3Y | +5.0 | +0.9 | **+17.3** | +11.3 | **+17.3** | +9.5 |
| 5Y | +1.8 | +2.4 | +9.0 | +6.0 | +13.6 | +6.7 |
| 10Y | +1.8 (WGB 11 Nov) | -4.6 | +4.1 | +3.1 | +11.9 | +3.1 |
| 30Y | +0.8 | -8.2 | -1.1 | +1.5 | +10.2 | +9.0 |

Switzerland's official curve stops at 30 Oct, because the SNB cube lags, so its column compares different dates. As a
same-date check, the site's 1-month-earlier value (Last - Chg 1M, about 11 Oct) was compared with the SNB on 9 Oct:

| 1Y | 3Y | 5Y | 10Y | 30Y |
|---|---|---|---|---|
| +17.2 | +2.3 | +2.1 | -2.1 | +1.5 |

**Flags (above about 15 bp at 2Y or longer): UK 3Y +17.3 and France 3Y +17.3.** The likely explanations below were not
verified further.
- **UK:**
  - The Bank of England curve is a fitted zero-coupon (spot) curve; the site's 3Y is a benchmark gilt's yield.
  - The gap is not a date effect. On matching dates a month earlier (Last - Chg 1M against the BoE on 9 Oct) it was +14 bp at
    3Y and +13 bp at 1Y, so it is a steady basis between the two definitions. A year earlier it was +2 bp.
  - The short end (6M +20, 1Y +26) is the same story: bills against the fitted curve.
- **France:**
  - The TEC are constant-maturity rates interpolated by the Banque de France. The site's figures are single benchmark OATs,
    whose remaining maturity can be longer than the label, which lifts the yield on a steep curve.
  - The dates also differ by a day: 11 Nov was a French holiday, so the TEC is from 10 Nov.
  - On matching dates a month earlier the gap was +6 to +10 bp (3Y +9, 5Y +10, 10Y +6).

Elsewhere the agreement is close: the US (par yields, close to benchmark yields) within 5 bp from 1Y to 30Y, Germany within
8 bp, Japan within 11 bp.

### e. Run time and headless

Headless works and gives exactly the same tables as a visible browser.
- Part 1: a full run of 13 pages took **99 s** (5.5 s between pages plus about 2 s per page load).
- The job itself: **77 s** for 13 pages, parsing, validation and publishing into `data-local/`.
- On GitHub's servers, add the one-off Chromium install (about a minute).

### Pass criteria

| Criterion | Result |
|---|---|
| Every page loads without a challenge | yes: 42 page loads, all HTTP 200, no challenge text, the page's data request 200 |
| At least 10 countries give 6 or more of our 8 tenors | yes: 11 (US, UK, Canada, Japan, Germany, France, Spain, Switzerland, Brazil, Italy, India) |
| No unexplained large errors | yes: two values just above 15 bp at 3Y, both explained by the definitions compared |

With this source, the figures are third-party copies of Investing.com and TradingEconomics data under the site's "All rights
reserved" notice, not official figures. The source line on the page says so.

What was built in Part 2 is described in `docs/yield-sources.md` and `docs/decisions.md` (round 17) in the front-end repo.
