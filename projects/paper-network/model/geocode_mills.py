"""Offline geocoder for mill towns: zipcodes DB (PyPI) + geonamescache + manual overrides."""
import sys, pandas as pd, zipcodes, geonamescache

MANUAL = {  # (city, state) -> (lat, lon)  for towns not in the US zip DB (Canada, odd spellings)
    ("La Tuque","QC"): (47.4389,-72.7822), ("Temiscouata-sur-le-Lac","QC"): (47.6820,-68.8770),
    ("Trois-Rivieres","QC"): (46.3432,-72.5477), ("Whitby","ON"): (43.8975,-78.9429),
    ("Saint George","NB"): (45.1298,-66.8257), ("Kingsey Falls","QC"): (45.8537,-72.0656),
    ("Trenton","ON"): (44.1023,-77.5747), ("Cabano","QC"): (47.6820,-68.8770),
    ("DeRidder","LA"): (30.8463,-93.2890), ("De Ridder","LA"): (30.8463,-93.2890),
    ("Filer City","MI"): (44.2153,-86.2873), ("Big Island","VA"): (37.5329,-79.3639),
    ("Cantonment","FL"): (30.6085,-87.3397), ("Biron","WI"): (44.4319,-89.7893),
    ("Monterrey","Nuevo Leon"): (25.6866,-100.3161), ("Ecatepec de Morelos","Estado de Mexico"): (19.60,-99.05),
    ("Tlalnepantla","Estado de Mexico"): (19.54,-99.19), ("San Luis Potosi","San Luis Potosi"): (22.15,-100.98), ("San Juan del Rio","QRO"): (20.39,-99.99),
    ("Scarborough","ON"): (43.77,-79.26), ("Solvay","NY"): (43.0581,-76.2077), ("Gladstone","VA"): (37.5468,-78.8639), ("Mississauga","ON"): (43.59,-79.64), ("Montreal","QC"): (45.47,-73.58), ("Saint George","NB"): (45.1298,-66.8257),
}
gc = geonamescache.GeonamesCache()
GN = {}
for v in gc.get_cities().values():
    if v["countrycode"] in ("US","CA","MX"):
        GN.setdefault((v["name"].lower(), v.get("admin1code","")), (v["latitude"], v["longitude"]))

def geocode(city, state, country="US"):
    key = (city, state)
    if key in MANUAL: return MANUAL[key] + ("manual",)
    if country == "US":
        for c in (city, city.replace("St.", "Saint"), city.replace("Saint", "St."), city.replace("Mc","Mc ")):
            r = zipcodes.filter_by(city=c, state=state)
            r = [z for z in r if z.get("zip_code_type","STANDARD")=="STANDARD" and z.get("lat")] or r
            if r:
                lat = sum(float(z["lat"]) for z in r)/len(r); lon = sum(float(z["long"]) for z in r)/len(r)
                return (round(lat,4), round(lon,4), f"zipcodes:{len(r)}")
    g = GN.get((city.lower(), state))
    if g: return (g[0], g[1], "geonames")
    return (None, None, "MISSING")

if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    d = pd.read_csv(src)
    out = [geocode(str(r.city).strip(), str(r.state).strip(), str(r.country).strip()) for r in d.itertuples()]
    d["lat"], d["lon"], d["geo_source"] = zip(*out)
    d.to_csv(dst, index=False)
    miss = d[d.lat.isna()]
    print(f"{len(d)} mills geocoded, {len(miss)} missing:", miss[["owner","mill_name","city","state"]].to_dict("records"))
