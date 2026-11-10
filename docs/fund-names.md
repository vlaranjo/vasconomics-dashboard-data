# Fund names (from Yahoo)

Generated 2026-11-09 by `jobs/report_fund_names.py`. The markets job reads each ticker's `longName` and `shortName` from Yahoo (the same
source as the prices) and shows `longName`, falling back to `shortName` only if `longName` is missing. A ticker can carry `name_override` plus a one-line
`name_reason` in `config/universe.yaml` for a name Yahoo has wrong. If Yahoo's name call fails in a run, the last published name is kept (never blanked).

91 funds, 14 with a flag. Flags are automatic (missing, truncated, outdated brand, share class or hedge contradicting the config, legal-entity
prefix) plus hand-written remarks from a comparison with the justETF profile name for the same ISIN (the names the config used before this round).

| Ticker | ISIN | longName | shortName | Name shown | Flag |
|---|---|---|---|---|---|
| ACWIE.MI | IE00BYM11K57 | UBS MSCI ACWI SF UCITS ETF hEUR acc | UBS MSCI ACWI SF UCITS ETF hEUR | UBS MSCI ACWI SF UCITS ETF hEUR acc |  |
| VAGF.DE | IE00BG47KH54 | Vanguard Global Aggregate Bond UCITS ETF EUR Hedged Accumulation | Vanguard Fds-Gl.Aggr.Bd UC.ETFR | Vanguard Global Aggregate Bond UCITS ETF EUR Hedged Accumulation |  |
| EPRA.PA | LU1437018838 | Amundi Index Solutions - Amundi FTSE EPRA NAREIT Global UCITS ETF DR | Amundi FTSE EPRA NAREIT Global | Amundi Index Solutions - Amundi FTSE EPRA NAREIT Global UCITS ETF DR | legal-entity prefix in the name |
| CMOE.MI | IE00BF4J0300 | Invesco Bloomberg Commodity UCITS ETF EUR Hedged | INVESCO BLOOM COMMODIT UCITS ET | Invesco Bloomberg Commodity UCITS ETF EUR Hedged |  |
| XAD1.DE | DE000A1EK0G3 | Xtrackers Physical Gold EUR Hedged ETC | DB ETC PLC                    E | Xtrackers Physical Gold EUR Hedged ETC |  |
| PEU.PA | IE00B3BPCH51 | Invesco EuroMTS Cash 3 Months UCITS ETF | Invesco EuroMTS Cash 3 Months U | Invesco Euro Cash 3 Months UCITS ETF Acc | overridden: Yahoo still shows the pre-rename name (Invesco EuroMTS Cash 3 Months UCITS ETF); the fund is now called Euro Cash 3 Months (justETF profile, checked 6 Nov 2026) |
| UBUJ.DE | IE00BD4TYG73 | UBS Core MSCI USA hEUR UCITS ETF EUR acc | UBS(I)ETF-UBS C.M.USA hEO ETF R | UBS Core MSCI USA hEUR UCITS ETF EUR acc |  |
| EUNK.DE | IE00B4K48X80 | iShares Core MSCI Europe UCITS ETF EUR (Acc) | iShsIII-C.MSCI Eu.U.E.EUR Acc R | iShares Core MSCI Europe UCITS ETF EUR (Acc) |  |
| IBCG.DE | IE00B42Z5J44 | iShares MSCI Japan EUR Hedged UCITS ETF (Acc) | iShsV-MSCI Jap.EUR Hdg U-ETF AR | iShares MSCI Japan EUR Hedged UCITS ETF (Acc) |  |
| SXR1.DE | IE00B52MJY50 | iShares VII PLC - iShares Core MSCI Pac ex-Jpn ETF USD Acc | iShs VII-Co.MSCI Pac.xJP U.ETFR | iShares VII PLC - iShares Core MSCI Pac ex-Jpn ETF USD Acc | legal-entity prefix in the name; abbreviated ("Pac ex-Jpn"), no "UCITS"; same ISIN as justETF's "Core MSCI Pacific ex Japan" |
| EUNM.DE | IE00B4L5YC18 | iShares MSCI EM UCITS ETF USD (Acc) | iShsIII-MSCI EM U.ETF USD(Acc)R | iShares MSCI EM UCITS ETF USD (Acc) |  |
| AASI.MI | LU1681044480 | Amundi Index Solutions - Amundi MSCI Em Asia UCITS ETF-C EUR | AMUNDI MSCI EM ASIA UCITS ETF - | Amundi Index Solutions - Amundi MSCI Em Asia UCITS ETF-C EUR | legal-entity prefix in the name; wording differs from justETF ("Em Asia" vs "Emerging Markets Asia"); same fund |
| ALAT.PA | LU1681045024 | Amundi Index Solutions - Amundi MSCI Em Latin America UCITS ETF-C EUR | AMUNDI MSCI EM LATIN AMERICA UC | Amundi Index Solutions - Amundi MSCI Em Latin America UCITS ETF-C EUR | legal-entity prefix in the name; wording differs from justETF ("Em" abbreviation); same fund |
| IBCF.DE | IE00B3ZW0K18 | iShares S&P 500 EUR Hedged UCITS ETF (Acc) | iShsV-S&P500 EUR Hgd U.ETF AccR | iShares S&P 500 EUR Hedged UCITS ETF (Acc) |  |
| LYP6.DE | LU0908500753 | Amundi Core Stoxx Europe 600 UCITS ETF Acc | AIS-Amundi Core Stoxx Eur.600 A | Amundi Core Stoxx Europe 600 UCITS ETF Acc |  |
| SXRW.DE | IE00B53HP851 | iShares VII PLC - iShares Core FTSE 100 ETF GBP Acc | iShs VII-C.FTSE 100 E.GBP     R | iShares VII PLC - iShares Core FTSE 100 ETF GBP Acc | legal-entity prefix in the name; no "UCITS" in the name; same fund as justETF's "Core FTSE 100 UCITS ETF GBP (Acc)" |
| 18MN.DE | LU1681044993 | Amundi Index Solutions - Amundi MSCI Switzerland UCITS ETF-C CHF | AIS-Amundi MSCI Switzerland   N | Amundi Index Solutions - Amundi MSCI Switzerland UCITS ETF-C CHF | legal-entity prefix in the name |
| SAUS.MI | IE00B5377D42 | iShares MSCI Australia UCITS ETF USD (Acc) | ISHARES MSCI AUSTRALIA UCITS ET | iShares MSCI Australia UCITS ETF USD (Acc) |  |
| XCS6.DE | LU0514695690 | Xtrackers MSCI China UCITS ETF 1C | xtrackers MSCI China          I | Xtrackers MSCI China UCITS ETF 1C |  |
| QDV5.DE | IE00BZCQB185 | iShares MSCI India UCITS ETF USD Acc | iShs IV-iShs MSCI India UC.ETFR | iShares MSCI India UCITS ETF USD Acc |  |
| LBRA.DE | LU1900066207 | Amundi MSCI Brazil UCITS ETF Acc | MUL Amundi MSCI Brazil        I | Amundi MSCI Brazil UCITS ETF Acc |  |
| LKOR.DE | LU1900066975 | Amundi MSCI Korea UCITS ETF Acc | MUL Amundi MSCI Korea         U | Amundi MSCI Korea UCITS ETF Acc |  |
| D5BI.DE | LU0476289466 | Xtrackers MSCI Mexico UCITS ETF 1C | Xtrackers MSCI Mexico         I | Xtrackers MSCI Mexico UCITS ETF 1C |  |
| IBC4.DE | IE00B52XQP83 | iShares MSCI South Africa UCITS ETF USD (Acc) | iShsIII-MSCI South Afr.U.ETF  R | iShares MSCI South Africa UCITS ETF USD (Acc) |  |
| LTUR.DE | LU1900067601 | Amundi MSCI Turkey UCITS ETF Acc | MUL Amundi MSCI Turkey        U | Amundi MSCI Turkey UCITS ETF Acc |  |
| IUSS.DE | IE00BYYR0489 | iShares MSCI Saudi Arabia Capped UCITS ETF USD (Acc) | iShsIII-MSCI S.Arab.Capp.U.ETFR | iShares MSCI Saudi Arabia Capped UCITS ETF USD (Acc) |  |
| IBCJ.DE | IE00B4M7GH52 | iShares MSCI Poland UCITS ETF USD (Acc) | iShsV-MSCI Poland UCITS ETF   R | iShares MSCI Poland UCITS ETF USD (Acc) |  |
| INDO.MI | LU1900065811 | Amundi MSCI Indonesia UCITS ETF Acc | Amundi MSCI Indonesia UCITS ETF | Amundi MSCI Indonesia UCITS ETF Acc |  |
| DBX5.DE | LU0292109187 | Xtrackers MSCI Taiwan UCITS ETF 1C | Xtrackers MSCI Taiwan         I | Xtrackers MSCI Taiwan UCITS ETF 1C |  |
| SXR8.DE | IE00B5BMR087 | iShares Core S&P 500 UCITS ETF USD (Acc) | iShs VII-Core S&P 500 U.ETF   R | iShares Core S&P 500 UCITS ETF USD (Acc) |  |
| SXRV.DE | IE00B53SZB19 | iShares NASDAQ 100 UCITS ETF USD (Acc) | iShsVII-NASDAQ 100 UCITS ETF  R | iShares NASDAQ 100 UCITS ETF USD (Acc) |  |
| SXRU.DE | IE00B53L4350 | iShares VII PLC - iShares Dow Jones Indust Avg ETF USD Acc | iShsVII-DJ Indl Average U.ETF R | iShares VII PLC - iShares Dow Jones Indust Avg ETF USD Acc | legal-entity prefix in the name; abbreviated ("Indust Avg"), no "UCITS"; same ISIN as justETF's "Dow Jones Industrial Average" |
| ZPRR.DE | IE00BJ38QD84 | State Street SPDR Russell 2000 US Small Cap UCITS ETF | SPDR Russell2000US.S.Cap U.ETFR | State Street SPDR Russell 2000 US Small Cap UCITS ETF |  |
| SXR4.DE | IE00B52SFT06 | iShares VII PLC - iShares MSCI USA ETF USD Acc | iShsVII-MSCI USA UCITS ETF    R | iShares VII PLC - iShares MSCI USA ETF USD Acc | legal-entity prefix in the name; no "UCITS" in the name; same ISIN as justETF's "MSCI USA UCITS ETF (Acc)" |
| QDVI.DE | IE00BD1F4M44 | iShares Edge MSCI USA Value Factor UCITS ETF USD (Acc) | iShsIV-Edge MSCI USA V.F.U.ETFR | iShares Edge MSCI USA Value Factor UCITS ETF USD (Acc) |  |
| QDVC.DE | IE00BD1F4K20 | iShares MSCI USA Mid-Cap Equal Weight UCITS ETF | iShsIV-MSCI USA M-C E.W.U.ETF R | iShares MSCI USA Mid-Cap Equal Weight UCITS ETF | share class (Acc) not in the name |
| QDVB.DE | IE00BD1F4L37 | iShares Edge MSCI USA Quality Factor UCITS ETF USD (Acc) | iShsIV-Edge MSCI USA Q.F.U.ETFR | iShares Edge MSCI USA Quality Factor UCITS ETF USD (Acc) |  |
| QDVA.DE | IE00BD1F4N50 | iShares Edge MSCI USA Momentum Factor UCITS ETF USD (Acc) | iShsIV-Edge MSCI USA M.F.U.ETFR | iShares Edge MSCI USA Momentum Factor UCITS ETF USD (Acc) |  |
| SPYD.DE | IE00B6YX5D40 | State Street SPDR S&P US Dividend Aristocrats UCITS ETF Dis | StSt SPDR S&P US Div.Arist.UE R | State Street SPDR S&P US Dividend Aristocrats UCITS ETF Dis | Yahoo ends "Dis" (distributing); justETF adds "USD Unhedged (Dist)"; same ISIN |
| MVEA.DE | IE00BKVL7331 | iShares Edge MSCI USA Minimum Volatility Advanced UCITS ETF USD (Acc) | iShs VI-iSh.Edg.MSCI USA M.V.ER | iShares Edge MSCI USA Minimum Volatility Advanced UCITS ETF USD (Acc) |  |
| IU5C.DE | IE00BDDRF478 | iShares S&P 500 Communication Sector UCITS ETF USD Acc | iShs V-S&P 500 Commun.S.UC.ETFR | iShares S&P 500 Communication Sector UCITS ETF USD Acc |  |
| QDVK.DE | IE00B4MCHD36 | iShares S&P 500 Consumer Discretionary Sector UCITS ETF USD (Acc) | iShsV-S&P 500 Con.Dis.Se.U.ETFR | iShares S&P 500 Consumer Discretionary Sector UCITS ETF USD (Acc) |  |
| 2B7D.DE | IE00B40B8R38 | iShares S&P 500 Consumer Staples Sector UCITS ETF USD (Acc) | iShsV-S&P 500 Con.Sta.Se.U.ETFR | iShares S&P 500 Consumer Staples Sector UCITS ETF USD (Acc) |  |
| QDVF.DE | IE00B42NKQ00 | iShares S&P 500 Energy Sector UCITS ETF USD (Acc) | iShsV-S&P 500 Energ.Sect.U.ETFR | iShares S&P 500 Energy Sector UCITS ETF USD (Acc) |  |
| QDVH.DE | IE00B4JNQZ49 | iShares S&P 500 Financials Sector UCITS ETF USD (Acc) | iShsV-S&P 500 Finl Sec.U.ETF  R | iShares S&P 500 Financials Sector UCITS ETF USD (Acc) |  |
| QDVG.DE | IE00B43HR379 | iShares S&P 500 Health Care Sector UCITS ETF USD (Acc) | iShsV-S&P 500 He.Ca.Sec.U.ETF R | iShares S&P 500 Health Care Sector UCITS ETF USD (Acc) |  |
| 2B7C.DE | IE00B4LN9N13 | iShares S&P 500 Industrials Sector UCITS ETF USD (Acc) | iShsV-S&P 500 Ind.Sector.U.ETFR | iShares S&P 500 Industrials Sector UCITS ETF USD (Acc) |  |
| 2B7B.DE | IE00B4MKCJ84 | iShares S&P 500 Materials Sector UCITS ETF USD (Acc) | iShsV-S&P 500 Mat.Sector.U.ETFR | iShares S&P 500 Materials Sector UCITS ETF USD (Acc) |  |
| QDVE.DE | IE00B3WJKG14 | iShares S&P 500 Information Technology Sector UCITS ETF USD (Acc) | iShsV-S&P 500 Inf.Te.Sec.U.ETFR | iShares S&P 500 Information Technology Sector UCITS ETF USD (Acc) |  |
| 2B7A.DE | IE00B4KBBD01 | iShares S&P 500 Utilities Sector UCITS ETF USD (Acc) | iShsV-S&P 500 Ut.Sector U.ETF R | iShares S&P 500 Utilities Sector UCITS ETF USD (Acc) |  |
| STTX.MI | IE00BKWQ0N82 | State Street SPDR MSCI Europe Communication Services UCITS ETF | State Street SPDR MSCI Europe C | State Street SPDR MSCI Europe Communication Services UCITS ETF |  |
| STRX.MI | IE00BKWQ0C77 | State Street SPDR MSCI Europe Consumer Discretionary UCITS ETF | State Street SPDR MSCI Europe C | State Street SPDR MSCI Europe Consumer Discretionary UCITS ETF |  |
| STSX.MI | IE00BKWQ0D84 | State Street SPDR MSCI Europe Consumer Staples UCITS ETF | State Street SPDR MSCI Europe C | State Street SPDR MSCI Europe Consumer Staples UCITS ETF |  |
| STNX.MI | IE00BKWQ0F09 | State Street SPDR MSCI Europe Energy UCITS ETF | State Street SPDR MSCI Europe E | State Street SPDR MSCI Europe Energy UCITS ETF |  |
| STZX.MI | IE00BKWQ0G16 | State Street SPDR MSCI Europe Financials UCITS ETF | State Street SPDR MSCI Europe F | State Street SPDR MSCI Europe Financials UCITS ETF |  |
| STWX.MI | IE00BKWQ0H23 | State Street SPDR MSCI Europe Health Care UCITS ETF | State Street SPDR MSCI Europe H | State Street SPDR MSCI Europe Health Care UCITS ETF |  |
| STQX.MI | IE00BKWQ0J47 | State Street SPDR MSCI Europe Industrials UCITS ETF | State Street SPDR MSCI Europe I | State Street SPDR MSCI Europe Industrials UCITS ETF |  |
| STPX.MI | IE00BKWQ0L68 | State Street SPDR MSCI Europe Materials UCITS ETF | State Street SPDR MSCI Europe M | State Street SPDR MSCI Europe Materials UCITS ETF |  |
| STKX.MI | IE00BKWQ0K51 | State Street SPDR MSCI Europe Technology UCITS ETF | State Street SPDR MSCI Europe T | State Street SPDR MSCI Europe Technology UCITS ETF |  |
| STUX.MI | IE00BKWQ0P07 | State Street SPDR MSCI Europe Utilities UCITS ETF | State Street SPDR MSCI Europe U | State Street SPDR MSCI Europe Utilities UCITS ETF |  |
| SYBT.DE | IE00B44CND37 | State Street SPDR Bloomberg U.S. Treasury Bond UCITS ETF | SPDR Bl.US Treasury Bd UETF   R | State Street SPDR Bloomberg U.S. Treasury Bond UCITS ETF |  |
| VGEA.DE | IE00BH04GL39 | Vanguard EUR Eurozone Government Bond UCITS ETF EUR Accumulation | Vanguard EUR Euroz.Gov.B.U.ETFR | Vanguard EUR Eurozone Government Bond UCITS ETF EUR Accumulation |  |
| IUST.DE | IE00B1FZSC47 | iShares $ TIPS UCITS ETF USD (Acc) | iShsII-$ TIPS UCITS ETF       R | iShares $ TIPS UCITS ETF USD (Acc) |  |
| IBCI.AS | IE00B0M62X26 | iShares € Inflation Linked Govt Bond UCITS ETF EUR (Acc) | iShares Euro Inflation Linked G | iShares € Inflation Linked Govt Bond UCITS ETF EUR (Acc) | Yahoo uses the euro sign and "Govt"; justETF "Euro ... Government"; same ISIN |
| IGLT.MI | IE00B1FZSB30 | iShares Core UK Gilts UCITS ETF GBP (Dist) | ISHARES CORE UK GILTS UCITS ETF | iShares Core UK Gilts UCITS ETF GBP (Dist) |  |
| SPFA.DE | IE00BFWFPY67 | State Street SPDR Bloomberg Emerging Markets Local Bond UCITS ETF (Acc) | SPDR Bl.Em.Mkts Loc.Bd UETF   R | State Street SPDR Bloomberg Emerging Markets Local Bond UCITS ETF (Acc) |  |
| IBCD.DE | IE0032895942 | iShares $ Corp Bond UCITS ETF USD (Dist) | iShs DL Corp Bond UCITS ETF   R | iShares $ Corp Bond UCITS ETF USD (Dist) | Yahoo still writes "$ Corp Bond"; justETF now "USD Corporate Bond"; same ISIN |
| IHYU.MI | IE00B4PY7Y77 | iShares $ High Yield Corp Bond UCITS ETF USD (Dist) | ISHARES $ HIGH YIELD CORP UCITS | iShares $ High Yield Corp Bond UCITS ETF USD (Dist) |  |
| VECA.DE | IE00BGYWT403 | Vanguard EUR Corporate Bond UCITS ETF EUR Accumulation | Vanguard EUR Corp.Bond U.ETF  R | Vanguard EUR Corporate Bond UCITS ETF EUR Accumulation | "Accumulation" vs justETF "Accumulating": wording only |
| IHYG.MI | IE00B66F4759 | iShares € High Yield Corp Bond UCITS ETF EUR (Dist) | ISHARES HIGH YLD CORP UCITS ETF | iShares € High Yield Corp Bond UCITS ETF EUR (Dist) |  |
| QDVP.DE | IE00BZ6V7883 | iShares US Mortgage Backed Securities UCITS ETF USD (Dist) | iShsIV-US Mortg.Back.Sec.U.ETFR | iShares US Mortgage Backed Securities UCITS ETF USD (Dist) |  |
| MUNI.MI | IE00BNG70R26 | Invesco US Municipal Bond UCITS ETF Dist | INVESCO US MUNICIPAL BOND UCITS | Invesco US Municipal Bond UCITS ETF Dist |  |
| AIGE.MI | GB00B15KYB02 | WisdomTree Energy | WISDOMTREE ENERGY | WisdomTree Energy |  |
| AIGA.MI | GB00B15KYH63 | WisdomTree Agriculture | WISDOMTREE AGRICULTURE | WisdomTree Agriculture |  |
| EIMT.MI | JE00B78NPW60 | WisdomTree Industrial Metals - EUR Daily Hedged | WISDOMTREE INDUST METALS EUR DA | WisdomTree Industrial Metals - EUR Daily Hedged |  |
| AIGP.MI | GB00B15KYF40 | WisdomTree Precious Metals | WISDOMTREE PRECIOUS METALS | WisdomTree Precious Metals |  |
| AIGS.MI | GB00B15KYJ87 | WisdomTree Softs | WISDOMTREE SOFTS | WisdomTree Softs |  |
| EBRT.MI | JE00B7305Z55 | WisdomTree Brent Crude Oil - EUR Daily Hedged | WISDOMTREE BRENT CRUDE OIL EUR | WisdomTree Brent Crude Oil - EUR Daily Hedged |  |
| ENGS.MI | JE00B6XF0923 | WisdomTree Natural Gas - EUR Daily Hedged | WISDOMTREE NAT GAS - EUR DAILY | WisdomTree Natural Gas - EUR Daily Hedged |  |
| ECRN.MI | JE00B3ZQRP79 | WisdomTree Corn - EUR Daily Hedged | WISDOMTREE CORN - EUR DAILY HED | WisdomTree Corn - EUR Daily Hedged |  |
| ESOY.MI | JE00B6SLJ210 | WisdomTree Soybeans - EUR Daily Hedged | WISDOMTREE SOYBEANS - EUR DAILY | WisdomTree Soybeans - EUR Daily Hedged |  |
| EWAT.MI | JE00B78NNK09 | WisdomTree Wheat - EUR Daily Hedged | WISDOMTREE WHEAT - EUR DAILY HE | WisdomTree Wheat - EUR Daily Hedged |  |
| ESVR.MI | JE00B5SV2703 | WisdomTree Silver - EUR Daily Hedged | WISDOMTREE SILVER - EUR DAILY H | WisdomTree Silver - EUR Daily Hedged |  |
| PHPT.MI | JE00B1VS2W53 | WisdomTree Physical Platinum | WISDOMTREE PHYSICAL PLATINUM | WisdomTree Physical Platinum |  |
| ECOP.MI | JE00B4PDKD43 | WisdomTree Copper - EUR Daily Hedged | WISDOMTREE COPPER - EUR DAILY H | WisdomTree Copper - EUR Daily Hedged |  |
| EALU.MI | JE00B6VG2P72 | WisdomTree Aluminium - EUR Daily Hedged | WISDOMTREE ALUMINIUM - EUR DAIL | WisdomTree Aluminium - EUR Daily Hedged |  |
| EZNC.MI | JE00B78NNM23 | WisdomTree Zinc - EUR Daily Hedged | WISDOMTREE ZINC - EUR DAILY HED | WisdomTree Zinc - EUR Daily Hedged |  |
| ENIK.MI | JE00B6XL6W59 | WisdomTree Nickel - EUR Daily Hedged | WISDOMTREE NICKEL - EUR DAILY H | WisdomTree Nickel - EUR Daily Hedged |  |
| ESUG.MI | JE00B6X05031 | WisdomTree Sugar - EUR Daily Hedged | WISDOMTREE SUGAR - EUR DAILY HE | WisdomTree Sugar - EUR Daily Hedged |  |
| ECOF.MI | JE00B6TK3K31 | WisdomTree Coffee - EUR Daily Hedged | WISDOMTREE COFFEE - EUR DAILY H | WisdomTree Coffee - EUR Daily Hedged |  |
| ECTN.MI | JE00B70DCH80 | WisdomTree Cotton - EUR Daily Hedged | WISDOMTREE COTTON - EUR DAILY H | WisdomTree Cotton - EUR Daily Hedged |  |
