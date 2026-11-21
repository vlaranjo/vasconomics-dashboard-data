# Fixed-income characteristics: where the issuers publish them, and whether we can read them

Research of 21 November 2026 (a Saturday) for the twelve bond funds of the Fixed Income page: yield to maturity (YTM), duration, average credit rating and option-adjusted spread (OAS), each with the issuer's as-of date. Rules followed: plain requests, one at a time, at least 5 s apart; a default headless browser only where a page builds its figures in the browser; stop at any bot check, captcha, login wall or 401/403/406/429, with no workaround. Every request made is listed below. No credential is used anywhere.

## Summary

| Issuer | Funds | Where the figures are | Plain request | Published (YTM / duration / avg rating / OAS) | Update | Usable |
|---|---|---|---|---|---|---|
| State Street (SPDR) | SYBT, SPFA | Fund page, server-rendered HTML block "Fund Characteristics as of [date]" | Yes (HTTP 200) | Yes / Yes (effective duration) / **No** (only a breakdown by rating) / **No** | Daily (previous business day) | **Yes**, adapter built |
| Vanguard | VGEA, VECA | Fund page, server-rendered (Angular); the same figures in the page's embedded JSON | Yes (HTTP 200) | Yes / Yes (average duration) / Yes ("Average quality") / **No** | Monthly (month-end) | **Yes**, adapter built |
| iShares (BlackRock) | IUST, IBCI, IGLT, IBCD, IHYU, IHYG, QDVP | Fund page (not examined) | **Refused: HTTP 403, Akamai "Access Denied"** | not examined | n/a | **No**, switched off |
| Invesco | MUNI | Fund page (builds its figures in the browser) | **Refused: HTTP 406, empty body** | not examined | n/a | **No**, switched off |

**Terms: none of the four issuers allows republishing its website data without written permission, and Vanguard's terms also forbid "repeated automated access".** Details under "Terms" below. Recommendation: ask State Street and Vanguard before the `characteristics` workflow runs on `main` (one line per issuer switches it off: `enabled: false` in `config/characteristics.yaml`). Until then it runs nowhere: `dev` publishes nothing and the workflow's schedule only fires on the default branch.

## State Street (SPDR): usable

- `https://www.ssga.com/robots.txt` (200): disallows `/library-content/assets/pdf/documents`, `/search-results`, `/disclaimers/` and some legacy paths; fund pages and `/library-content/products/` are allowed.
- The fund pages come from the Irish sitemap `https://www.ssga.com/ie/en_gb/sitemap.xml` (200, 963 addresses):
  - SYBT (IE00B44CND37): `https://www.ssga.com/ie/en_gb/institutional/etfs/state-street-spdr-bloomberg-us-treasury-bond-ucits-etf-dist-sybt-gy`
  - SPFA (IE00BFWFPY67): `https://www.ssga.com/ie/en_gb/institutional/etfs/state-street-spdr-bloomberg-emerging-markets-local-bond-ucits-etf-acc-spfa-gy`
- Both answer a plain request with 200 and about 215 KB of server-rendered HTML. No challenge, no investor-type gate in the HTML.
- **Figures:** a `<section data-fundComponent>` titled "Fund Characteristics as of 19 Nov 2026" holds a key/value table: Current Yield, Effective Convexity, **Effective Duration**, Number of Holdings, **Yield to Maturity**, Average Maturity in Years, Average Price. The "Fund Information" block on the same page gives the ISIN, which the adapter checks.
- **Not published:** an average credit rating (the page has a "Quality Breakdown" table, weights by rating bucket, e.g. SYBT AAA 0.56% / AA1 99.44%) and OAS. Those two show "n/a" with the reason. A weighted average rating could be derived from the breakdown, but that would be our figure, not the issuer's, so it is not done.
- Also on the page (not used): a daily holdings XLSX (`/library-content/products/fund-data/etfs/emea/holdings-daily-emea-en-sybt-gy.xlsx`), the NAV history XLSX and the monthly factsheet PDF.
- Update: the characteristics date was the previous business day (19 Nov on Saturday 21 Nov; the NAV block said 20 Nov).
- 21 Nov 2026: SYBT YTM 4.95%, effective duration 5.55; SPFA YTM 6.55%, effective duration 6.15 (both as of 19 Nov 2026).

## Vanguard: usable

- `https://www.vanguard.co.uk/robots.txt` (200): allows everything to everyone; blocks only AI-training crawlers (GPTBot, ClaudeBot, Google-Extended); explicitly allows user-fetch agents.
- Pages from `https://www.vanguard.co.uk/professional/sitemap.xml` (200, 816 addresses):
  - VGEA (IE00BH04GL39): `https://www.vanguard.co.uk/professional/product/etf/bond/9591/eur-eurozone-government-bond-ucits-etf-eur-accumulating`
  - VECA (IE00BGYWT403): `https://www.vanguard.co.uk/professional/product/etf/bond/9695/eur-corporate-bond-ucits-etf-eur-accumulating`
- Plain request: 200, about 630 KB. The page is rendered on the server (Angular), so no browser is needed: the "Characteristics" table is in the HTML ("YTM (Yield to Maturity) effective 3.9% ... As at 31 Oct 2026", "Average quality A+", "Average Duration 6.8 Years"), and the same figures, unrounded, are in the embedded JSON `<script id="serverApp-state" type="application/json">` (the cached answers of the page's `/gpx/graphql` calls): `polarisAnalyticsHistory[0].monthly.yields.fund.items[0].codes.YLDMAT` (YTM), `....analytics.fund.items[0].codes.AVGDURADJ` (average duration), `AVGQLYTFTO` (average quality), each with an `effectiveDate`. The benchmark's figures sit right beside them (`BMK...`, `yields.benchmark`); the adapter reads the fund's only. The entry keys are hashes that differ per page, so the adapter finds the entry by content; it requires exactly one set of fund figures in the JSON and checks them against the rounded ones the page displays.
- **Not published:** OAS.
- Update: monthly, month-end (31 Oct 2026 on 21 Nov).
- 21 Nov 2026: VGEA YTM 3.86%, average duration 6.79, average quality A+; VECA YTM 4.27%, average duration 4.38, average quality A- (all as of 31 Oct 2026).

## iShares (BlackRock): not usable (refused)

- `https://www.ishares.com/robots.txt` (200): disallows only `?truepdf`, `?norepdf`, `*.dl`, sign-on and `/search/` (and Brightbot entirely).
- The old product-screener JSON (`/uk/individual/en/product-screener/product-screener-v3.1.jsn?...`) answered 404.
- `https://www.ishares.com/uk/product-sitemap.xml` answered 200 (3,088 product addresses).
- Earlier the same day, a product page with its full address (`/uk/individual/en/products/251850/ishares-msci-acwi-ucits-etf?switchLocale=y&siteEntryPassthrough=true`, used to verify the MSCI ACWI benchmark of the Relative Momentum charts) answered 200.
- The first bond-fund page request, `/uk/individual/en/products/251833/?switchLocale=y&siteEntryPassthrough=true` (a product address without its name part), answered **403 "Access Denied"** from Akamai (reference 18.d9b31202.1795269395.28810e9b). **Stopped there**: no further request to ishares.com, no other headers, no browser. It is possible that the address form, not the client, was refused; I did not test that. Your call whether to allow one more attempt with a full product address.
- So it is **unconfirmed** which of the four figures iShares publishes for its UCITS bond funds or in what form.

## Invesco: not usable (refused)

- `https://www.invesco.com/robots.txt` (200): disallows parameters such as `asOfDate=`, `.zip` and some US pages.
- `https://www.invesco.com/uk/en/sitemap.xml` (200) lists the MUNI page `https://www.invesco.com/uk/en/financial-products/etfs/invesco-us-municipal-bond-ucits-etf-dist.html`.
- That page answered **HTTP 406 with an empty body**. Treated as a refusal: **stopped**, nothing further requested from invesco.com, no browser. (Invesco's product pages are known to build their figures in the browser from a separate API, which would have made a default browser admissible under the rules; after a refusal I did not try it.)

## Terms

| Issuer | Read | What it says |
|---|---|---|
| State Street | `https://www.ssga.com/ie/en_gb/footer/terms-and-conditions` (read in full) | "You may not copy, reproduce, duplicate, modify, adopt or lend, sell, disseminate or otherwise transfer, in whole or in part, any of the information contained in this Site, except for the purpose of accessing the Site and producing print-outs for your own personal use, or making a reasonable number of copies of such pages for internal use within your organization." |
| Vanguard | `https://www.vanguard.co.uk/professional/terms-and-conditions` (read in full) | Licence "solely for your personal, informational and non-commercial use or as expressly authorised by Vanguard in writing"; you may not "copy, ... distribute, ... display, ... reproduce, publish ... any reports, data, information ... obtained from this website"; and you may not use "devices or software that provide repeated automated access to this website, other than those made generally available by Vanguard". |
| iShares | not opened (the host had refused us); from search results only: `https://www.ishares.com/uk/individual/en/compliance/terms-and-conditions`, `https://www.blackrock.com/corporate/compliance/ishares-terms-and-conditions` | Reproduction or distribution without BlackRock's written permission is not allowed. **Unconfirmed** in the full text. |
| Invesco | not opened; from search results only: `https://www.invesco.com/uk/en/global-footer/terms-and-conditions.html` and other country sites | Copying, transmitting or commercial use without prior written permission is not allowed; personal use only. **Unconfirmed** for the UK text. |

Consequence: publishing these figures on a public page, refreshed by a scheduled job, needs written permission from State Street and from Vanguard (the same position as Cboe in decisions V5; you decided to publish Cboe in V13). The adapters are built and tested so that nothing more is needed once permission is given.

## The job (`characteristics` workflow)

- `jobs/dashjobs/characteristics.py`, `jobs/run_characteristics.py`, `config/characteristics.yaml`, `.github/workflows/characteristics.yml` (Saturday 07:17 UTC; own concurrency group; `commit_data.py --job characteristics` commits only a real change).
- Output: `data/characteristics/fixed-income.json` (13 KB), manifest block `characteristics`, status source `fund_issuers`.
- Per fund: `measures.{ytm, duration, rating, oas}` = `{value, as_of, name}` (the issuer's own name for the figure) or `{value: null, reason}`.
- Rules: 5 s between requests; no retry and no further request to an issuer after a 401/403/406/429 or a challenge page; a fund that fails (refused, page layout changed, wrong ISIN, figures fail the checks) keeps its last good figures, marked stale; a figure is never replaced by one with an earlier as-of date; checks: YTM -2..30%, duration 0..30, OAS -100..3000 bp, rating a valid letter rating, as-of not in the future and at most 10 days old (State Street) or 75 days (Vanguard, monthly).
- Tests: `tests/test_characteristics.py` (13), on the four real pages saved 21 Nov 2026 (`tests/fixtures/characteristics/*.html.gz`), including layout changes (block renamed, figure renamed, figure not a number, the embedded JSON missing or renamed, the wrong fund's page).
