/* PSX & MUFAP dashboard. Reads data.json (or window.PKM_DATA in the standalone file).
   Everything that came from a scraped page is escaped before it touches the DOM. */
(function () {
  "use strict";

  // ---------------------------------------------------------------- helpers
  var $ = function (id) { return document.getElementById(id); };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function pct(x, d) {
    if (x == null || isNaN(x)) return "–";
    return (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x * 100).toFixed(d == null ? 1 : d) + "%";
  }
  function pctAbs(x, d) { return x == null ? "–" : (x * 100).toFixed(d == null ? 1 : d) + "%"; }
  function sgn(x) { return x == null ? "" : x > 0 ? "pos" : x < 0 ? "neg" : ""; }
  function num(x, d) {
    if (x == null || isNaN(x)) return "–";
    return Number(x).toLocaleString("en-US", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
  }
  function pkr(x) { return x == null ? "–" : "PKR " + num(x, 0); }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function store(k, v) {
    try { if (v === undefined) return JSON.parse(localStorage.getItem("pkm." + k)); localStorage.setItem("pkm." + k, JSON.stringify(v)); }
    catch (e) { return null; }
  }
  function cell(html, cls) { return "<td" + (cls ? ' class="' + cls + '"' : "") + ">" + html + "</td>"; }

  var D = null, bySym = {}, charts = {}, rendered = {};
  var SLOTS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"];
  var state = { compare: [], slots: {}, cRange: 250, ovRange: 250, sort: { key: "score", dir: -1 } };

  function chart(id, cfg) {
    if (charts[id]) charts[id].destroy();
    if (typeof Chart === "undefined") { $(id).parentNode.innerHTML = '<div class="empty">Charts need the Chart.js library (internet access).</div>'; return null; }
    charts[id] = new Chart($(id), cfg);
    return charts[id];
  }
  function baseOpts(extra) {
    var grid = css("--grid"), text = css("--text-2");
    var o = {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { labels: { color: text, boxWidth: 12, boxHeight: 12, usePointStyle: true } },
                 tooltip: { backgroundColor: css("--surface"), titleColor: css("--text"), bodyColor: css("--text"),
                            borderColor: css("--border"), borderWidth: 1, padding: 8 } },
      scales: { x: { ticks: { color: text, maxRotation: 0, autoSkip: true, maxTicksLimit: 7 }, grid: { color: grid, drawTicks: false }, border: { display: false } },
                y: { ticks: { color: text }, grid: { color: grid, drawTicks: false }, border: { display: false } } }
    };
    return Object.assign(o, extra || {});
  }
  function slotColor(sym) {
    if (!(sym in state.slots)) {
      var used = Object.values(state.slots);
      var free = SLOTS.find(function (s) { return used.indexOf(s) < 0; }) || SLOTS[0];
      state.slots[sym] = free;
    }
    return css(state.slots[sym]);
  }
  function rangeSeg(el, current, onPick) {
    var opts = [["1M", 21], ["3M", 63], ["6M", 126], ["1Y", 250], ["All", 100000]];
    el.innerHTML = opts.map(function (o) {
      return '<button data-n="' + o[1] + '"' + (o[1] === current ? ' class="on"' : "") + ">" + o[0] + "</button>";
    }).join("");
    el.onclick = function (e) {
      var n = e.target && e.target.getAttribute("data-n");
      if (!n) return;
      Array.prototype.forEach.call(el.children, function (b) { b.classList.toggle("on", b === e.target); });
      onPick(+n);
    };
  }
  function sliceSeries(sym, n) {
    var arr = D.series[sym] || [], cal = D.calendar;
    var start = Math.max(0, cal.length - n);
    return { labels: cal.slice(start), values: arr.slice(start) };
  }
  function rebase(values) {
    var base = null;
    return values.map(function (v) {
      if (v == null) return null;
      if (base == null) base = v;
      return +(100 * v / base).toFixed(2);
    });
  }
  function symCell(s) {
    return '<a href="#compare=' + encodeURIComponent(s.symbol) + '" data-sym="' + esc(s.symbol) + '"><b>' + esc(s.symbol) + "</b></a>" +
      (s.shariah ? '<span class="tag sh" title="KMI All Share (Shariah-compliant)">☪</span>' : "") +
      (s.held ? '<span class="tag" title="In the paper portfolio">held</span>' : "") +
      ((s.tags || []).indexOf("XD") >= 0 ? '<span class="tag" title="Trading ex-dividend">XD</span>' : "");
  }

  // ---------------------------------------------------------------- tabs
  var views = { overview: renderOverview, screener: renderScreener, compare: renderCompare,
                portfolio: renderPortfolio, dividends: renderDividends, funds: renderFunds };
  function show(v) {
    if (!views[v]) v = "overview";
    Array.prototype.forEach.call($("tabs").children, function (b) { b.classList.toggle("on", b.getAttribute("data-v") === v); });
    Object.keys(views).forEach(function (k) { $("v-" + k).classList.toggle("on", k === v); });
    views[v]();
    rendered[v] = true;
    store("view", v);
  }
  $("tabs").onclick = function (e) { var v = e.target.getAttribute("data-v"); if (v) show(v); };
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("[data-sym]");
    if (a) { e.preventDefault(); addCompare(a.getAttribute("data-sym")); show("compare"); }
  });
  $("theme").onclick = function () {
    var cur = document.documentElement.getAttribute("data-theme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    var next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    store("theme", next);
    Object.keys(rendered).forEach(function (k) { if ($("v-" + k).classList.contains("on")) views[k](); });
  };

  // ---------------------------------------------------------------- overview
  function renderOverview() {
    var b = (D.benchmark || {}).metrics || {};
    var st = D.stocks, up = st.filter(function (s) { return s.r1m > 0; }).length;
    var pf = D.portfolio;
    var k = [
      ["KSE-100, 1 month", pct(b["1m"]), "1 year " + pct(b["1y"]), sgn(b["1m"])],
      ["Market breadth", up + " / " + st.length, "shares up over 1 month", ""],
      ["Shariah-compliant", st.filter(function (s) { return s.shariah; }).length, "of " + st.length + " ranked", ""],
      ["Paper account", pf ? pkr(pf.total) : "not started", pf ? "return " + pct(pf["return"]) : "paper.py init", pf ? sgn(pf["return"]) : ""]
    ];
    $("ov-kpis").innerHTML = k.map(function (x) {
      return '<div class="kpi"><div class="l">' + esc(x[0]) + '</div><div class="v ' + x[3] + '">' + esc(x[1]) +
        '</div><div class="s">' + esc(x[2]) + "</div></div>";
    }).join("");
    var bsym = (D.benchmark || {}).symbol;
    function drawIndex(n) {
      var full = D.series[bsym] || [], last = full.length - 1;
      while (last >= 0 && full[last] == null) last--;  // index may lag the newest share prices
      var start = Math.max(0, last + 1 - n);
      var s = { labels: D.calendar.slice(start, last + 1), values: full.slice(start, last + 1) };
      chart("ov-index", { type: "line", data: { labels: s.labels, datasets: [{ label: bsym, data: s.values, borderColor: css("--s1"),
        borderWidth: 2, pointRadius: 0, spanGaps: true, tension: 0 }] },
        options: baseOpts({ interaction: { mode: "index", intersect: false }, plugins: Object.assign(baseOpts().plugins, { legend: { display: false } }) }) });
    }
    rangeSeg($("ov-range"), state.ovRange, function (n) { state.ovRange = n; drawIndex(n); });
    if (D.series[bsym]) drawIndex(state.ovRange); else $("ov-index").parentNode.innerHTML = '<div class="empty">No KSE-100 prices yet.</div>';

    var secs = (D.sectors || []).filter(function (s) { return s["3m"] != null; });
    var pos = css("--s1"), neg = css("--bad");
    chart("ov-sectors", { type: "bar",
      data: { labels: secs.map(function (s) { var m = window.innerWidth < 600 ? 18 : 26; return s.sector.length > m ? s.sector.slice(0, m - 1) + "…" : s.sector; }),
        datasets: [{ label: "Median 3M return", data: secs.map(function (s) { return +(s["3m"] * 100).toFixed(2); }),
          backgroundColor: secs.map(function (s) { return s["3m"] >= 0 ? pos : neg; }), borderRadius: 4, borderSkipped: false, barPercentage: 0.8 }] },
      options: baseOpts({ indexAxis: "y", plugins: Object.assign(baseOpts().plugins, { legend: { display: false },
        tooltip: Object.assign(baseOpts().plugins.tooltip, { callbacks: { label: function (c) {
          var s = secs[c.dataIndex];
          return ["3M " + pct(s["3m"]) + " · 1Y " + pct(s["1y"]), s.count + " stocks, " + s.shariah + " Shariah", "Median yield " + pctAbs(s.div_yield), "Top score: " + s.best];
        } } }) }),
        scales: { x: { ticks: { color: css("--text-2"), callback: function (v) { return v + "%"; } }, grid: { color: css("--grid") }, border: { display: false } },
                  y: { ticks: { color: css("--text-2"), autoSkip: false, font: { size: 11 } }, grid: { display: false }, border: { display: false } } } }) });
    $("ov-sectors").parentNode.style.height = Math.max(240, secs.length * 22 + 40) + "px";

    var top = st.slice().sort(function (a, b) { return (b.score || 0) - (a.score || 0); }).slice(0, 10);
    $("ov-top").innerHTML = "<tr><th class='l'>Stock</th><th>1M</th><th>3M</th><th>1Y</th><th>Yield</th><th>Score</th></tr>" +
      top.map(function (s) {
        return "<tr>" + cell(symCell(s), "l") + cell(pct(s.r1m), sgn(s.r1m)) + cell(pct(s.r3m), sgn(s.r3m)) +
          cell(pct(s.r1y), sgn(s.r1y)) + cell(pctAbs((s.div || {}).yield)) + cell(num(s.score)) + "</tr>";
      }).join("");
    var cal = (D.dividend_calendar || []).slice(0, 10);
    $("ov-divs").innerHTML = cal.length ? cal.map(function (c) {
      return "<li><span><a href='#' data-sym='" + esc(c.symbol) + "'><b>" + esc(c.symbol) + "</b></a> " + esc(c.details) +
        (c.type === "expected" ? ' <span class="tag">estimate</span>' : "") + (c.held ? ' <span class="tag">held</span>' : "") +
        "</span><span class='muted'>" + esc(c.date) + "</span></li>";
    }).join("") : "<li class='muted'>Nothing on file. Run pkdata.py payouts and company.</li>";
  }

  // ---------------------------------------------------------------- screener
  var SC_COLS = [
    ["sel", "", null], ["symbol", "Stock", "l"], ["name", "Name", "l hide-m"], ["sector", "Sector", "l"], ["close", "Close"],
    ["r1m", "1M"], ["r3m", "3M"], ["r1y", "1Y"], ["vs_idx_3m", "3M vs idx"], ["vol", "Volatility"], ["sharpe", "Sharpe"],
    ["yield", "Div yield"], ["pe", "P/E"], ["trend", "Trend"], ["score", "Score"]
  ];
  function val(s, k) { return k === "yield" ? (s.div || {}).yield : s[k]; }
  function renderScreener() {
    if (!rendered.screener) {
      var secs = Array.from(new Set(D.stocks.map(function (s) { return s.sector; }).filter(Boolean))).sort();
      $("f-sector").innerHTML = '<option value="">All sectors</option>' + secs.map(function (s) { return "<option>" + esc(s) + "</option>"; }).join("");
      ["f-q", "f-sector", "f-sh", "f-watch", "f-held", "f-yield"].forEach(function (id) { $(id).oninput = drawScreener; $(id).onchange = drawScreener; });
      $("f-compare").onclick = function () { show("compare"); };
    }
    drawScreener();
  }
  function drawScreener() {
    var q = $("f-q").value.trim().toLowerCase(), sec = $("f-sector").value, my = parseFloat($("f-yield").value);
    var rows = D.stocks.filter(function (s) {
      if (q && s.symbol.toLowerCase().indexOf(q) < 0 && (s.name || "").toLowerCase().indexOf(q) < 0) return false;
      if (sec && s.sector !== sec) return false;
      if ($("f-sh").checked && !s.shariah) return false;
      if ($("f-watch").checked && !s.watch) return false;
      if ($("f-held").checked && !s.held) return false;
      if (!isNaN(my) && !(((s.div || {}).yield || 0) * 100 >= my)) return false;
      return true;
    });
    var k = state.sort.key, d = state.sort.dir;
    rows.sort(function (a, b) {
      var x = val(a, k), y = val(b, k);
      if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * d;
    });
    var shown = rows.slice(0, 400);
    $("sc-table").innerHTML = "<thead><tr>" + SC_COLS.map(function (c) {
      var sort = c[0] === k ? (d < 0 ? "descending" : "ascending") : "none";
      return "<th data-k='" + c[0] + "' class='" + (c[2] || "") + "' aria-sort='" + sort + "'>" + c[1] + "</th>";
    }).join("") + "</tr></thead><tbody>" + shown.map(function (s) {
      var on = state.compare.indexOf(s.symbol) >= 0;
      return "<tr>" + cell("<input type='checkbox' class='sel' data-pick='" + esc(s.symbol) + "'" + (on ? " checked" : "") + " aria-label='Compare " + esc(s.symbol) + "'>", "l") +
        cell(symCell(s), "l") + cell(esc((s.name || "").slice(0, 28)), "l hide-m") + cell(esc((s.sector || "").slice(0, 24)), "l") +
        cell(num(s.close, 2)) + cell(pct(s.r1m), sgn(s.r1m)) + cell(pct(s.r3m), sgn(s.r3m)) + cell(pct(s.r1y), sgn(s.r1y)) +
        cell(pct(s.vs_idx_3m), sgn(s.vs_idx_3m)) + cell(pctAbs(s.vol, 0)) + cell(s.sharpe == null ? "–" : s.sharpe.toFixed(2)) +
        cell(pctAbs((s.div || {}).yield)) + cell(s.pe == null ? "–" : num(s.pe, 1)) + cell(esc(s.trend)) + cell(num(s.score)) + "</tr>";
    }).join("") + "</tbody>";
    $("sc-note").textContent = rows.length + " shares" + (rows.length > shown.length ? " (first 400 shown)" : "") +
      ". Tap a column to sort, tick boxes to compare (up to 6). " + (D.notes.illiquid_left_out ? D.notes.illiquid_left_out + " illiquid shares left out. " : "") +
      D.notes.face_value_note;
    $("f-compare").textContent = "Compare selected (" + state.compare.length + ")";
  }
  $("sc-table").addEventListener("click", function (e) {
    var th = e.target.closest("th");
    if (th && th.getAttribute("data-k") && th.getAttribute("data-k") !== "sel") {
      var k = th.getAttribute("data-k");
      state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : (["symbol", "name", "sector", "trend"].indexOf(k) >= 0 ? 1 : -1) };
      drawScreener();
    }
  });
  $("sc-table").addEventListener("change", function (e) {
    var s = e.target.getAttribute("data-pick");
    if (!s) return;
    if (e.target.checked) { if (!addCompare(s)) e.target.checked = false; } else removeCompare(s);
    $("f-compare").textContent = "Compare selected (" + state.compare.length + ")";
  });

  // ---------------------------------------------------------------- compare
  function addCompare(sym) {
    sym = String(sym || "").toUpperCase().trim();
    if (!bySym[sym]) return false;
    if (state.compare.indexOf(sym) >= 0) return true;
    if (state.compare.length >= 6) { alert("Compare up to 6 shares at a time."); return false; }
    state.compare.push(sym); slotColor(sym); saveCompare(); return true;
  }
  function removeCompare(sym) {
    state.compare = state.compare.filter(function (s) { return s !== sym; });
    delete state.slots[sym]; saveCompare();
  }
  function saveCompare() {
    store("compare", state.compare); store("slots", state.slots);
    try { history.replaceState(null, "", "#compare=" + state.compare.join(",")); } catch (e) { /* file:// */ }
  }
  function renderCompare() {
    if (!rendered.compare) {
      $("c-symbols").innerHTML = D.stocks.map(function (s) { return "<option value='" + esc(s.symbol) + "'>" + esc(s.name || "") + "</option>"; }).join("");
      $("c-addbtn").onclick = function () { if (addCompare($("c-add").value)) { $("c-add").value = ""; renderCompare(); } };
      $("c-add").onkeydown = function (e) { if (e.key === "Enter") $("c-addbtn").onclick(); };
      $("c-chips").onclick = function (e) { var s = e.target.getAttribute("data-rm"); if (s) { removeCompare(s); renderCompare(); } };
      rangeSeg($("c-range"), state.cRange, function (n) { state.cRange = n; drawComparePrice(); });
    }
    var sel = state.compare.map(function (s) { return bySym[s]; }).filter(Boolean);
    $("c-chips").innerHTML = sel.map(function (s) {
      return '<span class="chip"><span class="dot" style="background:' + slotColor(s.symbol) + '"></span>' + esc(s.symbol) +
        '<button data-rm="' + esc(s.symbol) + '" aria-label="Remove ' + esc(s.symbol) + '">×</button></span>';
    }).join("");
    if (!sel.length) {
      Object.keys(charts).forEach(function (k) { if (k.indexOf("c-") === 0) { charts[k].destroy(); delete charts[k]; } });
      $("c-table").innerHTML = "<tr><td class='l muted'>Add shares above, or tick them in the Screener.</td></tr>";
      $("c-divs").innerHTML = "";
      return;
    }
    drawComparePrice();
    var periods = [["1M", "r1m"], ["3M", "r3m"], ["6M", "r6m"], ["1Y", "r1y"], ["YTD", "ytd"]];
    var pctTick = { color: css("--text-2"), callback: function (v) { return v + "%"; } };
    chart("c-returns", { type: "bar", data: { labels: periods.map(function (p) { return p[0]; }),
      datasets: sel.map(function (s) { return { label: s.symbol, backgroundColor: slotColor(s.symbol), borderRadius: 4, borderSkipped: false,
        data: periods.map(function (p) { return s[p[1]] == null ? null : +(s[p[1]] * 100).toFixed(2); }) }; }) },
      options: baseOpts({ scales: { x: { ticks: { color: css("--text-2") }, grid: { display: false }, border: { display: false } },
        y: { ticks: pctTick, grid: { color: css("--grid") }, border: { display: false } } } }) });
    var risk = [["Volatility", function (s) { return s.vol; }], ["Max drawdown", function (s) { return s.mdd == null ? null : -s.mdd; }],
                ["Dividend yield", function (s) { return (s.div || {}).yield; }]];
    chart("c-risk", { type: "bar", data: { labels: risk.map(function (r) { return r[0]; }),
      datasets: sel.map(function (s) { return { label: s.symbol, backgroundColor: slotColor(s.symbol), borderRadius: 4, borderSkipped: false,
        data: risk.map(function (r) { var v = r[1](s); return v == null ? null : +(v * 100).toFixed(2); }) }; }) },
      options: baseOpts({ scales: { x: { ticks: { color: css("--text-2") }, grid: { display: false }, border: { display: false } },
        y: { beginAtZero: true, ticks: pctTick, grid: { color: css("--grid") }, border: { display: false } } } }) });

    var rows = [
      ["Name", function (s) { return esc(s.name || "–"); }], ["Sector", function (s) { return esc(s.sector || "–"); }],
      ["Shariah (KMI)", function (s) { return s.shariah ? "<span class='pos'>✓ Yes</span>" : s.shariah === false ? "No" : "–"; }],
      ["Close", function (s) { return num(s.close, 2) + " <span class='muted small'>" + esc(s.last_date) + "</span>"; }],
      ["52-week range", function (s) { return s.low_52w == null ? "–" : num(s.low_52w, 2) + " – " + num(s.high_52w, 2); }],
      ["1 month", function (s) { return "<span class='" + sgn(s.r1m) + "'>" + pct(s.r1m) + "</span>"; }],
      ["3 months", function (s) { return "<span class='" + sgn(s.r3m) + "'>" + pct(s.r3m) + "</span>"; }],
      ["1 year", function (s) { return "<span class='" + sgn(s.r1y) + "'>" + pct(s.r1y) + "</span>"; }],
      ["3M vs KSE-100", function (s) { return "<span class='" + sgn(s.vs_idx_3m) + "'>" + pct(s.vs_idx_3m) + "</span>"; }],
      ["Volatility (1Y)", function (s) { return pctAbs(s.vol); }], ["Max drawdown (1Y)", function (s) { return pct(s.mdd); }],
      ["Sharpe (1Y)", function (s) { return s.sharpe == null ? "–" : s.sharpe.toFixed(2); }], ["Trend", function (s) { return esc(s.trend); }],
      ["P/E (TTM)", function (s) { return s.pe == null ? "–" : num(s.pe, 1); }],
      ["Market cap", function (s) { return s.mcap_m == null ? "–" : "PKR " + num(s.mcap_m / 1000, 1) + " bn"; }],
      ["Avg daily volume", function (s) { return num(s.avg_volume); }],
      ["Dividend yield (12M)", function (s) { return pctAbs((s.div || {}).yield); }],
      ["Dividends per share (12M)", function (s) { return (s.div || {}).dps_ttm == null ? "–" : "Rs " + num(s.div.dps_ttm, 2); }],
      ["Last dividend", function (s) { var l = (s.div || {}).last; return l ? esc(l.details) + " <span class='muted small'>" + esc(l.announced) + "</span>" : "–"; }],
      ["Next book closure", function (s) { var u = ((s.div || {}).upcoming || [])[0]; return u ? esc(u.details) + " · " + esc(u.bc_from) : "none announced"; }],
      ["Expected next", function (s) { var e = (s.div || {}).expected_next; return e ? "around " + esc(e.around) + " <span class='muted small'>(last year " + esc(e.last_year) + ")</span>" : "–"; }],
      ["Score", function (s) { return num(s.score); }]
    ];
    $("c-table").innerHTML = "<tr><th class='l'></th>" + sel.map(function (s) {
      return "<th class='l'><span class='dot' style='display:inline-block;width:10px;height:10px;border-radius:50%;background:" + slotColor(s.symbol) + "'></span> " + esc(s.symbol) + "</th>";
    }).join("") + "</tr>" + rows.map(function (r) {
      return "<tr><td class='l muted'>" + r[0] + "</td>" + sel.map(function (s) { return cell(r[1](s), "l"); }).join("") + "</tr>";
    }).join("");
    var divRows = [];
    sel.forEach(function (s) { (s.payouts || []).slice(0, 6).forEach(function (p) { divRows.push([s.symbol, p]); }); });
    $("c-divs").innerHTML = "<tr><th class='l'>Stock</th><th class='l'>Announced</th><th class='l'>Period</th><th class='l'>Payout</th><th class='l'>Book closure</th></tr>" +
      (divRows.length ? divRows.map(function (r) {
        var p = r[1];
        return "<tr>" + cell("<b>" + esc(r[0]) + "</b>", "l") + cell(esc(p.announced), "l") + cell(esc(p.period), "l") + cell(esc(p.details), "l") +
          cell(esc(p.bc_from || "") + (p.bc_to && p.bc_to !== p.bc_from ? " – " + esc(p.bc_to) : ""), "l") + "</tr>";
      }).join("") : "<tr><td class='l muted' colspan='5'>No payout history on file (pkdata.py company).</td></tr>");
  }
  function drawComparePrice() {
    var sel = state.compare.filter(function (s) { return bySym[s]; });
    if (!sel.length) return;
    var labels = null, sets = sel.map(function (sym) {
      var s = sliceSeries(sym, state.cRange); labels = s.labels;
      return { label: sym, data: rebase(s.values), borderColor: slotColor(sym), backgroundColor: slotColor(sym),
               borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, spanGaps: true, tension: 0 };
    });
    var b = (D.benchmark || {}).symbol;
    if (D.series[b]) {
      var bs = sliceSeries(b, state.cRange);
      sets.push({ label: b, data: rebase(bs.values), borderColor: css("--muted"), backgroundColor: css("--muted"),
                  borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0, spanGaps: true });
    }
    chart("c-price", { type: "line", data: { labels: labels, datasets: sets },
      options: baseOpts({ interaction: { mode: "index", intersect: false } }) });
  }

  // ---------------------------------------------------------------- portfolio
  function renderPortfolio() {
    var p = D.portfolio;
    if (!p) { $("v-portfolio").innerHTML = '<div class="empty">No paper account yet. Run <code>paper.py init</code>, then <code>propose.py run</code>.</div>'; return; }
    var marks = p.marks || [], bench = null;
    if (marks.length > 1 && marks[0].benchmark && marks[marks.length - 1].benchmark) bench = marks[marks.length - 1].benchmark / marks[0].benchmark - 1;
    var k = [["Account value", pkr(p.total), "started " + pkr(p.starting_cash), ""],
             ["Return", pct(p["return"]), bench == null ? "since " + p.created.slice(0, 10) : "KSE-100 " + pct(bench) + " same period", sgn(p["return"])],
             ["Cash", pkr(p.cash), pctAbs(p.cash / p.total, 0) + " of account", ""],
             ["Realised + dividends", pkr(p.realized), (p.dividends || []).length + " dividend credits", sgn(p.realized)]];
    $("pf-kpis").innerHTML = k.map(function (x) {
      return '<div class="kpi"><div class="l">' + esc(x[0]) + '</div><div class="v ' + x[3] + '">' + esc(x[1]) + '</div><div class="s">' + esc(x[2]) + "</div></div>";
    }).join("");
    if (marks.length > 1) {
      var v0 = marks[0].value, b0 = marks[0].benchmark;
      var sets = [{ label: "Paper account", data: marks.map(function (m) { return +(100 * m.value / v0).toFixed(2); }),
        borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 0 }];
      if (b0) sets.push({ label: "KSE-100", data: marks.map(function (m) { return m.benchmark ? +(100 * m.benchmark / b0).toFixed(2) : null; }),
        borderColor: css("--muted"), backgroundColor: css("--muted"), borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0, spanGaps: true });
      chart("pf-equity", { type: "line", data: { labels: marks.map(function (m) { return m.date; }), datasets: sets },
        options: baseOpts({ interaction: { mode: "index", intersect: false } }) });
      $("pf-eqnote").textContent = "Both rebased to 100 on the first day recorded. The daily service records one point per day.";
    } else {
      $("pf-equity").parentNode.innerHTML = '<div class="empty">The value chart starts once the daily service has recorded two days (paper.py mark).</div>';
    }
    var alloc = {};
    p.holdings.forEach(function (h) {
      var key = h.kind === "fund" ? "Mutual funds" : (h.sector || "Unknown sector");
      alloc[key] = (alloc[key] || 0) + (h.value || 0);
    });
    if (p.cash > 0) alloc.Cash = p.cash;
    var ent = Object.keys(alloc).map(function (k) { return [k, alloc[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
    if (ent.length > 6) { var rest = ent.slice(5).reduce(function (s, e) { return s + e[1]; }, 0); ent = ent.slice(0, 5).concat([["Other", rest]]); }
    chart("pf-alloc", { type: "doughnut", data: { labels: ent.map(function (e) { return e[0]; }),
      datasets: [{ data: ent.map(function (e) { return Math.round(e[1]); }), backgroundColor: ent.map(function (e, i) { return css(SLOTS[i]); }),
        borderColor: css("--surface"), borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, cutout: "62%",
        plugins: { legend: { position: window.innerWidth < 600 ? "bottom" : "right", labels: { color: css("--text-2"), boxWidth: 12, usePointStyle: true } },
          tooltip: { callbacks: { label: function (c) { return c.label + ": " + pkr(c.raw) + " (" + pctAbs(c.raw / p.total, 0) + ")"; } } } } } });
    $("pf-hold").innerHTML = "<tr><th class='l'>Holding</th><th>Qty / units</th><th>Price</th><th>Value</th><th>P/L</th><th class='l'>Strategy</th><th class='l'>Review</th><th class='l'>Next dividend</th></tr>" +
      p.holdings.map(function (h) {
        var s = bySym[h.symbol] || {}, u = ((s.div || {}).upcoming || [])[0], e = (s.div || {}).expected_next;
        var nd = u ? esc(u.details) + " · BC " + esc(u.bc_from) : e ? "~" + esc(e.around) + " (est.)" : "–";
        return "<tr>" + cell(h.kind === "fund" ? esc(h.symbol) + " <span class='tag'>fund</span>" : symCell(Object.assign({ symbol: h.symbol }, s)), "l") +
          cell(h.kind === "fund" ? num(h.units, 2) : num(h.qty)) + cell(num(h.price, h.kind === "fund" ? 4 : 2)) + cell(pkr(h.value)) +
          cell(pct(h.pl), sgn(h.pl)) + cell(h.strategy ? esc(h.strategy) + " <span class='muted small'>" + esc(JSON.stringify(h.params || {})) + "</span>" : "–", "l") +
          cell(h.action ? (h.action === "SELL" ? "<b class='neg'>SELL</b> " : "HOLD ") + "<span class='muted small'>" + esc(h.why || "") + "</span>" : "–", "l") +
          cell(h.kind === "fund" ? "–" : nd, "l") + "</tr>";
      }).join("");
    var pr = D.proposal;
    if (pr) {
      $("pf-prop").innerHTML = "<div class='muted small'>" + esc(pr.date) + " · screened " + esc(pr.screened) + " (" + esc(pr.scope) + ")" +
        (pr.filters && pr.filters.shariah ? " · Shariah only" : "") + "</div><div class='tablewrap'><table><tr><th class='l'>Stock</th><th class='l'>Strategy</th><th>OOS CAGR</th><th>B&amp;H OOS</th><th class='l'>Result</th></tr>" +
        (pr.candidates || []).map(function (c) {
          var res = pr.picks.indexOf(c.symbol) >= 0 ? "<b class='pos'>PICK</b>" : c.pass ? "pass" : "<span class='muted' title='" + esc(c.why) + "'>no</span>";
          return "<tr>" + cell("<b>" + esc(c.symbol) + "</b>", "l") + cell(esc(c.strategy || "–"), "l") + cell(pct((c.out || {}).cagr), sgn((c.out || {}).cagr)) +
            cell(pct((c.out_buyhold || {}).cagr)) + cell(res, "l") + "</tr>";
        }).join("") + "</table></div><div class='note'>OOS = the last 30% of each history, untouched by parameter tuning.</div>";
    } else { $("pf-prop").innerHTML = "<div class='muted'>No proposal yet: propose.py run</div>"; }
    var dv = (p.dividends || []).slice().reverse();
    $("pf-divs").innerHTML = dv.length ? dv.map(function (d) {
      return "<li><span><b>" + esc(d.symbol) + "</b> " + esc(d.details) + (d.bonus_shares ? " +" + esc(d.bonus_shares) + " bonus" : "") +
        "</span><span>" + pkr(d.net) + " <span class='muted small'>" + esc(d.book_closure) + "</span></span></li>";
    }).join("") : "<li class='muted'>None yet.</li>";
  }

  // ---------------------------------------------------------------- dividends
  function renderDividends() {
    if (!rendered.dividends) { $("d-held").onchange = renderDividends; $("d-sh").onchange = renderDividends; }
    var cal = (D.dividend_calendar || []).filter(function (c) {
      return (!$("d-held").checked || c.held) && (!$("d-sh").checked || c.shariah);
    });
    $("d-cal").innerHTML = "<tr><th class='l'>Date</th><th class='l'>Stock</th><th class='l'>Payout</th><th class='l'>Kind</th></tr>" +
      (cal.length ? cal.map(function (c) {
        return "<tr>" + cell(esc(c.date), "l") + cell("<a href='#' data-sym='" + esc(c.symbol) + "'><b>" + esc(c.symbol) + "</b></a>" +
          (c.shariah ? '<span class="tag sh">☪</span>' : "") + (c.held ? '<span class="tag">held</span>' : ""), "l") +
          cell(esc(c.details), "l") + cell(c.type === "expected" ? "<span class='muted'>expected (estimate)</span>" : "book closure", "l") + "</tr>";
      }).join("") : "<tr><td class='l muted' colspan='4'>Nothing coming up on file.</td></tr>");
    var ys = D.stocks.filter(function (s) { return (s.div || {}).yield > 0 && (!$("d-sh").checked || s.shariah) && (!$("d-held").checked || s.held); })
      .sort(function (a, b) { return b.div.yield - a.div.yield; }).slice(0, 15);
    chart("d-yield", { type: "bar", data: { labels: ys.map(function (s) { return s.symbol; }),
      datasets: [{ label: "Dividend yield, last 12 months", data: ys.map(function (s) { return +(s.div.yield * 100).toFixed(2); }),
        backgroundColor: css("--s1"), borderRadius: 4, borderSkipped: false, barPercentage: 0.8 }] },
      options: baseOpts({ indexAxis: "y", plugins: Object.assign(baseOpts().plugins, { legend: { display: false },
        tooltip: Object.assign(baseOpts().plugins.tooltip, { callbacks: { label: function (c) { var s = ys[c.dataIndex];
          return ["Yield " + pctAbs(s.div.yield) + " · Rs " + num(s.div.dps_ttm, 2) + "/share", (s.sector || "") + (s.shariah ? " · Shariah" : "")]; } } }) }),
        scales: { x: { ticks: { color: css("--text-2"), callback: function (v) { return v + "%"; } }, grid: { color: css("--grid") }, border: { display: false } },
                  y: { ticks: { color: css("--text-2"), autoSkip: false }, grid: { display: false }, border: { display: false } } } }) });
    $("d-note").textContent = "Very high yields often mean a one-off payout or a falling price; check the history in Compare. " + D.notes.face_value_note;
  }

  // ---------------------------------------------------------------- funds
  function renderFunds() {
    var F = D.funds;
    if (!F) { $("v-funds").innerHTML = '<div class="empty">No MUFAP data yet: pkdata.py mufap</div>'; return; }
    var cats = Object.keys(F.categories).sort();
    if (!rendered.funds) {
      $("fu-cat").innerHTML = cats.map(function (c) { return "<option>" + esc(c) + "</option>"; }).join("");
      var pref = store("fundcat");
      $("fu-cat").value = cats.indexOf(pref) >= 0 ? pref : (cats.indexOf("Equity") >= 0 ? "Equity" : cats[0]);
      $("fu-cat").onchange = function () { store("fundcat", $("fu-cat").value); renderFunds(); };
    }
    var c = F.categories[$("fu-cat").value];
    $("fu-type").textContent = c.count + " funds · " + c.type + " returns · MUFAP report " + F.date;
    var top = c.funds.slice(0, 8);
    var per = [["30 days", "d30"], ["90 days", "d90"], ["1 year", "d365"]];
    chart("fu-chart", { type: "bar", data: { labels: top.map(function (f) { return f.fund.length > 28 ? f.fund.slice(0, 27) + "…" : f.fund; }),
      datasets: per.map(function (p, i) { return { label: p[0], data: top.map(function (f) { return f[p[1]]; }), backgroundColor: css(SLOTS[i]),
        borderRadius: 4, borderSkipped: false }; }) },
      options: baseOpts({ indexAxis: "y", scales: { x: { ticks: { color: css("--text-2"), callback: function (v) { return v + "%"; } }, grid: { color: css("--grid") }, border: { display: false } },
        y: { ticks: { color: css("--text-2"), autoSkip: false, font: { size: 11 } }, grid: { display: false }, border: { display: false } } } }) });
    $("fu-table").innerHTML = "<tr><th class='l'>#</th><th class='l'>Fund</th><th>NAV</th><th>30D</th><th>90D</th><th>YTD</th><th>1Y</th><th>3Y</th><th>Score</th></tr>" +
      c.funds.map(function (f, i) {
        function r(x) { return x == null ? "–" : "<span class='" + sgn(x) + "'>" + x.toFixed(1) + "</span>"; }
        return "<tr>" + cell(i + 1, "l") + cell(esc(f.fund) + (f.rating ? " <span class='tag'>" + esc(f.rating) + "</span>" : ""), "l") +
          cell(num(f.nav, 4)) + cell(r(f.d30)) + cell(r(f.d90)) + cell(r(f.ytd)) + cell(r(f.d365)) + cell(r(f.y3)) + cell(f.score == null ? "–" : num(f.score)) + "</tr>";
      }).join("");
  }

  // ---------------------------------------------------------------- boot
  function boot(data) {
    D = data;
    D.stocks.forEach(function (s) { bySym[s.symbol] = s; });
    $("meta").textContent = "Built " + D.generated + " · " + D.stocks.length + " shares (" + D.scope + ") · prices to " +
      (D.calendar[D.calendar.length - 1] || "–");
    var theme = store("theme"); if (theme) document.documentElement.setAttribute("data-theme", theme);
    var fromHash = (location.hash.match(/compare=([^&]*)/) || [])[1];
    var saved = fromHash ? decodeURIComponent(fromHash).split(",") : (store("compare") || []);
    var slots = store("slots") || {};
    saved.forEach(function (s) { if (bySym[s] && slots[s]) state.slots[s] = slots[s]; addCompare(s); });
    if (!state.compare.length) D.stocks.filter(function (s) { return s.held || s.watch; }).slice(0, 3).forEach(function (s) { addCompare(s.symbol); });
    show(fromHash ? "compare" : (store("view") || "overview"));
  }
  if (window.PKM_DATA) boot(window.PKM_DATA);
  else fetch("data.json", { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error(r.status + " " + r.statusText); return r.json();
  }).then(boot).catch(function (e) {
    document.querySelector("main").innerHTML = '<div class="empty">Could not load data.json (' + esc(e.message) + "). Run dashboard.py build.</div>";
  });
})();
