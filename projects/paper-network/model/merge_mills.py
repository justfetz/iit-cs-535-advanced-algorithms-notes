"""Merge agent-researched mill files with the seed list into one normalized, geocoded mill table."""
import os, re, sys, pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from geocode_mills import geocode

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
OWNER_MAP = {"Packaging Corp":"Packaging Corp of America","Pratt":"Pratt Industries","Port Townsend":"Port Townsend Paper","McKinley":"McKinley Paper","Crossroads":"Crossroads Paper","Hood Container Corporation":"Hood Container","IP":"International Paper","International Paper":"International Paper","SW":"Smurfit Westrock","Smurfit Westrock":"Smurfit Westrock",
  "PCA":"Packaging Corp of America","Packaging Corporation of America":"Packaging Corp of America","Packaging Corp of America":"Packaging Corp of America",
  "Georgia-Pacific":"Georgia-Pacific","GP":"Georgia-Pacific","Pratt Industries":"Pratt Industries","Pratt":"Pratt Industries",
  "Green Bay Packaging":"Green Bay Packaging","GBP":"Green Bay Packaging","Greenpac (Cascades)":"Cascades","Greenpac":"Cascades","Cascades":"Cascades",
  "New-Indy Containerboard":"New-Indy","New-Indy":"New-Indy","ND Paper":"ND Paper","Domtar":"Domtar","Hood Container":"Hood Container",
  "Port Townsend Paper":"Port Townsend Paper","McKinley Paper (Bio Pappel)":"McKinley Paper","McKinley Paper":"McKinley Paper","Liberty Paper":"Liberty Paper",
  "Jackson Paper":"Jackson Paper","Kruger":"Kruger","Atlantic Packaging":"Atlantic Packaging","Irving Paper":"Irving","Irving":"Irving",
  "Ox Industries (ex-WestRock)":"Ox Industries","Sylvamo (ex-IP)":"Sylvamo"}

def norm_owner(o):
    o = str(o).strip()
    if o in OWNER_MAP: return OWNER_MAP[o]
    base = re.sub(r"\s*\(.*$", "", o).strip()
    for k in ["International Paper","Smurfit Westrock","Packaging Corp","Georgia-Pacific","Pratt","Green Bay Packaging","Cascades","New-Indy","ND Paper",
              "Domtar","Hood Container","Port Townsend","McKinley","Liberty Paper","Jackson Paper","Kruger","Atlantic Packaging","Irving","Crossroads","Bio Pappel","Cartones Ponderosa","Ox Industries","Sylvamo"]:
        if base.startswith(k) or k in base: return OWNER_MAP.get(k, k)
    return OWNER_MAP.get(base, base)
COUNTRY = {"USA":"US","US":"US","United States":"US","Canada":"CA","CA":"CA","Mexico":"MX","MX":"MX"}
CLOSED_YEAR_OVERRIDE = {("McKinley Paper","Port Angeles"): 2024, ("International Paper","Orange"): 2023}   # idled Aug 2024, sold 2026: out of the 2024 footprint
CAP_2024 = {("International Paper","Selma"): 450000, ("Packaging Corp of America","Wallula"): 450000}  # before PM16 conversion / before W2 shutdown
OWNER_2024 = {("Packaging Corp of America","Gladstone"): "Greif", ("Packaging Corp of America","Massillon"): "Greif", ("International Paper","Longview"): "NORPAC"}

def load(path, default_conf):
    if not os.path.exists(path): return pd.DataFrame()
    d = pd.read_csv(path)
    d["owner"] = d.owner.map(norm_owner)
    d["country"] = d.country.map(lambda c: COUNTRY.get(str(c).strip(), str(c).strip()))
    d["grades"] = d.grades.fillna("").str.replace("|",";").str.replace(" ","")
    for c in ["status_note","capacity_basis","source_url","confidence","city","state","country","mill_name"]:
        if c not in d: d[c] = ""
        d[c] = d[c].fillna("").astype(str)
    d["confidence"] = d.confidence.replace("", default_conf)
    d["capacity_tons_per_year"] = pd.to_numeric(d.capacity_tons_per_year, errors="coerce").fillna(0).astype(int)
    return d

def norm_key(r):
    city = re.sub(r"\s*\(.*\)", "", str(r.city)).strip().lower()
    return (r.owner, city, str(r.state).strip())

def closed_year(note, status):
    if status != "closed": return np.nan
    m = re.findall(r"(20\d\d)", str(note))
    return float(m[-1]) if m else np.nan

def main(out_csv):
    ipsw = load(os.path.join(DATA, "mills_ip_sw.csv"), "medium")
    others = load(os.path.join(DATA, "mills_others.csv"), "medium")
    seed = load(os.path.join(DATA, "mills_seed.csv"), "seed")
    seed["source_url"] = ""; seed["capacity_basis"] = "seed estimate from prior knowledge"
    researched = pd.concat([ipsw, others], ignore_index=True)
    researched = researched[~researched.grades.str.contains("not_containerboard")]
    researched = researched[researched.capacity_tons_per_year > 0]
    have = set(norm_key(r) for r in researched.itertuples())
    have_owner = set(researched.owner)
    # seed rows fill gaps only for owners the research did not cover at all, or mills missing for covered owners (flagged)
    fill = seed[[norm_key(r) not in have for r in seed.itertuples()]].copy()
    fill = fill[~fill.owner.isin(have_owner)]  # research files are authoritative for every owner they cover
    fill = fill[~fill.mill_name.str.contains("Orange (Smurfit", regex=False)]
    allm = pd.concat([researched, fill], ignore_index=True)
    allm["closed_year"] = [closed_year(n, s) for n, s in zip(allm.status_note, allm.status_oct2026)]
    allm = allm[~allm.owner.isin(["Crossroads Paper","Bio Pappel"])]  # proposed greenfield / unresearched aggregate
    # NORPAC: keep the containerboard-only figure (others file), drop the all-grades row from the IP file
    dup = allm[(allm.owner=="International Paper") & (allm.city.str.startswith("Longview"))]
    if len(dup) > 1: allm = allm.drop(dup.capacity_tons_per_year.idxmax())
    allm["city_clean"] = allm.city.str.replace(r"\s*\(.*\)", "", regex=True).str.strip().str.replace("St. George","Saint George")
    geo = [geocode(c, s, k) for c, s, k in zip(allm.city_clean, allm.state, allm.country)]
    allm["lat"], allm["lon"], allm["geo_source"] = zip(*geo)
    allm["mill_name"] = allm.mill_name.str.replace(r"\s+Mill\b", "", regex=True).str.replace(r"\s*\((ex-|WestRock)[^)]*\)", "", regex=True).str.strip()
    for (o, c), y in CLOSED_YEAR_OVERRIDE.items(): allm.loc[(allm.owner==o) & (allm.city_clean==c), "closed_year"] = y
    allm["capacity_2024"] = allm.capacity_tons_per_year
    for (o, c), v in CAP_2024.items(): allm.loc[(allm.owner==o) & (allm.city_clean==c), "capacity_2024"] = v
    allm["owner_2024"] = allm.owner
    for (o, c), v in OWNER_2024.items(): allm.loc[(allm.owner==o) & (allm.city_clean==c), "owner_2024"] = v
    allm["in_model"] = allm.country.isin(["US","CA"]) & allm.lat.notna()
    cols = ["owner","owner_2024","mill_name","city","state","country","grades","capacity_tons_per_year","capacity_2024","status_oct2026","closed_year","status_note","capacity_basis","source_url","confidence","lat","lon","geo_source","in_model"]
    allm = allm[cols].sort_values(["owner","state","mill_name"]).reset_index(drop=True)
    allm.to_csv(out_csv, index=False)
    us_open = allm[(allm.country=="US") & (allm.status_oct2026=="open")]
    print(f"{len(allm)} mills; US open {len(us_open)} = {us_open.capacity_tons_per_year.sum()/1e6:.2f} Mt; missing geo: {allm[allm.lat.isna()][['mill_name','city','state']].to_dict('records')}")
    print(us_open.groupby("owner").capacity_tons_per_year.sum().sort_values(ascending=False).div(1e6).round(2).to_dict())
    print("seed-filled rows:", int((allm.confidence=="seed").sum()), "| closed since 2022 US:", allm[(allm.country=='US')&(allm.status_oct2026=='closed')&(allm.closed_year>=2022)].capacity_tons_per_year.sum()/1e6)
    return allm

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(DATA, "mills_final.csv"))
