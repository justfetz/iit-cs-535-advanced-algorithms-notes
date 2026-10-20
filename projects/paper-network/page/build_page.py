"""Assemble the blog post (site layout), the standalone artifact page, and a local test page from template + data + app."""
import json, os, re, html, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.abspath(os.path.join(HERE, ".."))
SITE = "/home/user/justfetz/justfetz.github.io"
OUT = os.path.join(SCR, "out")
D = json.load(open(os.path.join(SCR, "data", "paper_network.json")))
BM = json.load(open(os.path.join(SCR, "geo", "basemap.json")))
mills = D["mills"]; S = D["scenarios"]; P = D["params"]
MT = lambda v: f"{v/1e6:.2f}"; MT1 = lambda v: f"{v/1e6:.1f}"
def kt(v): return f"{v/1e6:.2f} Mt" if v >= 950000 else f"{round(v/1e3):,} kt"
def musd(v): return f"${v/1e6:,.0f}M"
MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"]

# owner order for the palette: open US+CA capacity, descending
caps = {}
for m in mills:
    if m["country"] != "MX" and m["status"] == "open": caps[m["owner"]] = caps.get(m["owner"], 0) + m["cap"]
D["owner_order"] = sorted(caps, key=lambda o: -caps[o])

act24 = set(S["fp2024"]["active"]); act26 = set(S["fp2026"]["active"])
us = [m for m in mills if m["country"] == "US"]
n_us_open = sum(1 for m in us if m["status"] == "open")
cap_us_2024 = sum(m["cap_2024"] for m in us if m["id"] in act24)
cap_us_2026 = sum(m["cap"] for m in us if m["status"] == "open")
ip_2024 = sum(m["cap_2024"] for m in us if m["id"] in act24 and m["owner_2024"] == "International Paper")
sw_2026 = sum(m["cap"] for m in us if m["status"] == "open" and m["owner"] == "Smurfit Westrock")
pca_2026 = sum(m["cap"] for m in us if m["status"] == "open" and m["owner"] == "Packaging Corp of America")
closed_2526 = sum(m["cap"] for m in us if m["status"] == "closed" and (m["closed_year"] or 0) >= 2025)
def ship_us(key): return sum(S[key]["shipped"][m["id"]] for m in us)
k26, k24, kcf = S["fp2026"]["kpi"], S["fp2024"]["kpi"], S["cf2026"]["kpi"]
integ = S["fp2026"]["integration"]
REPORTED = {"International Paper": "~80% to own plants (10-K)", "Smurfit Westrock": "~81% implied: WestRock was ~23% long on board vs its plants (Fastmarkets)",
            "Packaging Corp of America": "\"majority\" in the 10-K; ~96% per secondary sources", "Georgia-Pacific": "not disclosed", "Pratt Industries": "not disclosed",
            "Green Bay Packaging": "not disclosed", "Cascades": "not disclosed"}
rows = []
for o, v in sorted(integ.items(), key=lambda kv: -(kv[1]["total"] + kv[1]["exports"])):
    tot = v["total"] + v["exports"]
    if tot <= 0: continue
    rows.append(f"<tr><td>{html.escape(o)}</td><td class='n'>{kt(tot)}</td><td class='n'>{v['internal']/tot:.0%}</td><td class='n'>{kt(v['market'])}</td><td class='n'>{kt(v['exports'])}</td><td class='n'>{kt(v['bought_from_market'])}</td><td>{html.escape(REPORTED.get(o,''))}</td></tr>")
ip = integ["International Paper"]; sw = integ["Smurfit Westrock"]
ip_tot = ip["total"] + ip["exports"]; sw_tot = sw["total"] + sw["exports"]
# scarcity: capacity duals west vs east (active US mills, 2026)
sh = S["fp2026"]["shadow"]
west = [sh[m["id"]] for m in us if m["id"] in act26 and m["st"] in ("CA", "OR", "WA")]
east = [sh[m["id"]] for m in us if m["id"] in act26 and m["st"] not in ("CA", "OR", "WA")]
mc = S["fp2026"]["node_mc"]; order = sorted(range(len(mc)), key=lambda i: mc[i])
cheap = ", ".join(D["nodes"][i]["name"] for i in order[:3]); dear = ", ".join(D["nodes"][i]["name"] for i in order[-3:])
# months (staggered calendar): outage penalty isolated from seasonality
mon = [(mo, S[f"m{mo:02d}"]) for mo in range(1, 13)]
worst = max(mon, key=lambda t: t[1]["outage_penalty_usd"]); best = min(mon, key=lambda t: t[1]["outage_penalty_usd"])
unmet_w = worst[1]["kpi"]["unmet_tons"] - worst[1]["noout"]["unmet_tons"]
month_text = (f"In this calendar the costliest month is {MONTHS[worst[0]-1]}, with {len(worst[1]['mills_down'])} mills down and {kt(worst[1]['tons_offline'])} of capacity offline: "
              f"freight runs {musd(worst[1]['outage_penalty_usd'])} above what the same month would cost with every mill running"
              + (f", and {kt(unmet_w)} of demand cannot be served at all." if unmet_w > 1000 else ".")
              + f" The cheapest outage month is {MONTHS[best[0]-1]} at {musd(best[1]['outage_penalty_usd'])}, with {len(best[1]['mills_down'])} mills out and soft demand.")
co = D["calendar_opt"]
calopt_text = (f"On the dual-price estimate, the staggered calendar costs {musd(co['random_est'])} a year in extra freight and the assignment's calendar {musd(co['opt_est'])}. "
               f"Re-solving the twelve months with the optimized calendar confirms the direction: the actual freight penalty falls from {musd(co['random_actual_annual_penalty'])} to {musd(co['opt_actual_annual_penalty'])} a year, "
               f"with the same {len(co['assignments'])} outages of the same length.")
kos = sorted(D["knockouts"], key=lambda k: -k["d_freight"])
ko_text = (f"Losing {kos[0]['name']}, {kos[0]['st']} ({kos[0]['owner']}, {kt(kos[0]['cap'])}) would cost the network {musd(kos[0]['d_freight'])} a year in freight; "
           f"{kos[1]['name']}, {kos[1]['st']} {musd(kos[1]['d_freight'])}; {kos[2]['name']}, {kos[2]['st']} {musd(kos[2]['d_freight'])}. "
           + ("The ranking is not the capacity ranking: " if kos[0]["cap"] < max(k["cap"] for k in kos) else "")
           + "a mill matters in proportion to how far its tons would have to come from otherwise, which is why the West Coast mills punch above their tonnage."
           + (" " + "; ".join(f"without {k['name']} {kt(k['unmet'])} of demand goes unserved" for k in kos if k["unmet"] > 1000)[:1].upper() + "; ".join(f"without {k['name']} {kt(k['unmet'])} of demand goes unserved" for k in kos if k["unmet"] > 1000)[1:] + "." if any(k["unmet"] > 1000 for k in kos) else ""))
cf_text = (f"the solver cannot place {kt(kcf['unmet_tons'])} of that demand anywhere, the average haul rises to {kcf['avg_haul_miles']:.0f} miles and freight to ${kcf['avg_freight_per_ton']:.0f} a ton."
           if kcf["unmet_tons"] > 1000 else f"every ton still finds a mill, but the average haul rises to {kcf['avg_haul_miles']:.0f} miles and freight to ${kcf['avg_freight_per_ton']:.0f} a ton, with mills at {kcf['tons_shipped_domestic']/cap_us_2026:.0%} of US capacity.")
# python excerpt
src = open(os.path.join(SCR, "model", "netmodel.py")).read()
a = src.index("    owners = [k for k in owner_shares"); b = src.index("    if res.status != 0")
excerpt = html.escape("\n".join(l[4:] if l.startswith("    ") else l for l in src[a:b].splitlines()))
sources = " · ".join([
 '<a href="https://www.sec.gov/Archives/edgar/data/51434/000005143425000013/ip-20241231.htm">IP 10-K FY2024</a>',
 '<a href="https://www.sec.gov/Archives/edgar/data/2005951/000200595125000005/smur-20241231.htm">Smurfit Westrock 10-K FY2024</a>',
 '<a href="https://www.sec.gov/Archives/edgar/data/75677/000119312526074129/pkg-20251231.htm">PCA 10-K FY2025</a>',
 '<a href="https://www.packagingdive.com/news/afpa-capacity-data-2025-production-decline-containerboard/821910/">AF&amp;PA 2025 capacity survey (Packaging Dive)</a>',
 '<a href="https://www.fastmarkets.com/insights/north-american-containerboard-market-capacity-cuts/">Fastmarkets on 2025–26 capacity cuts</a>',
 '<a href="https://www.packagingdive.com/news/international-paper-two-mill-closures-riceboro-savannah-georgia-layoffs/758254/">IP Savannah and Riceboro closures</a>',
 '<a href="https://www.recyclingtoday.com/news/georgia-pacific-mill-closing-cedar-springs-containerboard-cardboard-recycling/">GP Cedar Springs closure</a>',
 '<a href="https://ir.packagingcorp.com/news-releases/news-release-details/packaging-corporation-america-announces-agreement-purchase-greif">PCA buys Greif containerboard</a>',
 '<a href="https://www.fibrebox.org/the-corrugated-industry">Fibre Box Association</a>',
 '<a href="https://now.aiccbox.org/a-look-at-the-evolution-of-box-plants-1/">AICC on the number of box plants</a>',
 '<a href="https://www.recyclingtoday.com/article/what-a-difference-a-year-makes-for-north-american-paper-capacity/">Recycling Today on capacity shares</a>',
 '<a href="https://www.fool.com/earnings/call-transcripts/2026/04/23/packaging-corp-pkg-q1-2026-earnings-transcript/">PCA Q1 2026 call (outage plan)</a>',
 '<a href="https://github.com/topojson/us-atlas">us-atlas</a>', '<a href="https://github.com/CSSEGISandData/COVID-19">JHU county population table</a>', '<a href="https://pypi.org/project/zipcodes/">zipcodes (PyPI)</a>',
 'Freight parameters, demand allocation, export gateway shares, owner shares and the outage calendar are the author\'s assumptions; see the notes in the repository.'])
fill = {
 "n_us_open": n_us_open, "n_nodes": len(D["nodes"]), "n_model_2026": len(act26),
 "cap_us_2024": MT1(cap_us_2024), "cap_us_2026": MT1(cap_us_2026), "ip_2024": MT(ip_2024), "sw_2026": MT(sw_2026), "pca_2026": MT(pca_2026), "closed_2526": MT1(closed_2526),
 "ship_2024": MT1(ship_us("fp2024")), "ship_2026": MT1(ship_us("fp2026")), "demand_2024": MT1(P["demand_2024"]), "demand_2026": MT1(P["demand_2026"]), "exports_2026": MT1(P["exports_2026"]),
 "n_vars": f"{k26['n_vars']:,}", "n_rows": f"{k26['n_rows']:,}", "solve_s": f"{k26['solve_seconds']:.1f}",
 "haul_2026": f"{k26['avg_haul_miles']:.0f}", "haul_2024": f"{k24['avg_haul_miles']:.0f}", "frt_2026": f"{k26['avg_freight_per_ton']:.0f}", "frt_2024": f"{k24['avg_freight_per_ton']:.0f}",
 "frt_pct": f"{k26['avg_freight_per_ton']/1000*100:.0f}", "rail_2026": f"{k26['rail_share']:.0%}",
 "ip_int": f"{ip['internal']/ip_tot*100:.0f}", "ip_exp": f"{ip['exports']/ip_tot*100:.0f}", "sw_int": f"{sw['internal']/sw_tot*100:.0f}",
 "integration_rows": "\n".join(rows), "west_shadow": f"{sum(west)/len(west):.0f}", "east_shadow": f"{sum(east)/len(east):.0f}",
 "cheap_nodes": cheap, "dear_nodes": dear, "month_text": month_text, "per_month_cap": co["per_month_cap"], "calopt_text": calopt_text, "ko_text": ko_text, "cf_text": cf_text,
 "python_excerpt": excerpt, "sources": sources,
}
tpl = open(os.path.join(HERE, "template.html")).read()
def render(extra):
    out = tpl
    for k, v in {**fill, **extra}.items(): out = out.replace("{{" + k + "}}", str(v))
    missing = re.findall(r"{{(\w+)}}", out)
    if missing: raise SystemExit("unfilled placeholders: " + ", ".join(missing))
    return out
post_css = open(os.path.join(HERE, "post.css")).read(); app_js = open(os.path.join(HERE, "app.js")).read()
site_css = open(os.path.join(SITE, "assets", "site.css")).read(); viz_js = open(os.path.join(SITE, "assets", "viz.js")).read(); theme_js = open(os.path.join(SITE, "assets", "theme.js")).read()
theme_btn = re.search(r'<button class="theme".*?</button>', open(os.path.join(SITE, "posts", "set-cover-plants.html")).read(), re.S).group(0)
data_js = "window.PN_DATA=" + json.dumps(D, separators=(",", ":")) + ";\nwindow.PN_BASEMAP=" + json.dumps(BM, separators=(",", ":")) + ";\n"
D3 = '<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>'
FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com">\n<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">'
TITLE = "The paper network: every containerboard mill, and who it ships to — Jason Fetzer"
DESC = "Every US containerboard mill from 10-Ks and press, box demand by county, and a min-cost transshipment model of the flows between them: the 2025 closures, a maintenance-outage calendar priced by the LP's duals, and single-mill knockouts, animated with d3."
# 1) blog post
os.makedirs(os.path.join(OUT, "site", "posts"), exist_ok=True); os.makedirs(os.path.join(OUT, "site", "models", "paper-network"), exist_ok=True)
body = render({"home": "../", "writing": "../#writing", "theme_button": theme_btn, "footer_link": '<a href="https://justfetz.github.io">justfetz.github.io</a>'})
post = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(TITLE)}</title>
<meta name="description" content="{html.escape(DESC)}">
{FONTS}
<link rel="stylesheet" href="../assets/site.css">
<style>
{post_css}</style>
</head>
<body>
<main class="page">
{body}
</main>
{D3}
<script src="../assets/viz.js"></script>
<script src="../assets/theme.js"></script>
<script src="../models/paper-network/data.js"></script>
<script>
{app_js}</script>
</body>
</html>
'''
open(os.path.join(OUT, "site", "posts", "paper-network.html"), "w").write(post)
open(os.path.join(OUT, "site", "models", "paper-network", "data.js"), "w").write(data_js)
# 2) artifact: self-contained page body (publish skeleton adds doctype/head/body)
os.makedirs(os.path.join(OUT, "artifact"), exist_ok=True)
art_css = site_css.replace(".page{max-width:680px;margin:0 auto;padding:48px 20px 96px}", ".page{max-width:680px;margin:0 auto;padding-block:40px 80px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}")
abody = render({"home": "https://justfetz.github.io/", "writing": "https://justfetz.github.io/#writing", "theme_button": "", "footer_link": '<a href="https://justfetz.github.io">justfetz.github.io</a>'})
artifact = f'''<title>The Paper Network</title>
<meta name="claude:viewport-fit-sides" content="cover">
{FONTS}
<style>
{art_css}
{post_css}
body{{margin:0}}
</style>
<main class="page">
{abody}
</main>
{D3}
<script>
{viz_js}</script>
<script>
{data_js}</script>
<script>
{app_js}</script>
'''
open(os.path.join(OUT, "artifact", "paper-network.html"), "w").write(artifact)
# 3) local test page (d3 inlined) for a headless screenshot
os.makedirs(os.path.join(OUT, "test"), exist_ok=True)
d3_local = open(os.path.join(HERE, "d3.min.js")).read() if os.path.exists(os.path.join(HERE, "d3.min.js")) else ""
test = "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>" + artifact.replace(D3, "<script>" + d3_local + "</script>").replace("<main", "</head><body><main", 1) + "</body></html>"
open(os.path.join(OUT, "test", "paper-network.html"), "w").write(test)
print("built:", {k: os.path.getsize(os.path.join(OUT, *p)) // 1024 for k, p in {"post": ("site", "posts", "paper-network.html"), "data.js": ("site", "models", "paper-network", "data.js"), "artifact": ("artifact", "paper-network.html"), "test": ("test", "paper-network.html")}.items()}, "KB")
print("key numbers:", {k: fill[k] for k in ["n_us_open", "cap_us_2024", "cap_us_2026", "ip_2024", "pca_2026", "closed_2526", "ship_2024", "ship_2026", "haul_2026", "frt_2026", "rail_2026", "ip_int", "ip_exp", "sw_int", "west_shadow", "east_shadow"]})
print(month_text); print(calopt_text); print(ko_text); print(cf_text)
