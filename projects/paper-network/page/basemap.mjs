import fs from "node:fs";
import * as topojson from "topojson-client";
import { geoPath } from "d3-geo";
const st = JSON.parse(fs.readFileSync("node_modules/us-atlas/states-albers-10m.json","utf8"));
const na = JSON.parse(fs.readFileSync("node_modules/us-atlas/nation-albers-10m.json","utf8"));
const path = geoPath(null).digits(1);
const states = topojson.feature(st, st.objects.states).features
  .filter(f => !["02","15","72","78","60","66","69"].includes(f.id))   // drop AK, HI, territories (no mills, keeps the frame tight)
  .map(f => ({ id: f.id, name: f.properties.name, d: path(f) }));
const mesh = path(topojson.mesh(st, st.objects.states, (a, b) => a !== b && !["02","15","72"].includes(a.id) && !["02","15","72"].includes(b.id)));
const nation = topojson.feature(na, na.objects.nation).features[0];
// nation outline includes AK/HI polygons; keep only the largest (lower 48) ring set by area
const polys = nation.geometry.coordinates.map(c => ({ type: "Polygon", coordinates: c }));
const areas = polys.map(p => Math.abs(path.area(p)));
const main = polys[areas.indexOf(Math.max(...areas))];
const out = { states, mesh, nation: path(main) };
fs.writeFileSync("basemap.json", JSON.stringify(out));
console.log("states", states.length, "bytes", fs.statSync("basemap.json").size);
