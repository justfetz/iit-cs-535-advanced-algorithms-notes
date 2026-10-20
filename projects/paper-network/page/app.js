/* The Paper Network: mills -> box-plant demand, one min-cost flow per scenario. Needs window.PN_DATA and window.PN_BASEMAP, d3 v7. */
(function () {
  var D = window.PN_DATA, BM = window.PN_BASEMAP;
  var fmtT = d3.format(",.0f"), fmtP = d3.format(".0%"), fmt1 = d3.format(".1f");
  var kt = function (v) { return v >= 950000 ? (v / 1e6).toFixed(2) + " Mt" : Math.round(v / 1e3) + " kt"; };
  var musd = function (v) { return "$" + (v / 1e6).toFixed(0) + "M"; };
  var css = function (n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); };
  var proj = d3.geoConicEqualArea().parallels([29.5, 45.5]).rotate([96, 0]).center([-0.6, 38.7]).scale(1300).translate([487.5, 305]);
  D.mills.forEach(function (m) { var p = proj([m.lon, m.lat]); m.x = p[0]; m.y = p[1]; });
  D.nodes.forEach(function (n, i) { var p = proj([n.lon, n.lat]); n.x = p[0]; n.y = p[1]; n.i = i; });
  D.ports.forEach(function (p) { var q = proj([p.lon, p.lat]); p.x = q[0]; p.y = q[1]; });
  var OWNERS = D.owner_order;
  var byId = {}; D.mills.forEach(function (m) { byId[m.id] = m; });
  function ownerVar(o) { var i = OWNERS.indexOf(o); return i >= 0 && i < 8 ? "var(--s" + (i + 1) + ")" : "var(--other)"; }
  function ownerHex(o) { var i = OWNERS.indexOf(o); return i >= 0 && i < 8 ? css("--s" + (i + 1)) : css("--other"); }
  var GRADE = { kraft_linerboard: "kraft liner", recycled_linerboard: "recycled liner", white_top_linerboard: "white-top liner", semichem_medium: "semichem medium", recycled_medium: "recycled medium" };
  function grades(g) { return String(g || "").split(/[;|]/).filter(Boolean).map(function (x) { return GRADE[x] || x; }).join(", "); }

  /* ---------- scenario access ---------- */
  var state = { scen: "fp2026", flows: true, market: true, exports: false, demand: true, millColor: "owner", nodeColor: "none", isolate: null };
  function scen() { return D.scenarios[state.scen]; }
  function arcsOf(key) {
    var s = D.scenarios[key];
    if (!s.delta_of) return s.arcs;
    var map = new Map(D.scenarios[s.delta_of].arcs.map(function (a) { return [a[0] + "|" + a[1] + "|" + a[3], a]; }));
    s.arcs.forEach(function (a) { var k = a[0] + "|" + a[1] + "|" + a[3]; if (a[2] === 0) map.delete(k); else map.set(k, a); });
    return Array.from(map.values());
  }
  function ownerIn(m) { return state.scen === "fp2024" ? m.owner_2024 : m.owner; }
  function capIn(m) { return state.scen === "fp2024" ? m.cap_2024 : m.cap; }
  var cache = {};
  function derived(key) {
    if (cache[key]) return cache[key];
    var s = D.scenarios[key], arcs = arcsOf(key), byMill = {}, byNode = {};
    arcs.forEach(function (a) { (byMill[a[0]] = byMill[a[0]] || []).push(a); (byNode[a[1]] = byNode[a[1]] || []).push(a); });
    var byPort = {}; s.exports.forEach(function (e) { (byPort[e[1]] = byPort[e[1]] || []).push(e); });
    var active = {}; s.active.forEach(function (g) { active[g] = true; });
    return (cache[key] = { arcs: arcs, byMill: byMill, byNode: byNode, byPort: byPort, active: active });
  }

  /* ---------- map ---------- */
  var W = 975, H = 610;
  var root = d3.select("#map");
  var svg = root.append("svg").attr("viewBox", "0 0 " + W + " " + H).attr("role", "img").attr("aria-label", "Map of US containerboard mills, box-plant demand and modeled flows");
  var gBase = svg.append("g").attr("class", "base"), gArcs = svg.append("g").attr("class", "arcs"), gExp = svg.append("g").attr("class", "exp"),
      gNodes = svg.append("g").attr("class", "nodes"), gPorts = svg.append("g").attr("class", "ports"), gMills = svg.append("g").attr("class", "mills"), gLab = svg.append("g").attr("class", "labels");
  gBase.append("path").attr("d", BM.nation).attr("class", "nation");
  gBase.append("path").attr("d", BM.mesh).attr("class", "mesh");
  var tip = root.append("div").attr("class", "tip").style("display", "none");
  function showTip(ev, html) {
    var r = root.node().getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
    tip.html(html).style("display", "block");
    var tw = tip.node().offsetWidth, th = tip.node().offsetHeight;
    tip.style("left", Math.max(4, Math.min(r.width - tw - 4, x + 14)) + "px").style("top", (y - th - 12 < 4 ? y + 16 : y - th - 12) + "px");
  }
  function hideTip() { tip.style("display", "none"); }
  function arcPath(a, b) {
    var dx = b.x - a.x, dy = b.y - a.y, k = 0.16;
    return "M" + a.x + "," + a.y + "Q" + ((a.x + b.x) / 2 - dy * k) + "," + ((a.y + b.y) / 2 + dx * k) + " " + b.x + "," + b.y;
  }
  var rMill = function (cap) { return Math.max(2.4, Math.sqrt(cap / 1e6) * 9); };
  var sNode = function (t) { return Math.max(1.6, Math.sqrt(t / 1e6) * 7); };
  var wArc = function (t) { return Math.max(0.35, Math.sqrt(t / 1e6) * 6); };

  function renderMap() {
    var s = scen(), dv = derived(state.scen), iso = state.isolate;
    var seqLo = css("--seq-lo"), seqHi = css("--seq-hi");
    var shadowScale = d3.scaleSequential(d3.interpolateLab(seqLo, seqHi)).domain([0, d3.quantile(s.shadow.filter(function (v) { return v > 0; }).sort(d3.ascending), 0.95) || 1]);
    var mcScale = d3.scaleSequential(d3.interpolateLab(seqLo, seqHi)).domain([d3.min(s.node_mc), d3.quantile(s.node_mc.slice().sort(d3.ascending), 0.95)]);
    var visibleArcs = (state.flows ? dv.arcs : []).filter(function (a) { return (a[3] === 1 || state.market) && (!iso || ownerIn(byId[a[0]]) === iso); });
    visibleArcs.sort(function (a, b) { return b[2] - a[2]; });
    var arcSel = gArcs.selectAll("path").data(visibleArcs, function (a) { return a[0] + "|" + a[1] + "|" + a[3]; });
    arcSel.exit().remove();
    arcSel.enter().append("path").merge(arcSel)
      .attr("d", function (a) { return arcPath(byId[a[0]], D.nodes[a[1]]); })
      .attr("class", function (a) { return a[3] ? "arc own" : "arc mkt"; })
      .style("stroke", function (a) { return a[3] ? ownerVar(ownerIn(byId[a[0]])) : null; })
      .style("stroke-width", function (a) { return wArc(a[2]); });
    // exports
    var ex = state.exports ? s.exports.filter(function (e) { return !iso || ownerIn(byId[e[0]]) === iso; }) : [];
    var exSel = gExp.selectAll("path").data(ex, function (e) { return e[0] + "|" + e[1]; });
    exSel.exit().remove();
    exSel.enter().append("path").merge(exSel).attr("class", "arc exp").attr("d", function (e) { return arcPath(byId[e[0]], D.ports[e[1]]); })
      .style("stroke", function (e) { return ownerVar(ownerIn(byId[e[0]])); }).style("stroke-width", function (e) { return wArc(e[2]); });
    var portSel = gPorts.selectAll("path").data(state.exports ? D.ports : [], function (p) { return p.name; });
    portSel.exit().remove();
    portSel.enter().append("path").attr("class", "port").merge(portSel)
      .attr("d", function (p) { var t = (dv.byPort[D.ports.indexOf(p)] || []).reduce(function (a, e) { return a + e[2]; }, 0), r = Math.max(3, Math.sqrt(t / 1e6) * 9); return "M" + p.x + "," + (p.y - r) + "L" + (p.x + r) + "," + (p.y + r) + "L" + (p.x - r) + "," + (p.y + r) + "Z"; })
      .on("mousemove", function (ev, p) { var i = D.ports.indexOf(p), list = (dv.byPort[i] || []).slice().sort(function (a, b) { return b[2] - a[2]; }), t = list.reduce(function (a, e) { return a + e[2]; }, 0);
        showTip(ev, "<b>" + p.name + "</b><br>export gateway · " + fmtP(p.share) + " of US export tons<br>" + kt(t) + " through here<br>" + list.slice(0, 3).map(function (e) { return byId[e[0]].name + " " + kt(e[2]); }).join("<br>")); })
      .on("mouseleave", hideTip);
    // demand nodes
    var nodeSel = gNodes.selectAll("rect").data(state.demand ? D.nodes : [], function (n) { return n.id; });
    nodeSel.exit().remove();
    nodeSel.enter().append("rect").attr("class", "node").merge(nodeSel)
      .attr("x", function (n) { return n.x - sNode(s.node_demand[n.i]) / 2; }).attr("y", function (n) { return n.y - sNode(s.node_demand[n.i]) / 2; })
      .attr("width", function (n) { return sNode(s.node_demand[n.i]); }).attr("height", function (n) { return sNode(s.node_demand[n.i]); })
      .style("fill", function (n) { return state.nodeColor === "mc" ? mcScale(s.node_mc[n.i]) : null; })
      .classed("mc", state.nodeColor === "mc")
      .on("mousemove", function (ev, n) { var list = (dv.byNode[n.i] || []).slice().sort(function (a, b) { return b[2] - a[2]; });
        showTip(ev, "<b>" + n.name + "</b><br>" + fmtT(n.pop) + " people in the catchment<br>" + kt(s.node_demand[n.i]) + " of board a year · delivered marginal cost $" + Math.round(s.node_mc[n.i]) + "/t<br>" +
          list.slice(0, 4).map(function (a) { var m = byId[a[0]]; return m.name + ", " + m.st + " (" + ownerIn(m) + (a[3] ? ", own" : ", market") + ") " + kt(a[2]); }).join("<br>")); })
      .on("mouseleave", hideTip);
    // mills: active ones solid, closed/knocked-out hollow
    var mills = D.mills.filter(function (m) { return m.country !== "MX" && (dv.active[m.id] || m.status === "closed" || (s.kind === "knockout" && s.mill === m.id)); });
    var millSel = gMills.selectAll("circle").data(mills, function (m) { return m.id; });
    millSel.exit().remove();
    millSel.enter().append("circle").attr("class", "mill").merge(millSel)
      .attr("cx", function (m) { return m.x; }).attr("cy", function (m) { return m.y; })
      .attr("r", function (m) { return rMill(capIn(m)); })
      .classed("off", function (m) { return !dv.active[m.id] || (s.kind === "knockout" && s.mill === m.id); })
      .classed("dim", function (m) { return iso && ownerIn(m) !== iso; })
      .style("fill", function (m) { if (!dv.active[m.id] || (s.kind === "knockout" && s.mill === m.id)) return "none"; return state.millColor === "shadow" ? shadowScale(s.shadow[m.id]) : ownerVar(ownerIn(m)); })
      .style("stroke", function (m) { return (!dv.active[m.id] || (s.kind === "knockout" && s.mill === m.id)) ? "var(--ink-3)" : (state.millColor === "shadow" ? "var(--bg)" : ownerVar(ownerIn(m))); })
      .on("mousemove", function (ev, m) {
        var dests = (dv.byMill[m.id] || []).slice().sort(function (a, b) { return b[2] - a[2]; });
        var exp = s.exports.filter(function (e) { return e[0] === m.id; }).reduce(function (a, e) { return a + e[2]; }, 0);
        var off = !dv.active[m.id] || (s.kind === "knockout" && s.mill === m.id);
        var line1 = off ? (m.status === "closed" ? "closed " + (m.closed_year || "") : "knocked out in this scenario") : "shipping " + kt(s.shipped[m.id]) + " of " + kt(capIn(m)) + " (" + fmtP(s.util[m.id]) + " loaded)";
        showTip(ev, "<b>" + m.name + ", " + m.st + "</b> · " + ownerIn(m) + "<br>" + grades(m.grades) + " · " + kt(capIn(m)) + "/yr<br>" + line1 +
          (off ? "" : "<br>marginal value of one more ton: $" + Math.round(s.shadow[m.id]) + "/t" + (exp ? "<br>exports " + kt(exp) : "")) +
          (dests.length ? "<br>" + dests.slice(0, 3).map(function (a) { return "→ " + D.nodes[a[1]].name + " " + kt(a[2]); }).join("<br>") : "") + (m.note ? "<br><i>" + m.note + "</i>" : ""));
        gArcs.selectAll("path").classed("hl", function (a) { return a[0] === m.id; }).classed("fade", function (a) { return a[0] !== m.id; });
      })
      .on("mouseleave", function () { hideTip(); gArcs.selectAll("path").classed("hl", false).classed("fade", false); });
    var labs = mills.filter(function (m) { return capIn(m) >= 850000 && dv.active[m.id]; });
    var labSel = gLab.selectAll("text").data(labs, function (m) { return m.id; });
    labSel.exit().remove();
    labSel.enter().append("text").merge(labSel).attr("x", function (m) { return m.x + rMill(capIn(m)) + 2; }).attr("y", function (m) { return m.y + 3; }).text(function (m) { return m.name; });
    renderStats();
  }

  /* ---------- stats strip + legend ---------- */
  function renderStats() {
    var s = scen(), k = s.kpi, b = D.scenarios.fp2026.kpi, el = d3.select("#stats");
    var delta = function (v, bv, f, unit) { if (state.scen === "fp2026" || state.scen === "fp2024") return ""; var d = v - bv; return " <span class='d'>(" + (d >= 0 ? "+" : "−") + f(Math.abs(d)) + unit + ")</span>"; };
    var items = [
      ["scenario", s.label],
      ["board shipped", kt(k.tons_shipped_domestic) + delta(k.tons_shipped_domestic, b.tons_shipped_domestic, kt, "")],
      ["exported", kt(k.tons_exported)],
      ["average haul", Math.round(k.avg_haul_miles) + " mi" + delta(k.avg_haul_miles, b.avg_haul_miles, function (v) { return Math.round(v); }, " mi")],
      ["by rail", fmtP(k.rail_share)],
      ["freight", "$" + fmt1(k.avg_freight_per_ton) + "/t · " + musd(k.freight_usd) + delta(k.freight_usd, b.freight_usd, musd, "")],
      ["bought outside own system", kt(k.owner_purchased_from_market_tons)],
      ["unmet", k.unmet_tons > 0 ? kt(k.unmet_tons) : "none"]
    ];
    var sel = el.selectAll("div.st").data(items);
    sel.exit().remove();
    sel.enter().append("div").attr("class", "st").merge(sel).html(function (d) { return "<span>" + d[0] + "</span><b>" + d[1] + "</b>"; });
  }
  function renderLegend() {
    var caps = {}; D.mills.forEach(function (m) { if (m.country !== "MX" && m.status === "open") caps[m.owner] = (caps[m.owner] || 0) + m.cap; });
    var rows = OWNERS.slice(0, 8).map(function (o) { return { o: o, cap: caps[o] || 0 }; });
    var other = OWNERS.slice(8).reduce(function (a, o) { return a + (caps[o] || 0); }, 0);
    rows.push({ o: "Other", cap: other });
    var sel = d3.select("#legend").selectAll("button").data(rows);
    sel.enter().append("button").attr("type", "button").merge(sel)
      .attr("aria-pressed", function (d) { return state.isolate === d.o ? "true" : "false"; })
      .html(function (d) { return "<i style='background:" + (d.o === "Other" ? "var(--other)" : ownerVar(d.o)) + "'></i>" + d.o + " <span>" + kt(d.cap) + "</span>"; })
      .on("click", function (ev, d) { state.isolate = state.isolate === d.o ? null : (d.o === "Other" ? null : d.o); renderLegend(); renderMap(); });
  }

  /* ---------- controls ---------- */
  function setScen(key) { state.scen = key; d3.selectAll("#scen button").attr("aria-pressed", function () { return this.dataset.scen === key ? "true" : "false"; }); renderMap(); }
  d3.selectAll("#scen button").on("click", function () { d3.select("#month").property("value", ""); d3.select("#ko").property("value", ""); setScen(this.dataset.scen); });
  var monthSel = d3.select("#month");
  monthSel.selectAll("option.m").data(d3.range(1, 13)).enter().append("option").attr("class", "m").attr("value", function (m) { return "m" + (m < 10 ? "0" + m : m); })
    .text(function (m) { var s = D.scenarios["m" + (m < 10 ? "0" + m : m)]; return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1] + " · " + s.mills_down.length + " mills in outage · " + kt(s.tons_offline) + " offline"; });
  monthSel.on("change", function () { if (this.value) { d3.select("#ko").property("value", ""); d3.selectAll("#scen button").attr("aria-pressed", "false"); state.scen = this.value; renderMap(); } });
  var koSel = d3.select("#ko");
  koSel.selectAll("option.k").data(D.knockouts.slice().sort(function (a, b) { return b.d_freight - a.d_freight; })).enter().append("option").attr("class", "k").attr("value", function (k) { return "ko" + k.mill; })
    .text(function (k) { return k.name + ", " + k.st + " (" + k.owner + ") · +" + musd(k.d_freight) + "/yr freight" + (k.unmet > 0 ? " · " + kt(k.unmet) + " unmet" : ""); });
  koSel.on("change", function () { if (this.value) { d3.select("#month").property("value", ""); d3.selectAll("#scen button").attr("aria-pressed", "false"); state.scen = this.value; renderMap(); } });
  d3.selectAll("#layers button").on("click", function () {
    var k = this.dataset.layer;
    if (k === "flows" || k === "market" || k === "exports" || k === "demand") state[k] = !state[k];
    if (k === "shadow") state.millColor = state.millColor === "shadow" ? "owner" : "shadow";
    if (k === "mc") state.nodeColor = state.nodeColor === "mc" ? "none" : "mc";
    d3.selectAll("#layers button").attr("aria-pressed", function () { var q = this.dataset.layer; return (q === "shadow" ? state.millColor === "shadow" : q === "mc" ? state.nodeColor === "mc" : state[q]) ? "true" : "false"; });
    renderMap();
  });

  /* ---------- charts ---------- */
  function chartFrame(id, w, h, m) { var s = d3.select(id).append("svg").attr("viewBox", "0 0 " + w + " " + h); return s.append("g").attr("transform", "translate(" + m.l + "," + m.t + ")"); }
  function drawHaul() {
    var rows = D.scenarios.fp2026.haul, w = 680, h = 230, m = { l: 44, r: 12, t: 12, b: 34 }, iw = w - m.l - m.r, ih = h - m.t - m.b;
    var g = chartFrame("#haul", w, h, m);
    var x = d3.scaleBand().domain(rows.map(function (r) { return r[0]; })).range([0, iw]).padding(0.28);
    var y = d3.scaleLinear().domain([0, d3.max(rows, function (r) { return r[1] + r[2]; }) * 1.08]).nice().range([ih, 0]);
    g.append("g").attr("class", "grid").call(d3.axisLeft(y).ticks(4).tickSize(-iw).tickFormat(function (v) { return (v / 1e6).toFixed(0) + " Mt"; }));
    g.append("g").attr("class", "axis").attr("transform", "translate(0," + ih + ")").call(d3.axisBottom(x).tickSize(0));
    g.append("text").attr("class", "axlab").attr("x", iw / 2).attr("y", ih + 30).attr("text-anchor", "middle").text("road miles, mill to box plant");
    var bars = g.selectAll("g.b").data(rows).enter().append("g").attr("class", "b");
    bars.append("rect").attr("class", "truck").attr("x", function (r) { return x(r[0]); }).attr("width", x.bandwidth()).attr("y", function (r) { return y(r[1]); }).attr("height", function (r) { return ih - y(r[1]); }).attr("rx", 2);
    bars.append("rect").attr("class", "rail").attr("x", function (r) { return x(r[0]); }).attr("width", x.bandwidth()).attr("y", function (r) { return y(r[1] + r[2]) ; }).attr("height", function (r) { return Math.max(0, y(r[1]) - y(r[1] + r[2]) - 2); }).attr("rx", 2);
    bars.append("text").attr("class", "val").attr("x", function (r) { return x(r[0]) + x.bandwidth() / 2; }).attr("y", function (r) { return y(r[1] + r[2]) - 5; }).attr("text-anchor", "middle").text(function (r) { return ((r[1] + r[2]) / 1e6).toFixed(1); });
    bars.on("mousemove", function (ev, r) { showTipAt("#haul", ev, "<b>" + r[0] + " miles</b><br>truck " + kt(r[1]) + "<br>rail " + kt(r[2])); }).on("mouseleave", function () { d3.select("#haul .tip").style("display", "none"); });
  }
  function showTipAt(id, ev, html) {
    var box = d3.select(id); var t = box.select(".tip"); if (t.empty()) t = box.append("div").attr("class", "tip");
    var r = box.node().getBoundingClientRect(); t.html(html).style("display", "block").style("left", Math.min(r.width - 180, ev.clientX - r.left + 12) + "px").style("top", (ev.clientY - r.top - 40) + "px");
  }
  function drawMonths() {
    var months = d3.range(1, 13).map(function (m) { var k = "m" + (m < 10 ? "0" + m : m), s = D.scenarios[k]; return { m: m, k: k, off: s.tons_offline, down: s.mills_down.length, dfr: s.kpi.freight_usd - D.scenarios.fp2026.kpi.freight_usd, unmet: s.kpi.unmet_tons, season: s.season }; });
    var w = 680, h = 190, m = { l: 48, r: 12, t: 14, b: 26 }, iw = w - m.l - m.r, ih = h - m.t - m.b, names = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
    var x = d3.scaleBand().domain(months.map(function (d) { return d.m; })).range([0, iw]).padding(0.3);
    var g1 = chartFrame("#months-off", w, h, m);
    var y1 = d3.scaleLinear().domain([0, d3.max(months, function (d) { return d.off; }) * 1.15]).nice().range([ih, 0]);
    g1.append("g").attr("class", "grid").call(d3.axisLeft(y1).ticks(4).tickSize(-iw).tickFormat(function (v) { return (v / 1e3).toFixed(0) + " kt"; }));
    g1.append("g").attr("class", "axis").attr("transform", "translate(0," + ih + ")").call(d3.axisBottom(x).tickSize(0).tickFormat(function (d) { return names[d - 1]; }));
    g1.selectAll("rect").data(months).enter().append("rect").attr("class", "off").attr("x", function (d) { return x(d.m); }).attr("width", x.bandwidth()).attr("y", function (d) { return y1(d.off); }).attr("height", function (d) { return ih - y1(d.off); }).attr("rx", 2)
      .on("mousemove", function (ev, d) { showTipAt("#months-off", ev, "<b>month " + d.m + "</b><br>" + d.down + " mills in planned outage<br>" + kt(d.off) + " of capacity offline that month<br>demand index " + d.season.toFixed(2)); }).on("mouseleave", function () { d3.select("#months-off .tip").style("display", "none"); });
    g1.selectAll("text.val").data(months).enter().append("text").attr("class", "val").attr("x", function (d) { return x(d.m) + x.bandwidth() / 2; }).attr("y", function (d) { return y1(d.off) - 4; }).attr("text-anchor", "middle").text(function (d) { return d.down; });
    var g2 = chartFrame("#months-cost", w, h, m);
    var ext = d3.extent(months, function (d) { return d.dfr; }); var y2 = d3.scaleLinear().domain([Math.min(0, ext[0]) * 1.15, Math.max(0, ext[1]) * 1.15]).nice().range([ih, 0]);
    g2.append("g").attr("class", "grid").call(d3.axisLeft(y2).ticks(4).tickSize(-iw).tickFormat(function (v) { return (v >= 0 ? "+" : "−") + "$" + Math.abs(v / 1e6).toFixed(0) + "M"; }));
    g2.append("g").attr("class", "axis").attr("transform", "translate(0," + ih + ")").call(d3.axisBottom(x).tickSize(0).tickFormat(function (d) { return names[d - 1]; }));
    g2.append("line").attr("class", "zero").attr("x1", 0).attr("x2", iw).attr("y1", y2(0)).attr("y2", y2(0));
    g2.selectAll("rect").data(months).enter().append("rect").attr("class", function (d) { return d.dfr >= 0 ? "cost" : "cost neg"; }).attr("x", function (d) { return x(d.m); }).attr("width", x.bandwidth())
      .attr("y", function (d) { return Math.min(y2(0), y2(d.dfr)); }).attr("height", function (d) { return Math.abs(y2(d.dfr) - y2(0)); }).attr("rx", 2)
      .on("mousemove", function (ev, d) { showTipAt("#months-cost", ev, "<b>month " + d.m + "</b><br>freight vs the annual-average solution: " + (d.dfr >= 0 ? "+" : "−") + musd(Math.abs(d.dfr)) + (d.unmet > 0 ? "<br>unmet demand " + kt(d.unmet) : "")); }).on("mouseleave", function () { d3.select("#months-cost .tip").style("display", "none"); });
  }
  function drawKnockouts() {
    var rows = D.knockouts.slice().sort(function (a, b) { return b.d_freight - a.d_freight; });
    var w = 680, rowH = 22, m = { l: 190, r: 70, t: 8, b: 26 }, h = m.t + m.b + rows.length * rowH, iw = w - m.l - m.r;
    var g = chartFrame("#ko-chart", w, h, m);
    var x = d3.scaleLinear().domain([0, d3.max(rows, function (r) { return r.d_freight; }) * 1.05]).nice().range([0, iw]);
    var y = d3.scaleBand().domain(rows.map(function (r) { return r.mill; })).range([0, rows.length * rowH]).padding(0.25);
    g.append("g").attr("class", "grid").attr("transform", "translate(0," + rows.length * rowH + ")").call(d3.axisBottom(x).ticks(5).tickSize(-rows.length * rowH).tickFormat(function (v) { return "+$" + (v / 1e6).toFixed(0) + "M"; }));
    var r = g.selectAll("g.r").data(rows).enter().append("g").attr("class", "r").attr("transform", function (d) { return "translate(0," + y(d.mill) + ")"; });
    r.append("rect").attr("x", 0).attr("width", function (d) { return x(d.d_freight); }).attr("height", y.bandwidth()).attr("rx", 2).style("fill", function (d) { return ownerVar(d.owner); });
    r.append("text").attr("class", "lab").attr("x", -8).attr("y", y.bandwidth() / 2 + 4).attr("text-anchor", "end").text(function (d) { return d.name + ", " + d.st; });
    r.append("text").attr("class", "val").attr("x", function (d) { return x(d.d_freight) + 5; }).attr("y", y.bandwidth() / 2 + 4).text(function (d) { return kt(d.cap) + (d.unmet > 0 ? " · " + kt(d.unmet) + " unmet" : ""); });
    r.on("mousemove", function (ev, d) { showTipAt("#ko-chart", ev, "<b>" + d.name + ", " + d.st + "</b> (" + d.owner + ", " + kt(d.cap) + ")<br>extra freight if it vanished: +" + musd(d.d_freight) + "/yr<br>average haul " + (d.d_haul >= 0 ? "+" : "") + d.d_haul + " mi · owner buys " + kt(d.owner_buys) + " outside" + (d.unmet > 0 ? "<br>" + kt(d.unmet) + " of demand cannot be served" : "")); })
     .on("mouseleave", function () { d3.select("#ko-chart .tip").style("display", "none"); })
     .on("click", function (ev, d) { d3.select("#ko").property("value", "ko" + d.mill); d3.select("#month").property("value", ""); d3.selectAll("#scen button").attr("aria-pressed", "false"); state.scen = "ko" + d.mill; renderMap(); document.getElementById("map").scrollIntoView({ behavior: "smooth", block: "center" }); });
  }

  /* ---------- boot ---------- */
  renderLegend();
  if (window.viz) window.viz("map", renderMap, [arcsOf, arcPath, derived]); else renderMap();
  drawHaul(); drawMonths(); drawKnockouts();
  var mo = new MutationObserver(function () { renderMap(); }); mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { renderMap(); });
})();
