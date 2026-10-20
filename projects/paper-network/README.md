# The paper network (course write-up snapshot)

> The project now lives at **https://github.com/justfetz/the-paper-network** (model, data, notes, dashboard, ingestion scripts). This folder keeps the CS 535 Lecture-7 framing: the write-up page in `out/` and the model as it stood at the first run; see the main repo for the current version.

A free-data model of the US containerboard → corrugated box supply chain, solved as a
min-cost transshipment problem (CS 535, Lecture 7), with the 2025 mill closures, a
maintenance-outage calendar priced by the LP's dual values, and single-mill knockouts.
The write-up and interactive map are in `page/` (built HTML in `out/`).

## What is in here

| Path | What it is |
|---|---|
| `data/mills_final.csv` | 90 North American containerboard mills: owner (2026 and end-2024), city/state, grades, capacity (short tons/yr, with a 2024 value where it changed), status, closure year, source basis, confidence flag, coordinates. US + Canada rows enter the model; Mexico rows are listed only. |
| `data/mills_ip_sw.csv`, `data/mills_others.csv` | The research files the final table was merged from (per-row source URLs and capacity basis). `mills_seed.csv` is the prior-knowledge seed used to cross-check them. |
| `data/counties.csv` | 3,142 US counties: centroid (from us-atlas), population (JHU lookup table). Demand proxy. |
| `data/basemap.json` | State and nation outlines pre-projected to the Albers USA frame (975×610) as SVG paths. |
| `notes/industry_calibration.md` | Every industry-level number used for calibration (AF&PA capacity and production, FBA box shipments, imports, operating rates, integration rates, outage economics, prices) with year, unit, URL and a confidence note. |
| `notes/plants_*.md`, `notes/plants_by_state.csv` | What could be found about box-plant counts, locations, integration and outage practice by company. |
| `model/netmodel.py` | The LP: demand aggregation, freight function, ownership-aware transshipment, duals. |
| `model/export_json.py` | Scenario runner: end-2024 and October-2026 footprints, a counterfactual (2026 mills, 2024 demand), 12 months of a staggered outage calendar, an outage-calendar assignment problem priced by capacity duals and its re-solved months, 20 single-mill knockouts. Writes the JSON the page reads. |
| `model/merge_mills.py`, `model/geocode_mills.py` | Merge and offline geocoding (PyPI `zipcodes` + manual coordinates). |
| `page/` | `template.html` (prose + controls), `app.js` (d3 map and charts), `post.css`, `build_page.py` (fills the template with model numbers and emits the blog post, a standalone artifact page and a local test page). |

## How to run

```bash
pip install numpy pandas scipy zipcodes geonamescache
cd model
python merge_mills.py ../data/mills_final.csv            # optional: regenerate the merged table from the research files
python export_json.py ../data/mills_final.csv ../data/paper_network.json   # ~4 minutes: 49 LP solves + one small MILP
cd ../page && python build_page.py                        # writes out/site/posts/paper-network.html, out/site/models/paper-network/data.js, out/artifact/paper-network.html
```

`export_json.py` expects `../geo/counties.csv` relative to `model/` in the original layout; in this folder pass the path in `data/` (edit the one line at the top of `main`) or symlink `geo -> data`.

## The model in one paragraph

Mills are sources with annual capacity and a set of grades (kraft or recycled liner, semichem or recycled medium). Demand points are the 441 largest counties, each carrying the smaller counties around it, with tons of board proportional to population tilted toward states with more manufacturing employment; two thirds liner, one third medium. Freight per ton is `min(8 + 0.125·d, 35 + 0.065·d)` dollars at road distance `d = 1.2 ×` great-circle miles, which puts the truck/rail break near 450 miles. Integrated owners (IP, Smurfit Westrock, PCA, Georgia-Pacific, Pratt, Green Bay Packaging, Cascades) each get their own copy of every demand point holding their share of the local box market, and only their own mills can serve it; an arc from the open market into each owner copy at $150/ton lets an owner buy outside when short. Exports leave through twelve gateways in fixed shares. Splitting each mill into a liner node and a medium node behind one capacity arc keeps grades honest without a second commodity. The result is one min-cost flow on an expanded network; HiGHS solves the October 2026 instance (≈80k variables, ≈7k rows) in about three seconds. Capacity duals give the value of one more ton at each mill; demand duals give the delivered marginal cost in each county.

## Assumptions to know about

- **Demand geography** is a population proxy, not a plant list. The ~1,150 US box plants are not public with tonnage.
- **Owner shares** of the box market are national (IP 31%, SW 20%, PCA 15.5%, GP 9.5%, Pratt 6%, GBP 3%, Cascades 2%, independents 13%). Real footprints are regional.
- **Demand totals**: 34.5 Mt domestic + 4.6 Mt exports for 2024; 32.2 Mt + 3.6 Mt for 2026. AF&PA production was 37.7 Mt (2024) and 36.1 Mt (2025); imports 1.4 Mt (2024). Annual export tonnage is not published free; it is inferred from production, imports and the FBA shipment series.
- **Canadian mills** sell 35% of capacity into the US; Mexican mills are excluded.
- **Freight** is two straight lines. No lane rates, backhaul, car supply or transload economics.
- **Outage calendar**: one planned outage per mill per year (9 days kraft, 5 recycled), drawn into spring and fall months with a fixed seed, plus 3% unplanned downtime; box-demand seasonality is a hand-set monthly index. The optimized calendar minimizes Σ (capacity dual × tons lost) subject to at most ⌈n/8⌉ mills down per month and two per owner per month, then is re-solved month by month to measure the actual freight penalty.
- **Mill capacities** are public figures of mixed vintage. Owner totals reconcile to the 10-Ks (IP US end-2024 within 1%; SW's US mills are the 10-K table; PCA within 3%); any single IP or PCA legacy mill could be off by 10%.

## Sources

See `notes/industry_calibration.md` and the per-row `source_url` columns in the mill files. Headline anchors: IP 10-K FY2024 Appendix II (12,984 kt US containerboard capacity); Smurfit Westrock 10-K FY2024/FY2025 mill table; PCA 10-K FY2025 (5.8 Mt, 358 BSF, ten mills, 91 box plants); AF&PA annual capacity survey (42.3 Mt record in 2021; −5.1% in 2025; 36.1 Mt produced in 2025); Fastmarkets RISI (3.9 Mt retired Feb 2025–Mar 2026; 42-lb kraft liner $990–1,000/t May 2026); Fibre Box Association (381 BSF shipped in 2024); AICC (~1,150 US box plants); closure announcements from IP, Georgia-Pacific, Smurfit Westrock and Cascades; PCA Q1 2026 call ($1.44/share of 2026 outage expense).
