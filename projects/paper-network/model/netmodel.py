"""
Containerboard network model: mills -> corrugator demand nodes (+ export ports), solved as a
min-cost transshipment LP (HiGHS via scipy). Integrated owners serve their own box plants first;
the open market (independents + majors' surplus) clears the rest.
"""
import json, math, time
import numpy as np, pandas as pd
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

R_MI = 3958.8
def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2-lat1)/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
    return 2*R_MI*np.arcsin(np.sqrt(a))

# --- freight: $/ton as a function of great-circle miles (road factor 1.2). Truck vs rail breakpoint ~450 mi.
FREIGHT = dict(road_factor=1.2, truck_fixed=8.0, truck_per_mi=0.125, rail_fixed=35.0, rail_per_mi=0.065)
DIESEL_BASE = 3.75   # $/gal; fuel is ~22% of truck cost per mile and ~12% of rail cost per mile at this price
def freight_cost(gc_miles, p=FREIGHT, diesel=DIESEL_BASE):
    road = gc_miles * p["road_factor"]
    ft = 1 + 0.22*(diesel/DIESEL_BASE - 1); fr = 1 + 0.12*(diesel/DIESEL_BASE - 1)
    truck = p["truck_fixed"] + p["truck_per_mi"]*road*ft
    rail = p["rail_fixed"] + p["rail_per_mi"]*road*fr
    return np.minimum(truck, rail), (rail < truck)

# --- state manufacturing share of nonfarm employment (%, approx 2023 BLS) used to tilt box demand toward industrial states
MFG_SHARE = {"AL":13.0,"AK":3.5,"AZ":6.3,"AR":12.0,"CA":7.0,"CO":5.3,"CT":9.4,"DE":5.8,"FL":4.3,"GA":8.5,"HI":2.1,"ID":8.6,
 "IL":9.3,"IN":16.5,"IA":14.0,"KS":12.0,"KY":12.5,"LA":6.9,"ME":8.2,"MD":4.1,"MA":6.2,"MI":13.3,"MN":10.6,"MS":12.2,"MO":9.5,
 "MT":4.3,"NE":9.7,"NV":4.2,"NH":9.6,"NJ":5.9,"NM":3.3,"NY":4.3,"NC":9.6,"ND":6.2,"OH":12.3,"OK":8.1,"OR":9.5,"PA":9.2,"RI":7.8,
 "SC":11.3,"SD":10.2,"TN":10.9,"TX":6.8,"UT":8.1,"VT":9.2,"VA":6.0,"WA":7.8,"WV":6.6,"WI":16.0,"WY":3.4,"DC":0.2}
US_MFG_AVG = 8.4
STATE_ABBR = {"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO","Connecticut":"CT","Delaware":"DE",
 "Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA",
 "Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE",
 "Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH",
 "Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX",
 "Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY","District of Columbia":"DC"}

def county_weights(counties, mfg_tilt=0.5, state_weights=None):
    """Box-demand proxy per county. Default: population tilted by state manufacturing intensity.
    If state_weights (dict state_abbr -> target share) is given, rescale so each state's total matches it."""
    c = counties.copy()
    c["st"] = c.state.map(STATE_ABBR)
    c = c[c.st.notna() & ~c.st.isin(["AK","HI"])].copy()
    tilt = c.st.map(MFG_SHARE).fillna(US_MFG_AVG)/US_MFG_AVG
    c["w"] = c["pop"] * ((1-mfg_tilt) + mfg_tilt*tilt)
    if state_weights:
        tot = c.groupby("st").w.transform("sum")
        c["w"] = c.w/tot * c.st.map(state_weights).fillna(0) * c.w.sum()
    return c

def aggregate_demand_nodes(c, min_pop=150_000, max_assign_mi=250):
    """Counties with pop >= min_pop (plus each state's largest county) become demand nodes; others roll up to nearest node."""
    big = c[c["pop"] >= min_pop]
    tops = c.sort_values("pop", ascending=False).groupby("st").head(1)
    nodes = pd.concat([big, tops]).drop_duplicates("fips").copy()
    small = c[~c.fips.isin(nodes.fips)]
    d = haversine(small.lat.values[:,None], small.lon.values[:,None], nodes.lat.values[None,:], nodes.lon.values[None,:])
    nearest = d.argmin(axis=1)
    nodes["w_total"] = nodes.w.values
    add = pd.Series(small.w.values).groupby(nearest).sum()
    nodes.iloc[add.index, nodes.columns.get_loc("w_total")] += add.values
    nodes["pop_served"] = nodes["pop"].values
    addp = pd.Series(small["pop"].values).groupby(nearest).sum()
    nodes.iloc[addp.index, nodes.columns.get_loc("pop_served")] += addp.values
    nodes = nodes.reset_index(drop=True)
    nodes["node_id"] = nodes.fips
    nodes["name"] = nodes.county + ", " + nodes.st
    return nodes[["node_id","name","st","lat","lon","pop","pop_served","w_total"]]

# --- export gateways (share of US containerboard export tons; assumption, see notes)
PORTS = pd.DataFrame([
    ("Laredo TX (rail/truck to Mexico)", 27.51, -99.51, 0.28),
    ("Savannah GA", 32.08, -81.09, 0.14), ("Charleston SC", 32.78, -79.93, 0.07), ("Jacksonville FL", 30.33, -81.66, 0.05),
    ("Port Everglades FL", 26.09, -80.12, 0.04), ("Mobile AL", 30.69, -88.04, 0.05), ("New Orleans LA", 29.95, -90.07, 0.08),
    ("Houston TX", 29.76, -95.37, 0.10), ("Norfolk VA", 36.85, -76.29, 0.04), ("Los Angeles/Long Beach CA", 33.75, -118.22, 0.08),
    ("Seattle/Tacoma WA", 47.27, -122.42, 0.05), ("Detroit/Buffalo (to Canada)", 42.33, -83.05, 0.02)],
    columns=["port","lat","lon","share"])

def build_and_solve(mills, nodes, total_demand_tons, owner_shares, export_tons, grade_split=(0.65,0.35),
                    availability=None, premium=15.0, unmet_penalty=400.0, canada_factor=0.35, verbose=True,
                    diesel=DIESEL_BASE, market_surcharge=None):
    """market_surcharge: dict owner -> $/ton added to that owner's OPEN-MARKET offers (a unilateral price increase);
    integrated flows to its own plants are unaffected, so the solver shows which independents switch away."""
    """
    mills: DataFrame[owner, mill_name, lat, lon, capacity_tons_per_year, grades, country, status]
    nodes: DataFrame[node_id, name, lat, lon, w_total]
    owner_shares: dict owner -> share of US box demand served by that owner's box plants (rest = open market)
    availability: array (per mill) in [0,1], default 1
    """
    t0 = time.time()
    M = mills.reset_index(drop=True).copy()
    cap = M.capacity_tons_per_year.values.astype(float)
    if availability is None: availability = np.ones(len(M))
    cap = cap * availability * np.where(M.country.eq("US"), 1.0, canada_factor)
    liner_ok = M.grades.str.contains("linerboard").values
    medium_ok = M.grades.str.contains("medium").values
    kraft = M.grades.str.contains("kraft_linerboard|white_top").values
    N = nodes.reset_index(drop=True)
    J = len(N); nM = len(M)
    D = N.w_total.values/N.w_total.sum()*total_demand_tons
    dist = haversine(M.lat.values[:,None], M.lon.values[:,None], N.lat.values[None,:], N.lon.values[None,:])
    cost, by_rail = freight_cost(dist, diesel=diesel)
    pdist = haversine(M.lat.values[:,None], M.lon.values[:,None], PORTS.lat.values[None,:], PORTS.lon.values[None,:])
    pcost, _ = freight_cost(pdist, diesel=diesel)
    surcharge = np.array([(market_surcharge or {}).get(o, 0.0) for o in M.owner.values])
    owners = [k for k in owner_shares if (M.owner==k).any()]
    s_open = 1.0 - sum(owner_shares[k] for k in owners)
    grades = [("L", grade_split[0], liner_ok), ("M", grade_split[1], medium_ok)]
    # ---- variable bookkeeping
    cols = []  # (kind, k, m, j, g) ; kind in x,y,v,z,u
    c_obj = []
    rows_cap, rows_own, rows_open, rows_exp = [], {}, {}, []
    A_r, A_c, A_v = [], [], []
    def addvar(kind, k, m, j, g, c):
        cols.append((kind, k, m, j, g)); c_obj.append(c); return len(cols)-1
    # constraint indices
    cap_row = {m: m for m in range(nM)}
    nrow = nM
    own_row = {}
    for k in owners:
        for j in range(J):
            for gi,(g,_,_) in enumerate(grades):
                own_row[(k,j,g)] = nrow; nrow += 1
    open_row = {}
    for j in range(J):
        for g,_,_ in grades:
            open_row[(j,g)] = nrow; nrow += 1
    exp_row = {p: nrow+p for p in range(len(PORTS))}; nrow += len(PORTS)
    def coef(r, cidx, v): A_r.append(r); A_c.append(cidx); A_v.append(v)
    owner_of = M.owner.values
    for m in range(nM):
        if cap[m] <= 0: continue
        for g, phi, ok in grades:
            if not ok[m]: continue
            for j in range(J):
                # open-market arc
                ci = addvar("y", None, m, j, g, cost[m,j] + surcharge[m]); coef(cap_row[m], ci, 1); coef(open_row[(j,g)], ci, 1)
                k = owner_of[m]
                if k in owner_shares and k in owners:
                    ci = addvar("x", k, m, j, g, cost[m,j]); coef(cap_row[m], ci, 1); coef(own_row[(k,j,g)], ci, 1)
        if kraft[m]:
            for p in range(len(PORTS)):
                ci = addvar("z", None, m, None, p, pcost[m,p]); coef(cap_row[m], ci, 1); coef(exp_row[p], ci, 1)
    for k in owners:
        for j in range(J):
            for g,_,_ in grades:
                ci = addvar("v", k, None, j, g, premium); coef(own_row[(k,j,g)], ci, 1); coef(open_row[(j,g)], ci, -1)
    for j in range(J):
        for g,_,_ in grades:
            ci = addvar("u", None, None, j, g, unmet_penalty); coef(open_row[(j,g)], ci, 1)
    nvar = len(cols)
    A = coo_matrix((A_v, (A_r, A_c)), shape=(nrow, nvar)).tocsr()
    # split into inequality (capacity rows) and equality rows
    A_ub = A[:nM]; b_ub = cap
    A_eq = A[nM:]
    b_eq = np.zeros(nrow-nM)
    for k in owners:
        for j in range(J):
            for g, phi, _ in grades:
                b_eq[own_row[(k,j,g)]-nM] = owner_shares[k]*phi*D[j]
    for j in range(J):
        for g, phi, _ in grades:
            b_eq[open_row[(j,g)]-nM] = s_open*phi*D[j]
    for p in range(len(PORTS)):
        b_eq[exp_row[p]-nM] = export_tons*PORTS.share.values[p]
    res = linprog(np.array(c_obj), A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=(0,None), method="highs")
    if res.status != 0: raise RuntimeError(res.message)
    xv = res.x
    # ---- unpack
    kinds = np.array([c[0] for c in cols]); mm = np.array([c[2] if c[2] is not None else -1 for c in cols])
    jj = np.array([c[3] if c[3] is not None else -1 for c in cols]); gg = np.array([c[4] for c in cols], dtype=object)
    kk = np.array([c[1] for c in cols], dtype=object)
    flows = pd.DataFrame({"kind":kinds,"owner":kk,"m":mm,"j":jj,"g":gg,"tons":xv})
    flows = flows[flows.tons > 1e-6]
    ship = flows[flows.kind.isin(["x","y"])].copy()
    ship["mill"] = M.mill_name.values[ship.m]; ship["mill_owner"] = M.owner.values[ship.m]
    ship["node"] = N.name.values[ship.j]; ship["node_id"] = N.node_id.values[ship.j]
    ship["miles"] = dist[ship.m, ship.j]*FREIGHT["road_factor"]; ship["rail"] = by_rail[ship.m, ship.j]; ship["g"] = ship.g.astype(str)
    ship["cost"] = cost[ship.m, ship.j]*ship.tons
    exp = flows[flows.kind=="z"].copy(); exp["mill"] = M.mill_name.values[exp.m]; exp["port"] = PORTS.port.values[exp.g.astype(int)]
    exp["miles"] = pdist[exp.m, exp.g.astype(int)]*FREIGHT["road_factor"]; exp["cost"] = pcost[exp.m, exp.g.astype(int)]*exp.tons
    unmet = flows[flows.kind=="u"].tons.sum(); purchased = flows[flows.kind=="v"].tons.sum()
    util = pd.Series(0.0, index=range(nM))
    used = flows[flows.kind.isin(["x","y","z"])].groupby("m").tons.sum()
    util.loc[used.index] = used.values
    M["shipped_tons"] = util.values; M["avail_capacity"] = cap; M["utilization"] = np.where(cap>0, util.values/np.maximum(cap,1), 0)
    M["capacity_shadow_price"] = -res.ineqlin.marginals  # $/ton value of one more ton of capacity
    # delivered marginal cost at each node (open-market liner dual)
    duals = res.eqlin.marginals
    N = N.copy(); N["demand_tons"] = D
    N["marginal_delivered_cost_L"] = [duals[open_row[(j,"L")]-nM] for j in range(J)]
    N["marginal_delivered_cost_M"] = [duals[open_row[(j,"M")]-nM] for j in range(J)]
    kpi = dict(objective_usd=float(res.fun), freight_usd=float(ship.cost.sum()+exp.cost.sum()), premium_usd=float(purchased*premium), unmet_usd=float(unmet*unmet_penalty), tons_shipped_domestic=float(ship.tons.sum()), tons_exported=float(exp.tons.sum()),
               unmet_tons=float(unmet), owner_purchased_from_market_tons=float(purchased),
               avg_haul_miles=float((ship.tons*ship.miles).sum()/max(ship.tons.sum(),1)),
               rail_share=float(ship[ship.rail].tons.sum()/max(ship.tons.sum(),1)),
               avg_freight_per_ton=float(ship.cost.sum()/max(ship.tons.sum(),1)),
               n_vars=nvar, n_rows=nrow, solve_seconds=round(time.time()-t0,1))
    # integration: share of each owner's shipments that go to its own plants
    integ = {}
    for k in owners:
        own = ship[(ship.mill_owner==k)]
        integ[k] = dict(total=float(own.tons.sum()), internal=float(own[own.kind=="x"].tons.sum()),
                        market=float(own[own.kind=="y"].tons.sum()), exports=float(exp[M.owner.values[exp.m]==k].tons.sum()),
                        bought_from_market=float(flows[(flows.kind=="v")&(flows.owner==k)].tons.sum()))
    if verbose:
        print(f"LP {nvar} vars x {nrow} rows solved in {kpi['solve_seconds']}s; cost ${res.fun/1e6:,.0f}M; "
              f"avg haul {kpi['avg_haul_miles']:.0f} mi; rail share {kpi['rail_share']:.0%}; unmet {unmet:,.0f} t; owner buys {purchased:,.0f} t")
    return dict(mills=M, nodes=N, ship=ship, exports=exp, kpi=kpi, integration=integ)


def prospects(mills, nodes, availability=None, diesel=DIESEL_BASE, grade="L"):
    """For each demand point: the two cheapest active mills by delivered freight for the grade, and the gap between them."""
    M = mills.reset_index(drop=True)
    ok = (M.grades.str.contains("linerboard") if grade == "L" else M.grades.str.contains("medium")).values
    if availability is not None: ok = ok & (availability > 0)
    dist = haversine(M.lat.values[:,None], M.lon.values[:,None], nodes.lat.values[None,:], nodes.lon.values[None,:])
    cost, _ = freight_cost(dist, diesel=diesel)
    cost = np.where(ok[:,None], cost, np.inf)
    order = np.argsort(cost, axis=0)
    out = []
    for j in range(len(nodes)):
        i1, i2, i3 = order[0, j], order[1, j], order[2, j]
        out.append(dict(best=int(i1), best_cost=round(float(cost[i1, j]), 1), second=int(i2), second_cost=round(float(cost[i2, j]), 1),
                        third=int(i3), third_cost=round(float(cost[i3, j]), 1), gap=round(float(cost[i2, j] - cost[i1, j]), 1)))
    return out

# ---- the fiber loop: OCC generated where boxes are used flows back to recycled mills and export ports
OCC_PORTS = pd.DataFrame([("Los Angeles/Long Beach CA", 33.75, -118.22, 0.42), ("Seattle/Tacoma WA", 47.27, -122.42, 0.08), ("Oakland CA", 37.80, -122.28, 0.10),
                          ("New York/NJ", 40.67, -74.05, 0.12), ("Savannah GA", 32.08, -81.09, 0.06), ("Houston TX", 29.76, -95.37, 0.05),
                          ("Laredo TX (to Mexico)", 27.51, -99.51, 0.12), ("Norfolk VA", 36.85, -76.29, 0.05)], columns=["port","lat","lon","share"])
def solve_occ(mills, nodes, node_consumption_tons, recovery_rate=0.90, occ_per_ton=1.15, export_tons=6.0e6, utilization=None,
              diesel=DIESEL_BASE, verbose=True):
    """Transportation LP: county OCC supply -> recycled-grade mills (demand = recycled capacity x utilization x 1.15) + export ports."""
    M = mills.reset_index(drop=True)
    rec = M.grades.str.contains("recycled").values
    util = np.ones(len(M)) if utilization is None else utilization
    # a mill's OCC appetite: the recycled share of its grades times its shipped tons, times fiber yield loss
    rec_share = np.array([ (sum(1 for g in str(gr).split(";") if "recycled" in g) / max(1, len(str(gr).split(";")))) for gr in M.grades.values])
    appetite = M.capacity_tons_per_year.values * util * rec_share * occ_per_ton
    sinks_lat = np.concatenate([M.lat.values[appetite > 0], OCC_PORTS.lat.values]); sinks_lon = np.concatenate([M.lon.values[appetite > 0], OCC_PORTS.lon.values])
    sink_ids = [("mill", int(i)) for i in np.where(appetite > 0)[0]] + [("port", int(p)) for p in range(len(OCC_PORTS))]
    supply = node_consumption_tons * recovery_rate
    demand = np.concatenate([appetite[appetite > 0], export_tons*OCC_PORTS.share.values])
    scale = min(1.0, supply.sum()/demand.sum())           # if more appetite than fiber, mills (and ports) are rationed pro rata
    demand = demand * scale
    dist = haversine(nodes.lat.values[:,None], nodes.lon.values[:,None], sinks_lat[None,:], sinks_lon[None,:])
    cost, by_rail = freight_cost(dist, diesel=diesel)
    cost = cost * 0.9 + 6.0                                 # baled OCC: similar lanes, slightly cheaper per ton-mile, plus handling
    J, K = len(nodes), len(sink_ids)
    c = cost.flatten()
    from scipy.sparse import coo_matrix
    rows = np.repeat(np.arange(J), K); cols = np.arange(J*K)
    A_ub = coo_matrix((np.ones(J*K), (rows, cols)), shape=(J, J*K))          # each county ships at most what it recovers
    rows2 = np.tile(np.arange(K), J); A_eq = coo_matrix((np.ones(J*K), (rows2, cols)), shape=(K, J*K))
    res = linprog(c, A_ub=A_ub, b_ub=supply, A_eq=A_eq, b_eq=demand, bounds=(0, None), method="highs")
    if res.status != 0: raise RuntimeError("OCC LP: " + res.message)
    X = res.x.reshape(J, K)
    flows = [(j, k, X[j, k]) for j, k in zip(*np.where(X > 1000))]
    surplus = supply - X.sum(axis=1)                     # fiber recovered but not placed (landfill / other grades / inventory)
    duals = res.ineqlin.marginals                         # value of one more ton of OCC at each county (<= 0): the scarcity surface
    kpi = dict(occ_supply=float(supply.sum()), occ_to_mills=float(X[:, :len(sink_ids)-len(OCC_PORTS)].sum()), occ_exported=float(X[:, len(sink_ids)-len(OCC_PORTS):].sum()),
               occ_unplaced=float(surplus.sum()), appetite_scale=scale, avg_haul=float((X*dist*FREIGHT["road_factor"]).sum()/X.sum()), freight_usd=float((X*cost).sum()))
    if verbose: print("OCC loop:", {k: (round(v/1e6, 2) if v > 1e4 else round(v, 2)) for k, v in kpi.items()})
    return dict(flows=flows, sinks=sink_ids, X=X, supply=supply, demand=demand, surplus=surplus, county_value=-duals, kpi=kpi, dist=dist)
