"""Run footprints, monthly maintenance calendar and knockouts; write compact JSON for the page."""
import json, sys, time, numpy as np, pandas as pd
sys.path.insert(0, ".")
from netmodel import *
from scenarios import SEASON, outage_calendar

def main(mills_csv, out_json, demand_2024=34.5e6, exports_2024=4.6e6, demand_2026=32.2e6, exports_2026=3.6e6,
         premium=150.0, knockout_top=20, shares=None):
    t0 = time.time()
    counties = pd.read_csv("../geo/counties.csv", dtype={"fips":str})
    nodes = aggregate_demand_nodes(county_weights(counties))
    allm = pd.read_csv(mills_csv)
    if "closed_year" not in allm:  # derive from notes for the seed file
        allm["closed_year"] = allm.status_note.fillna("").str.extract(r"closed[^0-9]*(20\d\d)")[0].astype(float)
    allm = allm[allm.lat.notna()].reset_index(drop=True)
    allm["gid"] = range(len(allm))
    model_ok = allm.country.isin(["US", "CA"])          # Mexican mills are listed for context but do not supply the US network
    shares = shares or {"International Paper":0.31,"Smurfit Westrock":0.20,"Packaging Corp of America":0.155,"Georgia-Pacific":0.095,
                        "Pratt Industries":0.06,"Green Bay Packaging":0.03,"Cascades":0.02}
    fp24 = allm[model_ok & ((allm.status_oct2026=="open") | (allm.closed_year.fillna(0) >= 2025))].reset_index(drop=True).copy()
    if "capacity_2024" in fp24: fp24["capacity_tons_per_year"] = fp24.capacity_2024.fillna(fp24.capacity_tons_per_year)
    if "owner_2024" in fp24: fp24["owner"] = fp24.owner_2024.fillna(fp24.owner)
    fp26 = allm[model_ok & (allm.status_oct2026=="open")].reset_index(drop=True)
    def pack(res, fp, label, kind, extra=None, base=None):
        M, N, ship, exp = res["mills"], res["nodes"], res["ship"], res["exports"]
        util = np.zeros(len(allm)); shadow = np.zeros(len(allm)); shipped = np.zeros(len(allm))
        util[fp.gid.values] = M.utilization.values; shadow[fp.gid.values] = M.capacity_shadow_price.values; shipped[fp.gid.values] = M.shipped_tons.values
        arcs = ship.groupby(["m","j","kind"]).tons.sum().reset_index()
        arcs = arcs[arcs.tons >= 1000]
        arcs_out = [[int(fp.gid.values[r.m]), int(r.j), int(round(r.tons)), 1 if r.kind=="x" else 0] for r in arcs.itertuples()]
        ex = exp.groupby(["m","g"]).tons.sum().reset_index()
        ex_out = [[int(fp.gid.values[r.m]), int(r.g), int(round(r.tons))] for r in ex.itertuples() if r.tons >= 1000]
        if base is not None:
            b = {(a[0],a[1],a[3]): a[2] for a in base["arcs"]}
            cur = {(a[0],a[1],a[3]): a[2] for a in arcs_out}
            keys = set(b) | set(cur)
            arcs_out = [[k[0], k[1], cur.get(k,0), k[2]] for k in keys if abs(cur.get(k,0)-b.get(k,0)) >= 2000]
        bands = [(0,150),(150,300),(300,500),(500,800),(800,1200),(1200,9999)]
        haul = [[f"{a}-{b}" if b < 9999 else f"{a}+", int(round(ship[(ship.miles>=a)&(ship.miles<b)&(~ship.rail)].tons.sum())), int(round(ship[(ship.miles>=a)&(ship.miles<b)&(ship.rail)].tons.sum()))] for a,b in bands]
        d = dict(label=label, kind=kind, delta_of=("fp2026" if base is not None else None), active=[int(g) for g in fp.gid.values], haul=haul, kpi={k: (round(v,3) if isinstance(v,float) else v) for k,v in res["kpi"].items()},
                 util=[round(float(u),3) for u in util], shipped=[int(round(s)) for s in shipped], shadow=[round(float(s),1) for s in shadow],
                 node_mc=[round(float(v),1) for v in N.marginal_delivered_cost_L], node_demand=[int(round(v)) for v in N.demand_tons],
                 arcs=arcs_out, exports=ex_out, integration={k: {a: int(round(b)) for a,b in v.items()} for k,v in res["integration"].items()})
        if extra: d.update(extra)
        return d
    scen = {}
    r24 = build_and_solve(fp24, nodes, demand_2024, shares, exports_2024, premium=premium, verbose=False)
    scen["fp2024"] = pack(r24, fp24, "End of 2024 footprint", "footprint", dict(demand_tons=demand_2024, export_tons=exports_2024))
    r26 = build_and_solve(fp26, nodes, demand_2026, shares, exports_2026, premium=premium, verbose=False)
    scen["fp2026"] = pack(r26, fp26, "October 2026 footprint", "footprint", dict(demand_tons=demand_2026, export_tons=exports_2026))
    rcf = build_and_solve(fp26, nodes, demand_2024, shares, exports_2024, premium=premium, verbose=False)
    scen["cf2026"] = pack(rcf, fp26, "October 2026 mills, 2024 demand", "footprint", dict(demand_tons=demand_2024, export_tons=exports_2024))
    print(f"footprints done {time.time()-t0:.0f}s", scen["fp2024"]["kpi"]["avg_haul_miles"], scen["fp2026"]["kpi"]["avg_haul_miles"])
    cal, avail = outage_calendar(fp26)
    months = {}
    for mo in range(1,13):
        r = build_and_solve(fp26, nodes, demand_2026*SEASON[mo], shares, exports_2026, availability=avail[mo-1], premium=premium, verbose=False)
        extra = dict(month=mo, season=SEASON[mo], mills_down=[int(fp26.gid.values[i]) for i in np.where(avail[mo-1] < 0.96)[0]],
                     tons_offline=int(round((fp26.capacity_tons_per_year.values*(1-avail[mo-1]/0.97)).sum()/12)))
        scen[f"m{mo:02d}"] = pack(r, fp26, f"2026 maintenance calendar, month {mo}", "month", extra=extra, base=scen["fp2026"])
    print(f"months done {time.time()-t0:.0f}s")
    # ---- outage calendar as an assignment problem priced by the flow LP's duals
    from scipy.optimize import milp, LinearConstraint, Bounds
    n = len(fp26); S = np.zeros((12, n)); noout = {}
    for mo in range(1, 13):
        r = build_and_solve(fp26, nodes, demand_2026*SEASON[mo], shares, exports_2026, availability=np.full(n, 0.97), premium=premium, verbose=False)
        S[mo-1] = r["mills"].capacity_shadow_price.values
        noout[mo] = dict(freight_usd=r["kpi"]["freight_usd"], objective_usd=r["kpi"]["objective_usd"], avg_haul_miles=r["kpi"]["avg_haul_miles"], unmet_tons=r["kpi"]["unmet_tons"])
    tons_off = fp26.capacity_tons_per_year.values/12.0 * cal.days.values/30.0
    C = S * tons_off[None, :]
    rand_est = float(sum(C[cal.month.values[i]-1, i] for i in range(n)))
    nv = 12*n; c = C.flatten()
    A1 = np.zeros((n, nv))
    for i in range(n): A1[i, i::n] = 1
    A2 = np.zeros((12, nv))
    for m in range(12): A2[m, m*n:(m+1)*n] = 1
    owners_u = sorted(set(fp26.owner)); A3 = np.zeros((12*len(owners_u), nv))
    for oi, o in enumerate(owners_u):
        idx = np.where(fp26.owner.values == o)[0]
        for m in range(12): A3[oi*12+m, m*n+idx] = 1
    cons = [LinearConstraint(A1, 1, 1), LinearConstraint(A2, 0, int(np.ceil(n/8))), LinearConstraint(A3, 0, 2)]
    res = milp(c, constraints=cons, integrality=np.ones(nv), bounds=Bounds(0, 1))
    X = res.x.reshape(12, n); opt_month = X.argmax(axis=0) + 1
    opt_est = float(res.fun)
    avail_opt = np.full((12, n), 0.97)
    for i in range(n): avail_opt[opt_month[i]-1, i] *= (1 - cal.days.values[i]/30.0)
    for mo in range(1, 13):
        r = build_and_solve(fp26, nodes, demand_2026*SEASON[mo], shares, exports_2026, availability=avail_opt[mo-1], premium=premium, verbose=False)
        extra = dict(month=mo, season=SEASON[mo], mills_down=[int(fp26.gid.values[i]) for i in np.where(avail_opt[mo-1] < 0.96)[0]],
                     tons_offline=int(round((fp26.capacity_tons_per_year.values*(1-avail_opt[mo-1]/0.97)).sum()/12)))
        scen[f"o{mo:02d}"] = pack(r, fp26, f"2026 optimized outage calendar, month {mo}", "month", extra=extra, base=scen["fp2026"])
    for mo in range(1, 13):
        for pfx in ("m", "o"):
            scen[f"{pfx}{mo:02d}"]["noout"] = noout[mo]
            scen[f"{pfx}{mo:02d}"]["outage_penalty_usd"] = round((scen[f"{pfx}{mo:02d}"]["kpi"]["objective_usd"] - noout[mo]["objective_usd"])/12)   # network cost: freight + outside purchases at $150/t + unmet at $400/t
    rand_actual = float(sum(scen[f"m{mo:02d}"]["outage_penalty_usd"] for mo in range(1, 13)))
    opt_actual = float(sum(scen[f"o{mo:02d}"]["outage_penalty_usd"] for mo in range(1, 13)))
    calendar_opt = dict(random_est=rand_est, opt_est=opt_est, random_actual_annual_penalty=rand_actual, opt_actual_annual_penalty=opt_actual,
                        per_month_cap=int(np.ceil(n/8)), per_owner_month_cap=2,
                        assignments=[dict(mill=int(fp26.gid.values[i]), random_month=int(cal.month.values[i]), opt_month=int(opt_month[i]), days=int(cal.days.values[i]),
                                          est_cost_random=round(float(C[cal.month.values[i]-1, i])), est_cost_opt=round(float(C[opt_month[i]-1, i]))) for i in range(n)],
                        monthly_shadow_mean=[round(float(S[m].mean()), 1) for m in range(12)])
    print(f"calendar optimisation done {time.time()-t0:.0f}s: est random ${rand_est/1e6:.1f}M vs opt ${opt_est/1e6:.1f}M; actual annual penalty random ${rand_actual/1e6:.1f}M vs opt ${opt_actual/1e6:.1f}M")
    base_f = r26["kpi"]["freight_usd"]; base_obj = r26["kpi"]["objective_usd"]
    kos = []
    big = fp26.sort_values("capacity_tons_per_year", ascending=False).head(knockout_top)
    for i, row in big.iterrows():
        a = np.ones(len(fp26)); a[i] = 0.0
        r = build_and_solve(fp26, nodes, demand_2026, shares, exports_2026, availability=a, premium=premium, verbose=False)
        key = f"ko{int(row.gid)}"
        scen[key] = pack(r, fp26, f"Knockout: {row.mill_name}, {row.state}", "knockout", dict(mill=int(row.gid)), base=scen["fp2026"])
        kos.append(dict(mill=int(row.gid), name=row.mill_name, owner=row.owner, st=row.state, cap=int(row.capacity_tons_per_year),
                        d_freight=round(r["kpi"]["freight_usd"]-base_f), d_total=round(r["kpi"]["objective_usd"]-base_obj),
                        unmet=round(r["kpi"]["unmet_tons"]), d_haul=round(r["kpi"]["avg_haul_miles"]-r26["kpi"]["avg_haul_miles"],1),
                        owner_buys=round(r["kpi"]["owner_purchased_from_market_tons"])))
    print(f"knockouts done {time.time()-t0:.0f}s")
    # ---- unilateral price increases on the open market: who switches?
    base_y = r26["ship"][r26["ship"].kind == "y"].groupby(["m", "j", "g"]).tons.sum()
    price_shocks = {}
    for owner in ["International Paper", "Smurfit Westrock", "Packaging Corp of America", "Georgia-Pacific", "Pratt Industries"]:
        if not (fp26.owner == owner).any(): continue
        r = build_and_solve(fp26, nodes, demand_2026, shares, exports_2026, premium=premium, verbose=False, market_surcharge={owner: 70.0})
        y = r["ship"][r["ship"].kind == "y"].groupby(["m", "j", "g"]).tons.sum()
        own_m = set(np.where(fp26.owner.values == owner)[0])
        lost = base_y[[k[0] in own_m for k in base_y.index]]
        lost_after = y.reindex(lost.index).fillna(0)
        delta = (lost - lost_after); delta = delta[delta > 1000]
        calls = []
        for (mi, j, g), t in delta.sort_values(ascending=False).items():
            gained = y[[(k[1] == j and k[2] == g and k[0] not in own_m) for k in y.index]]
            to = gained.sort_values(ascending=False)
            to_m = int(to.index[0][0]) if len(to) else None
            calls.append(dict(node=int(j), grade=g, from_mill=int(fp26.gid.values[mi]), to_mill=(int(fp26.gid.values[to_m]) if to_m is not None else None), tons=int(round(t))))
        scen[f"ps_{owner}"] = pack(r, fp26, f"{owner} raises open-market price $70/t", "shock", base=scen["fp2026"])
        price_shocks[owner] = dict(base_market_tons=int(round(lost.sum())), market_tons_after=int(round(lost_after.sum())), calls=calls[:400],
                                   d_cost=round(r["kpi"]["objective_usd"] - r26["kpi"]["objective_usd"]))
    print(f"price shocks done {time.time()-t0:.0f}s")
    # ---- prospects: cheapest and second-cheapest supplier by delivered freight for each demand point
    pr_L = prospects(fp26, nodes, grade="L"); pr_M = prospects(fp26, nodes, grade="M")
    for lst in (pr_L, pr_M):
        for p in lst:
            for k in ("best", "second", "third"): p[k] = int(fp26.gid.values[p[k]])
    # ---- diesel sensitivity
    diesel = {}
    for dz in (3.0, 5.0, 6.2):
        r = build_and_solve(fp26, nodes, demand_2026, shares, exports_2026, premium=premium, verbose=False, diesel=dz)
        scen[f"dz{int(dz)}"] = pack(r, fp26, f"Diesel at ${dz:.2f}/gal", "diesel", base=scen["fp2026"], extra=dict(diesel=dz))
        diesel[str(dz)] = dict(freight_usd=r["kpi"]["freight_usd"], rail_share=r["kpi"]["rail_share"], avg_haul=r["kpi"]["avg_haul_miles"], avg_freight_per_ton=r["kpi"]["avg_freight_per_ton"])
    diesel["3.75"] = dict(freight_usd=r26["kpi"]["freight_usd"], rail_share=r26["kpi"]["rail_share"], avg_haul=r26["kpi"]["avg_haul_miles"], avg_freight_per_ton=r26["kpi"]["avg_freight_per_ton"])
    print(f"diesel done {time.time()-t0:.0f}s")
    # ---- the fiber loop
    occ = solve_occ(fp26, nodes, r26["nodes"].demand_tons.values*1.03, recovery_rate=0.92, export_tons=8.4e6, utilization=r26["mills"].utilization.values, verbose=True)
    sinks = [(("mill", int(fp26.gid.values[i])) if kind == "mill" else ("port", i)) for kind, i in occ["sinks"]]
    occ_out = dict(kpi={k: round(float(v), 3) for k, v in occ["kpi"].items()}, sinks=sinks, ports=[dict(name=r.port, lat=float(r.lat), lon=float(r.lon), share=float(r.share)) for r in OCC_PORTS.itertuples()],
                   flows=[[int(j), int(k), int(round(t))] for j, k, t in occ["flows"]], supply=[int(round(v)) for v in occ["supply"]], demand=[int(round(v)) for v in occ["demand"]],
                   surplus=[int(round(v)) for v in occ["surplus"]], county_value=[round(float(v), 1) for v in occ["county_value"]])
    # ---- closure backtest: 2024 footprint facing 2026 demand; who does the LP leave idle?
    rbt = build_and_solve(fp24, nodes, demand_2026, shares, exports_2026, premium=premium, verbose=False)
    Mb = rbt["mills"]
    bt = [dict(mill=int(fp24.gid.values[i]), name=Mb.mill_name.values[i], owner=Mb.owner.values[i], st=Mb.state.values[i], cap=int(Mb.capacity_tons_per_year.values[i]),
               utilization=round(float(Mb.utilization.values[i]), 3), shadow=round(float(Mb.capacity_shadow_price.values[i]), 1),
               closed_2025_26=bool(allm.loc[allm.gid == fp24.gid.values[i], "status_oct2026"].iloc[0] == "closed")) for i in range(len(fp24))]
    print(f"backtest done {time.time()-t0:.0f}s")
    out = dict(
        generated=time.strftime("%Y-%m-%d"),
        params=dict(premium=premium, freight=FREIGHT, demand_2024=demand_2024, exports_2024=exports_2024, demand_2026=demand_2026, exports_2026=exports_2026, shares=shares, season=SEASON),
        mills=[dict(id=int(r.gid), name=r.mill_name, owner=r.owner, owner_2024=(r.owner_2024 if "owner_2024" in allm else r.owner), cap_2024=int(r.capacity_2024 if "capacity_2024" in allm and not pd.isna(r.capacity_2024) else r.capacity_tons_per_year), city=r.city, st=r.state, country=r.country, lat=float(r.lat), lon=float(r.lon),
                    cap=int(r.capacity_tons_per_year), grades=r.grades, status=r.status_oct2026, closed_year=(None if pd.isna(r.closed_year) else int(r.closed_year)),
                    note=("" if pd.isna(r.status_note) else str(r.status_note)), conf=str(r.confidence)) for r in allm.itertuples()],
        nodes=[dict(id=str(r.node_id), name=r.name, st=r.st, lat=float(r.lat), lon=float(r.lon), pop=int(r.pop_served)) for r in nodes.itertuples()],
        ports=[dict(name=r.port, lat=float(r.lat), lon=float(r.lon), share=float(r.share)) for r in PORTS.itertuples()],
        calendar=[dict(mill=int(fp26.gid.values[i]), month=int(r.month), days=int(r.days)) for i, r in cal.iterrows()], calendar_opt=calendar_opt,
        knockouts=kos, price_shocks=price_shocks, prospects=dict(L=pr_L, M=pr_M), diesel=diesel, occ=occ_out, backtest=bt, scenarios=scen)
    json.dump(out, open(out_json, "w"), separators=(",",":"))
    import os; print("wrote", out_json, f"{os.path.getsize(out_json)/1e6:.2f} MB in {time.time()-t0:.0f}s")
    return out

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
