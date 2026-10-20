"""Scenario runner: footprints (2024 vs Oct-2026), monthly maintenance calendar, single-mill knockouts -> JSON for the viz."""
import json, sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from netmodel import *

SEASON = {1:0.95,2:0.93,3:1.02,4:0.99,5:1.01,6:1.02,7:0.99,8:1.03,9:1.03,10:1.05,11:1.00,12:0.98}  # box-shipment seasonality (assumption)
def outage_calendar(mills, seed=7, kraft_days=9, recycled_days=5, unplanned=0.03):
    """One planned maintenance outage per mill per year, staggered spring/fall by owner; plus unplanned downtime."""
    rng = np.random.default_rng(seed)
    cal = []
    for i, r in mills.reset_index(drop=True).iterrows():
        kraft = "kraft" in str(r.grades) or "white_top" in str(r.grades)
        days = kraft_days if kraft else recycled_days
        month = int(rng.choice([3,4,5,9,10,11], p=[.18,.2,.12,.17,.2,.13]))
        cal.append(dict(mill=r.mill_name, owner=r.owner, month=month, days=days))
    cal = pd.DataFrame(cal)
    avail = np.ones((12, len(mills))) * (1-unplanned)
    for i, r in cal.iterrows():
        avail[r.month-1, i] *= (1 - r.days/30.0)
    return cal, avail

def run_all(mills_all, nodes, shares, demand_2024, demand_2026, exports_2024, exports_2026, premium=150.0, knockout_top=20):
    out = {"scenarios": {}, "mills": None, "nodes": None}
    def footprint(year):
        m = mills_all.copy()
        if year == 2024:  # mills open at end-2024: exclude those closed before 2025
            return m[(m.status_oct2026=="open") | (m.closed_year.fillna(0) >= 2025)]
        return m[m.status_oct2026=="open"]
    results = {}
    base24 = build_and_solve(footprint(2024), nodes, demand_2024, shares, exports_2024, premium=premium, verbose=False)
    base26 = build_and_solve(footprint(2026), nodes, demand_2026, shares, exports_2026, premium=premium, verbose=False)
    results["footprint_2024"] = (footprint(2024), base24); results["footprint_2026"] = (footprint(2026), base26)
    m26 = footprint(2026).reset_index(drop=True)
    cal, avail = outage_calendar(m26)
    monthly = {}
    for mo in range(1, 13):
        r = build_and_solve(m26, nodes, demand_2026*SEASON[mo], shares, exports_2026, availability=avail[mo-1], premium=premium, verbose=False)
        monthly[mo] = r
    # knockouts: remove each of the largest mills (by capacity) one at a time
    kos = {}
    big = m26.sort_values("capacity_tons_per_year", ascending=False).head(knockout_top)
    for i, r in big.iterrows():
        a = np.ones(len(m26)); a[i] = 0.0
        kos[r.mill_name] = build_and_solve(m26, nodes, demand_2026, shares, exports_2026, availability=a, premium=premium, verbose=False)
    return results, cal, monthly, kos
