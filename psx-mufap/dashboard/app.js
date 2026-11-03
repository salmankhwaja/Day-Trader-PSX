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
  var state = { compare: [], slots: {}, cRange: 250, ovRange: 250, sort: { key: "score", dir: -1 }, scMode: store("scMode") || "ranked" };

  // Chart.js comes from cdnjs and loads in the background (async): a slow or blocked CDN on a
  // phone network must never leave the page blank. Charts draw once it arrives; if it never does,
  // each chart says so and everything else still works.
  var chartLib = typeof Chart !== "undefined" ? "ready" : "loading";
  function chartLibDone(state) {
    if (chartLib !== "loading") return;
    chartLib = state;
    if (D) Object.keys(views).forEach(function (k) { if ($("v-" + k).classList.contains("on")) views[k](); });
  }
  (function () {
    var tag = document.getElementById("chartjs");
    if (chartLib === "ready" || !tag) return;
    tag.addEventListener("load", function () { chartLibDone(typeof Chart !== "undefined" ? "ready" : "failed"); });
    tag.addEventListener("error", function () { chartLibDone("failed"); });
    setTimeout(function () { chartLibDone(typeof Chart !== "undefined" ? "ready" : "failed"); }, 20000);
  })();
  function chart(id, cfg) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
    if (!$(id)) return null;  // already replaced by a message (no Chart.js, or no data for it)
    if (chartLib !== "ready" && typeof Chart !== "undefined") chartLib = "ready";
    var box = $(id).parentNode;
    if (chartLib === "loading") { box.classList.add("waiting"); return null; }
    box.classList.remove("waiting", "nolib");
    if (chartLib === "failed") { box.classList.add("nolib"); return null; }   // keep the canvas: views redraw
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
      (s.owned ? '<span class="tag own" title="In your portfolio">owned</span>' : "") +
      (s.held ? '<span class="tag" title="In the paper account">paper</span>' : "") +
      ((s.tags || []).indexOf("XD") >= 0 ? '<span class="tag" title="Trading ex-dividend">XD</span>' : "");
  }

  // ---------------------------------------------------------------- tabs
  var views = { overview: renderOverview, screener: renderScreener, compare: renderCompare,
                mine: renderMine, portfolio: renderPortfolio, dividends: renderDividends, funds: renderFunds, risk: renderRisk, data: renderData };
  function show(v) {
    if (!views[v]) v = "overview";
    Array.prototype.forEach.call($("tabs").children, function (b) { b.classList.toggle("on", b.getAttribute("data-v") === v); });
    Object.keys(views).forEach(function (k) { $("v-" + k).classList.toggle("on", k === v); });
    views[v]();
    rendered[v] = true;
    store("view", v);
  }
  $("tabs").onclick = function (e) { var b = e.target.closest && e.target.closest("[data-v]"); if (b) show(b.getAttribute("data-v")); };
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("[data-sym]");
    if (a) { e.preventDefault(); addCompare(a.getAttribute("data-sym")); show("compare"); }
  });
  // ---------------------------------------------------------------- themes & clock
  var THEMES = [["auto", "Auto (follow phone)"], ["light", "Light"], ["dark", "Dark"], ["bluegray", "Blue Gray"],
                ["black", "Black"], ["terminal", "Terminal"], ["red", "Red"],
                // CyberWatch's four, with its colours
                ["obsidian", "Obsidian (CyberWatch)"], ["crimson", "Crimson (CyberWatch)"], ["midnight", "Midnight (CyberWatch)"], ["arctic", "Arctic (CyberWatch)"]];
  function applyTheme(id, rerender) {
    var ok = THEMES.some(function (t) { return t[0] === id; }) ? id : "auto";
    document.documentElement.setAttribute("data-theme", ok);
    store("theme", ok);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", css("--surface") || "#1d4ed8");
    Array.prototype.forEach.call($("theme").querySelectorAll("[data-t]"), function (b) {
      var on = b.getAttribute("data-t") === ok;
      b.classList.toggle("active", on); b.setAttribute("aria-checked", String(on));
    });
    if (rerender) Object.keys(rendered).forEach(function (k) { if ($("v-" + k).classList.contains("on")) views[k](); });  // charts read the colours
  }
  (function setupThemes() {   // CyberWatch-style: one tap on a coloured dot
    var row = $("theme");
    row.innerHTML = THEMES.map(function (t) {
      return (t[0] === "obsidian" ? '<span class="sw-sep" aria-hidden="true"></span>' : "") +
        '<button type="button" class="sw sw-' + t[0] + '" role="radio" aria-checked="false" data-t="' + t[0] +
        '" title="' + t[1] + '" aria-label="' + t[1] + ' theme"></button>';
    }).join("");
    row.onclick = function (e) { var b = e.target.closest("[data-t]"); if (b) applyTheme(b.getAttribute("data-t"), true); };
    applyTheme(document.documentElement.getAttribute("data-theme") || store("theme") || "auto", false);
  })();
  // CyberWatch's clock: date, time to the millisecond in the theme's clock colour, and the time zone.
  // Drawn with requestAnimationFrame, so it pauses by itself when the page isn't on screen.
  (function startClock() {
    var DN = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"], MN = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
    var p2 = function (n) { return ("0" + n).slice(-2); }, tz = "";
    try { tz = (Intl.DateTimeFormat().resolvedOptions().timeZone || "").split("/").pop().replace(/_/g, " "); } catch (e) {}
    var off = -new Date().getTimezoneOffset();
    $("clock").innerHTML = '<div class="clock-date" id="cD"></div><div class="clock-time" id="cT"></div>' +
      '<div class="clock-tz">' + (off === 0 ? "UTC" : esc(tz) + " UTC" + (off > 0 ? "+" : "-") + Math.floor(Math.abs(off) / 60) +
      (off % 60 ? ":" + p2(Math.abs(off % 60)) : "")) + "</div>";
    var cD = $("cD"), cT = $("cT"), lastDate = "";
    function frame() {
      var n = new Date(), d = DN[n.getDay()] + " " + p2(n.getDate()) + " " + MN[n.getMonth()] + " " + n.getFullYear();
      if (d !== lastDate) { cD.textContent = d; lastDate = d; }
      cT.innerHTML = p2(n.getHours()) + ":" + p2(n.getMinutes()) + ":" + p2(n.getSeconds()) +
        '<span class="clock-ms">.' + ("00" + n.getMilliseconds()).slice(-3) + "</span>";
      requestAnimationFrame(frame);
    }
    frame();
  })();

  // ---------------------------------------------------------------- number fields: 100,000
  function groupNum(raw) {
    var t = String(raw == null ? "" : raw).replace(/[^0-9.\-]/g, ""), neg = t.charAt(0) === "-";
    t = t.replace(/-/g, "");
    var parts = t.split("."), i = parts.shift().replace(/^0+(?=\d)/, ""), dec = parts.length ? "." + parts.join("") : "";
    return (neg ? "-" : "") + (i ? i.replace(/\B(?=(\d{3})+(?!\d))/g, ",") : (dec ? "0" : "")) + dec;
  }
  function nv(id) { var v = parseFloat(String($(id).value).replace(/,/g, "")); return isNaN(v) ? 0 : v; }
  function enhanceNumbers(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll('input[type="number"]'), function (el) {
      el.type = "text"; el.inputMode = "decimal"; el.classList.add("numeric"); el.autocomplete = "off";
      if (el.value) el.value = groupNum(el.value);
      el.addEventListener("input", function () {
        var before = el.value, caret = el.selectionStart == null ? before.length : el.selectionStart;
        var sig = before.slice(0, caret).replace(/[^0-9.\-]/g, "").length, after = groupNum(before);
        if (after === before) return;
        el.value = after;
        var k = 0, pos = 0;
        while (pos < after.length && k < sig) { if (/[0-9.\-]/.test(after.charAt(pos))) k++; pos++; }
        try { el.setSelectionRange(pos, pos); } catch (e) {}
      }, true);
    });
  }
  enhanceNumbers(document);

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
    if (D.series[bsym]) drawIndex(state.ovRange); else if ($("ov-index")) $("ov-index").parentNode.innerHTML = '<div class="empty">No KSE-100 prices yet.</div>';

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
    if ($("ov-sectors")) $("ov-sectors").parentNode.style.height = Math.max(240, secs.length * 22 + 40) + "px";

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
    drawLiveCard();
  }

  // ---------------------------------------------------------------- screener
  var SC_COLS = [
    ["sel", "", null], ["symbol", "Stock", "l"], ["name", "Name", "l hide-m"], ["sector", "Sector", "l"], ["close", "Close / live"],
    ["r1m", "1M"], ["r3m", "3M"], ["r1y", "1Y"], ["vs_idx_3m", "3M vs idx"], ["vol", "Volatility"], ["sharpe", "Sharpe"],
    ["yield", "Div yield"], ["pe", "P/E"], ["trend", "Trend"], ["score", "Score"], ["mover", "Mover", "l"]
  ];
  function val(s, k) {
    if (k === "mover") { var t = (MV || {})[s.symbol]; return t ? t.length : null; }
    return k === "yield" ? (s.div || {}).yield : s[k];
  }

  // Movers: every listed share's day (market.rows, from the last market-watch snapshot or the last
  // two closes), with live quotes laid over when Live is on. Top N gainers, losers and most traded
  // among shares trading at least movers_min_value rupees, and each sector's best gainer.
  var MV = null;
  function marketRows() {
    return ((D.market || {}).rows || []).map(function (r) {
      var x = quote(r.symbol);
      if (!x) return r;
      return Object.assign({}, r, { price: x.current, change: x.change_pct == null ? r.change : x.change_pct / 100,
        volume: x.volume, value: x.current && x.volume ? x.current * x.volume : null, source: "live" });
    });
  }
  function moverTags(rows) {
    var M = D.market || {}, n = M.movers_max || 10, floor = M.movers_min_value || 5e6, out = {}, best = {};
    function add(s, t) { (out[s] = out[s] || []).push(t); }
    var liq = rows.filter(function (r) { return r.change != null && (r.value || 0) >= floor; });
    liq.slice().sort(function (a, b) { return b.change - a.change; }).slice(0, n).forEach(function (r, i) {
      if (r.change > 0) add(r.symbol, ["up", "▲ Gainer #" + (i + 1)]);
    });
    liq.slice().sort(function (a, b) { return a.change - b.change; }).slice(0, n).forEach(function (r, i) {
      if (r.change < 0) add(r.symbol, ["down", "▼ Loser #" + (i + 1)]);
    });
    liq.slice().sort(function (a, b) { return (b.volume || 0) - (a.volume || 0); }).slice(0, n).forEach(function (r, i) {
      add(r.symbol, ["act", "◆ Most traded #" + (i + 1)]);
    });
    liq.forEach(function (r) { if (r.change > 0 && (!best[r.sector] || r.change > best[r.sector].change)) best[r.sector] = r; });
    Object.keys(best).forEach(function (k) { add(best[k].symbol, ["sec", "★ Sector best"]); });
    return out;
  }
  function moverHtml(sym) {
    var t = (MV || {})[sym];
    return t ? t.map(function (x) { return "<span class='mv " + x[0] + "'>" + esc(x[1]) + "</span>"; }).join(" ") : "<span class='muted'>–</span>";
  }
  function renderScreener() {
    if (!rendered.screener) {
      var secs = Array.from(new Set(D.stocks.map(function (s) { return s.sector; }).filter(Boolean))).sort();
      $("f-sector").innerHTML = '<option value="">All sectors</option>' + secs.map(function (s) { return "<option>" + esc(s) + "</option>"; }).join("");
      var secs2 = Array.from(new Set(secs.concat(((D.market || {}).rows || []).map(function (r) { return r.sector; }))
        .map(function (s) { return String(s).toUpperCase(); }))).sort();
      $("f-sector").innerHTML = '<option value="">All sectors</option>' + secs2.map(function (s) { return "<option>" + esc(s) + "</option>"; }).join("");
      ["f-q", "f-sector", "f-sh", "f-watch", "f-held", "f-yield", "f-mov"].forEach(function (id) { $(id).oninput = drawScreener; $(id).onchange = drawScreener; });
      $("f-mode").onclick = function (e) {
        var m = e.target.getAttribute("data-m");
        if (!m) return;
        state.scMode = m; store("scMode", m); drawScreener();
      };
      $("f-compare").onclick = function () { show("compare"); };
    }
    drawScreener();
  }
  function drawScreener() {
    MV = moverTags(marketRows());
    Array.prototype.forEach.call($("f-mode").querySelectorAll("button"), function (b) {
      b.classList.toggle("on", b.getAttribute("data-m") === state.scMode);
    });
    if (state.scMode === "sector") return drawSectors();
    var q = $("f-q").value.trim().toLowerCase(), sec = $("f-sector").value, my = parseFloat(String($("f-yield").value).replace(/,/g, ""));
    var rows = D.stocks.filter(function (s) {
      if (q && s.symbol.toLowerCase().indexOf(q) < 0 && (s.name || "").toLowerCase().indexOf(q) < 0) return false;
      if (sec && (s.sector || "").toUpperCase() !== sec.toUpperCase()) return false;
      if ($("f-mov").checked && !MV[s.symbol]) return false;
      if ($("f-sh").checked && !s.shariah) return false;
      if ($("f-watch").checked && !s.watch) return false;
      if ($("f-held").checked && !s.owned && !s.held) return false;
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
        cell(quote(s.symbol) ? "<b>" + num(quote(s.symbol).current, 2) + "</b> <span class='small " + sgn(quote(s.symbol).change_pct) + "'>" +
          pct((quote(s.symbol).change_pct || 0) / 100) + "</span>" : num(s.close, 2)) + cell(pct(s.r1m), sgn(s.r1m)) + cell(pct(s.r3m), sgn(s.r3m)) + cell(pct(s.r1y), sgn(s.r1y)) +
        cell(pct(s.vs_idx_3m), sgn(s.vs_idx_3m)) + cell(pctAbs(s.vol, 0)) + cell(s.sharpe == null ? "–" : s.sharpe.toFixed(2)) +
        cell(pctAbs((s.div || {}).yield)) + cell(s.pe == null ? "–" : num(s.pe, 1)) + cell(esc(s.trend)) + cell(num(s.score)) + cell(moverHtml(s.symbol), "l") + "</tr>";
    }).join("") + "</tbody>";
    $("sc-note").textContent = rows.length + " shares" + (rows.length > shown.length ? " (first 400 shown)" : "") +
      ". Tap a column to sort, tick boxes to compare (up to 6). " + (D.notes.illiquid_left_out ? D.notes.illiquid_left_out + " illiquid shares left out. " : "") +
      D.notes.face_value_note;
    $("f-compare").textContent = "Compare selected (" + state.compare.length + ")";
  }
  // Every listed share, grouped by sector, best day first inside each sector.
  function drawSectors() {
    var q = $("f-q").value.trim().toLowerCase(), sec = $("f-sector").value, my = parseFloat(String($("f-yield").value).replace(/,/g, ""));
    var all = marketRows();
    var rows = all.filter(function (r) {
      if (q && r.symbol.toLowerCase().indexOf(q) < 0 && (r.name || "").toLowerCase().indexOf(q) < 0) return false;
      if (sec && r.sector !== sec.toUpperCase()) return false;
      if ($("f-sh").checked && !r.shariah) return false;
      if ($("f-watch").checked && !r.watch) return false;
      if ($("f-held").checked && !r.owned) return false;
      if ($("f-mov").checked && !MV[r.symbol]) return false;
      if (!isNaN(my) && !((((bySym[r.symbol] || {}).div || {}).yield || 0) * 100 >= my)) return false;
      return true;
    });
    var groups = {};
    rows.forEach(function (r) { (groups[r.sector] = groups[r.sector] || []).push(r); });
    var names = Object.keys(groups).sort();
    var head = "<thead><tr><th class='l'>Stock</th><th class='l hide-m'>Name</th><th>Price</th><th>Change</th>" +
      "<th class='hide-m'>Volume</th><th class='l'>Mover</th><th>Score</th></tr></thead>";
    var body = names.map(function (n) {
      var g = groups[n].sort(function (a, b) {
        if (a.change == null && b.change == null) return a.symbol.localeCompare(b.symbol);
        if (a.change == null) return 1; if (b.change == null) return -1;
        return b.change - a.change;
      });
      var ch = g.filter(function (r) { return r.change != null; }).map(function (r) { return r.change; });
      var avg = ch.length ? ch.reduce(function (a, b) { return a + b; }, 0) / ch.length : null;
      var up = ch.filter(function (x) { return x > 0; }).length, dn = ch.filter(function (x) { return x < 0; }).length;
      return "<tr class='grp'><td colspan='7'>" + esc(n) + " <span class='muted small'>· " + g.length + " shares · average " +
        "<span class='" + sgn(avg) + "'>" + pct(avg, 2) + "</span> · ▲ " + up + " ▼ " + dn + "</span></td></tr>" +
        g.map(function (r) {
          var sym = bySym[r.symbol] ? symCell(Object.assign({}, bySym[r.symbol])) :
            "<b>" + esc(r.symbol) + "</b>" + (r.shariah ? '<span class="tag sh" title="KMI All Share (Shariah-compliant)">☪</span>' : "") +
            (r.owned ? '<span class="tag own">owned</span>' : "");
          return "<tr>" + cell(sym, "l") + cell(esc((r.name || "").slice(0, 30)), "l hide-m") +
            cell(r.price == null ? "–" : num(r.price, 2)) + cell(pct(r.change, 2), sgn(r.change)) +
            cell(r.volume == null ? "–" : num(r.volume), "hide-m") + cell(moverHtml(r.symbol), "l") +
            cell(r.score == null ? "<span class='muted' title='No price history on file, or too thinly traded to rank'>–</span>" : num(r.score)) + "</tr>";
        }).join("");
    }).join("");
    $("sc-table").innerHTML = head + "<tbody>" + (body || "<tr><td class='l muted' colspan='7'>No shares match.</td></tr>") + "</tbody>";
    var M = D.market || {};
    var src = all.some(function (r) { return r.source === "live"; }) ? "live prices" :
      M.as_of ? "the PSX market watch at " + M.as_of : "the last two closes on file";
    $("sc-note").textContent = rows.length + " of " + all.length + " listed shares in " + names.length + " sectors; the day's change from " + src + ". " +
      "Mover: top " + (M.movers_max || 10) + " gainers, losers and most traded among shares trading at least Rs " + num(M.movers_min_value || 5e6) +
      " that day, and each sector's best gainer. Score is blank for shares without price history on file or too thinly traded to rank." +
      (all.length < 100 ? " Only " + all.length + " shares on file: run pkdata.py universe and pkdata.py live (or the daily update) to list every share." : "");
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
      if ($("pf-equity")) $("pf-equity").parentNode.innerHTML = '<div class="empty">The value chart starts once the daily service has recorded two days (paper.py mark).</div>';
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

  // ---------------------------------------------------------------- my (real) portfolio
  // The price calculator: rupees if the price falls to the stop or rises to the target, after charges.
  function calcCells(c, held) {
    if (!c) return held ? cell("–") + cell("–") + cell("–") : cell("–") + cell("–") + cell("–") + cell("–");
    var lose = c.loss_at_stop ? "<span class='neg'>−" + pkr(c.loss_at_stop).replace("PKR ", "") + "</span>" : "<span class='muted'>stop hit</span>";
    var gain = held && !c.loss_at_stop ? "<span class='muted'>–</span>" :
      "<span class='" + sgn(c.gain_at_target) + "'>" + (c.gain_at_target >= 0 ? "+" : "−") + num(Math.abs(c.gain_at_target)) + "</span>";
    if (held) return cell(lose) + cell(gain) + cell("<span class='" + sgn(c.vs_cost_now) + "'>" + (c.vs_cost_now >= 0 ? "+" : "−") + num(Math.abs(c.vs_cost_now)) + "</span>");
    return cell(lose) + cell(gain) + cell(c.reward_risk == null ? "–" : c.reward_risk.toFixed(1) + " : 1") +
      cell(c.breakeven_win_rate == null ? "–" : pctAbs(c.breakeven_win_rate, 0));
  }

  function renderMine() {
    var M = D.mine;
    if (engineOn()) {
      renderRiskCard("mi-risk", $("v-mine"));
      if (canEdit()) renderEditor(); else serverNote();
      Array.prototype.forEach.call($("v-mine").children, function (c) { if (c.id !== "mi-edit" && c.id !== "mi-risk") c.style.display = M ? "" : "none"; });
      if (!M) return;
    }
    if (!M) {
      $("v-mine").innerHTML = '<div class="empty">No trades recorded yet. Add your broker and trades:<br><code>portfolio.py broker add NAME --commission-pct 0.15</code><br>' +
        '<code>portfolio.py buy SYMBOL QTY PRICE --broker NAME --date YYYY-MM-DD --commission X</code><br>or import a CSV: <code>portfolio.py import trades.csv</code></div>';
      return;
    }
    var HS = M.holdings.map(liveHold), delta = HS.reduce(function (t, x, i) { return t + (x.live ? x.value - (M.holdings[i].value || 0) : 0); }, 0);
    var S = Object.assign({}, M.summary, { value: M.summary.value + delta, unrealised: M.summary.unrealised + delta });
    var total = S.value + (S.cash || 0), anyLive = HS.some(function (x) { return x.live; });
    var gN = HS.filter(function (x) { return x.status === "GREEN"; }).length, rN = HS.filter(function (x) { return x.status === "RED"; }).length;
    var k = [["Market value" + (anyLive ? " (live)" : ""), pkr(S.value), "invested " + pkr(S.cost), ""],
             ["Green / red", gN + " / " + rN, "holdings in profit / at a loss", rN > gN ? "neg" : gN ? "pos" : ""],
             ["Unrealised", pkr(S.unrealised), S.cost ? pct(S.unrealised / S.cost) : "", sgn(S.unrealised)],
             ["Realised + dividends", pkr(S.realised + S.dividends), "dividends " + pkr(S.dividends), sgn(S.realised + S.dividends)],
             ["Costs paid", pkr(S.fees), "commission, taxes, fees", ""]];
    if (S.cash != null) k.push(["Cash", pkr(S.cash), pctAbs(S.cash / total, 0) + " of total", ""]);
    $("mi-kpis").innerHTML = k.map(function (x) {
      return '<div class="kpi"><div class="l">' + esc(x[0]) + '</div><div class="v ' + x[3] + '">' + esc(x[1]) + '</div><div class="s">' + esc(x[2]) + "</div></div>";
    }).join("");
    var nG = HS.filter(function (x) { return x.status === "GREEN"; }).length, nR = HS.filter(function (x) { return x.status === "RED"; }).length;
    $("mi-gr").innerHTML = "<tr><th class='l'>Stock</th><th class='l'>Status</th><th>P/L if sold now</th><th class='l'>Bought</th><th class='l'>Now</th><th class='hide-m'>Qty</th><th class='hide-m'>Paid (incl. charges)</th><th class='hide-m'>Worth now</th></tr>" +
      HS.map(function (hh) {
        var s = bySym[hh.symbol] || { symbol: hh.symbol }, lots = hh.lots || [];
        var now = hh.price == null ? "–" : "<b>" + num(hh.price, 2) + "</b> " + (hh.price_source === "live" ? "<span class='tag live'>live</span> " : "<span class='muted small'>close</span> ") +
          "<span class='small'>" + when(hh.price_date, hh.price_time) + "</span>";
        var row = "<tr class='row-" + (hh.status || "") + "'>" + cell(symCell(Object.assign({}, s, { held: false, owned: false })), "l") + cell(stBadge(hh.status), "l") +
          cell(plTxt(hh.net_pl, hh.net_pl_pct)) + cell("<b>" + num(hh.avg_cost, 2) + "</b> <span class='small'>" + when(hh.first_buy, hh.first_buy_time) + "</span>" +
            (lots.length > 1 ? " <span class='muted small'>(avg of " + lots.length + " buys)</span>" : ""), "l") +
          cell(now, "l") + cell(num(hh.qty), "hide-m") + cell(pkr(hh.cost), "hide-m") + cell(pkr(hh.value), "hide-m") + "</tr>";
        if (lots.length > 1) row += lots.map(function (l) {
          return "<tr class='lot'>" + cell("", "l") + cell(stBadge(l.status), "l") + cell(plTxt(l.net_pl, l.cost ? l.net_pl / l.cost : null)) +
            cell(num(l.qty) + " @ " + num(l.unit_cost, 2) + " · " + when(l.date, l.time) + " · " + esc(l.broker), "l") +
            cell("", "l") + cell(num(l.qty), "hide-m") + cell(pkr(l.cost), "hide-m") + cell(hh.price == null ? "–" : pkr(l.qty * hh.price), "hide-m") + "</tr>";
        }).join("");
        return row;
      }).join("");
    $("mi-grnote").innerHTML = "<b>" + nG + " in profit, " + nR + " at a loss.</b> GREEN / RED compares what you paid (price plus buying charges, with the date and time " +
      "you bought) with what selling at the price now would bring after selling charges. Now is the live price with its time when Live prices is on, " +
      "otherwise the last close (15:30 Pakistan time). Shares bought more than once show each purchase underneath.";
    var badge = { SELL: "<b class='neg'>SELL</b>", TRIM: "<b class='neg'>TRIM</b>", REVIEW: "<b>REVIEW</b>", HOLD: "HOLD", "NO DATA": "<span class='muted'>no data</span>" };
    $("mi-hold").innerHTML = "<tr><th class='l'>Stock</th><th class='l'>Action</th><th>Price</th><th>Stop</th><th>P/L if sold now</th><th class='l'>Why</th><th>Qty</th><th>Avg cost</th><th>Target</th><th>Value</th><th>At stop</th><th>At target</th><th>Sell today vs cost</th><th class='l'>PakistaniBulls says</th><th class='l'>Broker</th><th class='l'>Since</th></tr>" +
      HS.map(function (hh) {
        var s = bySym[hh.symbol] || { symbol: hh.symbol };
        var brokers = Object.keys(hh.brokers || {}).map(function (b) { return esc(b) + " " + num(hh.brokers[b]); }).join(", ");
        var why = esc(hh.why || "") + (hh.notes && hh.notes.length ? "<br><span class='muted small'>" + hh.notes.map(esc).join("<br>") + "</span>" : "");
        return "<tr>" + cell(symCell(Object.assign({}, s, { held: false, owned: false })), "l") + cell(badge[hh.action] || esc(hh.action), "l") +
          cell(num(hh.price, 2) + (hh.live ? " <span class='tag live' title='Live; end-of-day " + num(hh.eod_price, 2) + "'>live</span>" : "")) + cell(hh.stop == null ? "–" : num(hh.stop, 2) + (hh.stop_source === "yours" ? "*" : "")) +
          cell(stBadge(hh.status) + " <span class='" + sgn(hh.net_pl) + "'>" + pct(hh.net_pl_pct) + "</span>") + "<td class='l' style='white-space:normal;min-width:200px'>" + why + "</td>" +
          cell(num(hh.qty)) + cell(num(hh.avg_cost, 2)) + cell(hh.target == null ? "–" : num(hh.target, 2)) + cell(pkr(hh.value)) +
          calcCells(hh.calc, true) + theirsCell(hh.theirs) + cell(brokers, "l") + cell(esc(hh.first_buy), "l") + "</tr>";
      }).join("");
    var MF = M.funds || [];
    $("mi-fundcard").style.display = MF.length ? "" : "none";
    $("mi-funds").innerHTML = "<tr><th class='l'>Fund</th><th class='l'>Action</th><th>Value</th><th>P/L</th><th class='l'>Why</th><th>Units</th><th>NAV</th><th class='l'>Category</th></tr>" +
      MF.map(function (f) {
        return "<tr>" + cell("<b>" + esc(f.fund) + "</b>", "l") + cell(f.action === "REVIEW" ? "<b>REVIEW</b>" : esc(f.action || "–"), "l") +
          cell(pkr(f.value)) + cell(pct(f.unrealised_pct), sgn(f.unrealised_pct)) +
          "<td class='l' style='white-space:normal;min-width:200px'>" + esc(f.why || "") + "</td>" + cell(num(f.units, 2)) +
          cell(f.nav == null ? "–" : num(f.nav, 4) + " <span class='muted small'>" + esc(f.nav_date || "") + "</span>") + cell(esc(f.category || ""), "l") + "</tr>";
      }).join("");
    var TK = M.tickets || [];
    $("mi-ticketcard").style.display = TK.length ? "" : "none";
    $("mi-tickets").innerHTML = "<tr><th class='l'>Stock</th><th class='l'>Side</th><th class='l'>Order</th><th>Qty</th><th>Trigger</th><th>Limit</th><th class='l'>Broker</th><th class='l'>Valid</th></tr>" +
      TK.map(function (t) {
        return "<tr>" + cell("<b>" + esc(t.symbol) + "</b>", "l") + cell("<b class='" + (t.side === "BUY" ? "pos" : "neg") + "'>" + esc(t.side) + "</b>", "l") +
          cell(esc(t.type), "l") + cell(num(t.qty)) + cell(t.trigger ? num(t.trigger, 2) : "") + cell(t.limit ? num(t.limit, 2) : (t.type === "market" ? "market" : "")) +
          cell(esc(t.broker || ""), "l") + cell(esc(t.validity), "l") + "</tr>";
      }).join("");
    var st = M.settings;
    $("mi-note").textContent = "Average cost includes commission, taxes and fees. Stop = " + st.stop_atr_mult + " × the 14-day average daily move, " +
      Math.round(st.min_stop_pct * 100) + "–" + Math.round(st.max_stop_pct * 100) + "% below entry, trailing up; * = a stop you set. Prices are " + (anyLive ? "live where marked (the actions are from the end-of-day run, except a live price at or below the stop)" : "the last close") + ". At stop / at target: rupees, after estimated broker charges, " +
      "if the price falls to the stop or rises to the target from here; sell today vs cost: what selling at that price would make or lose against what you paid.";
    $("mi-buy").innerHTML = "<tr><th class='l'>Stock</th><th>Entry</th><th>Stop</th><th>Target</th><th>Qty</th><th>Cost incl. fees</th><th>Lose at stop</th><th>Gain at target</th><th>Reward : risk</th><th>Break-even win rate</th><th class='l'>PakistaniBulls says</th><th class='l'>Why it passed</th></tr>" +
      (M.buy_ideas.length ? M.buy_ideas.map(function (i) {
        var s = Object.assign({}, bySym[i.symbol] || { symbol: i.symbol, shariah: i.shariah }, { held: false });
        var x = quote(i.symbol), lv = "";
        if (x) {
          i = Object.assign({}, i, { calc: liveCalc(i.calc, x.current, false) });
          lv = "<br><span class='small'><span class='tag live'>live</span> " + num(x.current, 2) + " " +
            (x.current <= i.stop ? "<b class='neg'>at or below the stop: skip</b>" :
             x.current > i.entry * 1.03 ? "<span class='muted'>up " + pct(x.current / i.entry - 1) + " since the signal: re-check the size</span>" : "") + "</span>";
        }
        return "<tr>" + cell(symCell(s), "l") + cell(num(i.entry, 2) + lv) + cell(num(i.stop, 2) + " <span class='muted small'>" + pct(i.stop_pct) + "</span>") +
          cell(num(i.target, 2)) + cell(i.qty ? num(i.qty) : "–") + cell(i.qty ? pkr(i.cost) : "–") + calcCells(i.calc, false) + theirsCell(i.theirs) +
          "<td class='l' style='white-space:normal;min-width:220px'>" + esc(i.strategy) + " " + esc(JSON.stringify(i.params || {})) +
          ": out-of-sample " + pct(i.oos_cagr) + " a year vs buy-and-hold " + pct(i.oos_buyhold_cagr) + "</td></tr>";
      }).join("") : "<tr><td class='l muted' colspan='11'>No buy ideas: nothing passed every check, or portfolio.py advise has not run yet.</td></tr>");
    $("mi-buynote").textContent = (M.buy_note ? "No new buys: " + M.buy_note + ". " : "") + (M.advice_date ? (SOURCE === "feed" ? "Backtested by the site's feed run of " : "From the run of ") + M.advice_date + ". " : "") +
      (SOURCE === "feed" ? "" : M.second_opinion ? "PakistaniBulls: their candlestick-pattern signals (read " + M.second_opinion + "), a different method shown for comparison, for your own use only. " :
        "Add a second opinion: signals.py pakistanibulls --from-file PAGE.html. ") +
      "Size risks " + (st.risk_per_trade * 100).toFixed(1) + "% of your capital between entry and stop, at most " + Math.round(st.max_position_pct * 100) +
      "% in one stock. Rule-based suggestions from past prices, not investment advice; nothing is ordered for you.";
    var alloc = {};
    HS.forEach(function (hh) { var key = hh.sector || "Unknown sector"; alloc[key] = (alloc[key] || 0) + (hh.value || hh.cost || 0); });
    (M.funds || []).forEach(function (f) { alloc["Mutual funds"] = (alloc["Mutual funds"] || 0) + (f.value || f.cost || 0); });
    if (S.cash > 0) alloc.Cash = S.cash;
    var ent = Object.keys(alloc).map(function (k) { return [k, alloc[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
    if (ent.length > 6) { var rest = ent.slice(5).reduce(function (t, e) { return t + e[1]; }, 0); ent = ent.slice(0, 5).concat([["Other", rest]]); }
    chart("mi-alloc", { type: "doughnut", data: { labels: ent.map(function (e) { return e[0]; }),
      datasets: [{ data: ent.map(function (e) { return Math.round(e[1]); }), backgroundColor: ent.map(function (e, i) { return css(SLOTS[i]); }),
        borderColor: css("--surface"), borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, cutout: "62%",
        plugins: { legend: { position: window.innerWidth < 600 ? "bottom" : "right", labels: { color: css("--text-2"), boxWidth: 12, usePointStyle: true } },
          tooltip: { callbacks: { label: function (c) { return c.label + ": " + pkr(c.raw) + " (" + pctAbs(c.raw / total, 0) + ")"; } } } } } });
    var F = M.fees || [];
    chart("mi-fees", { type: "bar", data: { labels: F.map(function (f) { return f.broker; }),
      datasets: [["Commission", "commission", 0], ["Taxes", "taxes", 1], ["Other fees", "other", 2]].map(function (d) {
        return { label: d[0], data: F.map(function (f) { return Math.round(f[d[1]]); }), backgroundColor: css(SLOTS[d[2]]), borderRadius: 4, borderSkipped: false };
      }) },
      options: baseOpts({ scales: { x: { stacked: true, ticks: { color: css("--text-2") }, grid: { display: false }, border: { display: false } },
        y: { stacked: true, ticks: { color: css("--text-2") }, grid: { color: css("--grid") }, border: { display: false } } } }) });
    if ($("mi-fees")) $("mi-fees").parentNode.style.height = "200px";
    $("mi-feet").innerHTML = "<tr><th class='l'>Broker</th><th>Trades</th><th>Turnover</th><th>Total costs</th><th>Cost rate</th></tr>" +
      F.map(function (f) {
        var t = f.commission + f.taxes + f.other;
        return "<tr>" + cell(esc(f.broker) + (f.estimated ? " <span class='tag' title='commission estimated from the schedule on " + f.estimated + " trades'>est.</span>" : ""), "l") +
          cell(num(f.trades)) + cell(pkr(f.turnover)) + cell(pkr(t)) + cell(f.turnover ? (100 * t / f.turnover).toFixed(3) + "%" : "–") + "</tr>";
      }).join("");
    var sales = (M.sales || []).slice().reverse();
    $("mi-sales").innerHTML = "<tr><th class='l'>Date</th><th class='l'>Stock</th><th class='l'>Broker</th><th>Qty</th><th>P/L</th><th>%</th><th>Days</th></tr>" +
      (sales.length ? sales.map(function (x) {
        return "<tr>" + cell(esc(x.date), "l") + cell("<b>" + esc(x.symbol) + "</b>", "l") + cell(esc(x.broker), "l") + cell(num(x.qty)) +
          cell(pkr(x.pnl), sgn(x.pnl)) + cell(pct(x.pnl_pct), sgn(x.pnl_pct)) + cell(num(x.avg_days_held)) + "</tr>";
      }).join("") : "<tr><td class='l muted' colspan='7'>No sales yet.</td></tr>");
    var dv = (M.dividends || []).slice().reverse();
    $("mi-divs").innerHTML = dv.length ? dv.map(function (d) {
      return "<li><span><b>" + esc(d.symbol) + "</b>" + (d.estimated ? " <span class='tag'>estimated</span>" : "") + "</span><span>" + pkr(d.net) +
        " <span class='muted small'>" + esc(d.date) + "</span></span></li>";
    }).join("") : "<li class='muted'>None recorded.</li>";
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

  // ---------------------------------------------------------------- risk & SIP
  function sipProject(m, years, rate, step, lump) {
    var rm = Math.pow(1 + rate, 1 / 12) - 1, v = lump, inv = lump, rows = [];
    for (var y = 1; y <= years; y++) {
      for (var k = 0; k < 12; k++) { v = (v + m) * (1 + rm); inv += m; }
      rows.push({ year: y, invested: inv, value: v });
      m *= 1 + step;
    }
    return rows;
  }
  function sipNeed(target, years, rate, step, lump) {
    var lo = 0, hi = Math.max(target, 1);
    if (sipProject(0, years, rate, step, lump).slice(-1)[0].value >= target) return 0;
    for (var i = 0; i < 80; i++) { var mid = (lo + hi) / 2; if (sipProject(mid, years, rate, step, lump).slice(-1)[0].value >= target) hi = mid; else lo = mid; }
    return hi;
  }
  function drawSip() {
    var m = nv("sp-m"), y = Math.max(1, Math.min(60, nv("sp-y") || 1)), r = nv("sp-r") / 100,
        s = nv("sp-s") / 100, l = nv("sp-l"), inf = nv("sp-i") / 100, g = nv("sp-g");
    var rows = sipProject(m, y, r, s, l), last = rows[rows.length - 1];
    var lo = sipProject(m, y, r - 0.03, s, l).slice(-1)[0].value, hi = sipProject(m, y, r + 0.03, s, l).slice(-1)[0].value;
    var k = [["Invested", pkr(last.invested), y + " years", ""], ["Could grow to", pkr(last.value), "gain " + pkr(last.value - last.invested), "pos"],
             ["Range (±3 points)", pkr(lo) + " – " + pkr(hi), "returns rarely follow the plan", ""]];
    if (inf) k.push(["In today's rupees", pkr(last.value / Math.pow(1 + inf, y)), "after " + (inf * 100).toFixed(1) + "% inflation", ""]);
    if (g) k.push(["Monthly for your goal", pkr(sipNeed(g, y, r, s, l)), "to reach " + pkr(g), ""]);
    $("sp-kpis").innerHTML = k.map(function (x) {
      return '<div class="kpi"><div class="l">' + esc(x[0]) + '</div><div class="v ' + x[3] + '">' + esc(x[1]) + '</div><div class="s">' + esc(x[2]) + "</div></div>";
    }).join("");
    chart("sp-chart", { type: "line", data: { labels: rows.map(function (x) { return "Year " + x.year; }),
      datasets: [{ label: "Value", data: rows.map(function (x) { return Math.round(x.value); }), borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 2 },
                 { label: "Invested", data: rows.map(function (x) { return Math.round(x.invested); }), borderColor: css("--muted"), backgroundColor: css("--muted"), borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0 }] },
      options: baseOpts({ interaction: { mode: "index", intersect: false },
        plugins: Object.assign(baseOpts().plugins, { tooltip: Object.assign(baseOpts().plugins.tooltip, { callbacks: { label: function (c) { return c.dataset.label + ": " + pkr(c.raw); } } }) }),
        scales: { x: { ticks: { color: css("--text-2") }, grid: { display: false }, border: { display: false } },
                  y: { ticks: { color: css("--text-2"), callback: function (v) { return v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(0) + "k" : v; } }, grid: { color: css("--grid") }, border: { display: false } } } }) });
  }
  function renderRisk() {
    var R = D.risk;
    if (!R) { $("v-risk").innerHTML = '<div class="empty">Rebuild the dashboard to see risk and SIP.</div>'; return; }
    var P = R.portfolio;
    if (engineOn()) renderRiskCard("rk-risk", $("v-risk"));
    var k = [["Risk profile", (R.profile || "").replace("_", " "), engineOn() ? "change it above, or take the quiz" : "risk.py quiz to change", ""]];
    if (P && P.total) {
      k.push(["If every stop hit", pkr(P.open_risk), pctAbs(P.open_risk_pct) + " of portfolio; budget " + pkr(P.risk_budget), P.open_risk > P.risk_budget ? "neg" : ""]);
      if (P.var_1m_95 != null) k.push(["A bad month (95%)", pkr(P.var_1m_95), "value-at-risk on your shares", ""]);
      if (P.volatility != null) k.push(["Volatility", pctAbs(P.volatility), "beta " + (P.beta == null ? "n/a" : P.beta.toFixed(2)), ""]);
      if (P.effective_holdings) k.push(["Diversification", P.effective_holdings.toFixed(1), "effective positions", ""]);
    }
    $("rk-kpis").innerHTML = k.map(function (x) {
      return '<div class="kpi"><div class="l">' + esc(x[0]) + '</div><div class="v ' + x[3] + '" style="text-transform:capitalize">' + esc(x[1]) + '</div><div class="s">' + esc(x[2]) + "</div></div>";
    }).join("");
    var buckets = ["equity", "fixed_income", "money_market"], tgt = R.allocation_target || {};
    var now = (P && P.allocation_pct) || {};
    chart("rk-alloc", { type: "bar", data: { labels: buckets.map(function (b) { return b.replace("_", " "); }),
      datasets: [{ label: "Now", data: buckets.map(function (b) { return +((now[b] || 0) * 100).toFixed(1); }), backgroundColor: css("--s1"), borderRadius: 4, borderSkipped: false },
                 { label: "Target", data: buckets.map(function (b) { return +((tgt[b] || 0) * 100).toFixed(1); }), backgroundColor: css("--s2"), borderRadius: 4, borderSkipped: false }] },
      options: baseOpts({ scales: { x: { ticks: { color: css("--text-2") }, grid: { display: false }, border: { display: false } },
        y: { beginAtZero: true, max: 100, ticks: { color: css("--text-2"), callback: function (v) { return v + "%"; } }, grid: { color: css("--grid") }, border: { display: false } } } }) });
    var flags = (P && P.flags) || [];
    $("rk-flags").innerHTML = P && P.total ? (flags.length ? flags.map(function (f) { return "<li><span>" + esc(f) + "</span></li>"; }).join("") :
      "<li class='muted'>Nothing flagged: within your profile's limits.</li>") : "<li class='muted'>Record your holdings to see your own allocation.</li>";
    $("rk-settings").innerHTML = "<tr><th class='l'>Setting</th><th>Value</th><th class='l'>What it does</th></tr>" +
      (R.settings || []).map(function (s) {
        return "<tr>" + cell("<code>" + esc(s.key) + "</code>", "l") + cell(esc(s.value)) + "<td class='l' style='white-space:normal'>" + esc(s.about) + "</td></tr>";
      }).join("");
    if (!rendered.risk) {
      $("sp-r").value = ((R.sip && R.sip.rate) * 100 || 12).toFixed(1);
      ["sp-m", "sp-y", "sp-r", "sp-s", "sp-l", "sp-i", "sp-g"].forEach(function (id) { $(id).oninput = drawSip; });
    }
    $("sp-note").textContent = "Starting return: " + (R.sip ? R.sip.basis : "your choice") +
      ". Invested at the start of each month, compounded monthly; before taxes, loads and charges. A projection, not a promise.";
    drawSip();
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

  // ---------------------------------------------------------------- data freshness
  // Every number on the page is calculated from the data in data.json. Before using it, the page
  // says how old it is and asks whether to fetch fresh data; the answer can be remembered in a
  // cookie (pkm_refresh = ask | stored | auto). Fetching from the page needs the server to have
  // been started with --allow-refresh; otherwise the page says which command to run.
  function cookie(k, v) {
    try {
      if (v === undefined) {
        var m = document.cookie.match(new RegExp("(?:^|; )" + k + "=([^;]*)"));
        return m ? decodeURIComponent(m[1]) : store(k);
      }
      document.cookie = k + "=" + encodeURIComponent(v) + "; Max-Age=31536000; Path=/; SameSite=Strict" +
        (location.protocol === "https:" ? "; Secure" : "");
      store(k, v);  // a file:// page often can't keep cookies
    } catch (e) { return null; }
  }
  function ageDays(d) {
    if (!d) return null;
    var t = new Date(d + "T00:00:00");
    return isNaN(t) ? null : Math.max(0, Math.floor((Date.now() - t.getTime()) / 864e5));
  }
  var api = null, polling = null;
  function today() { var d = new Date(); return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
  function dataLine() {
    var F = D.freshness || {}, age = ageDays(F.prices_as_of);
    return "Data: prices to <b>" + esc(F.prices_as_of || "–") + "</b>" +
      (age != null ? " (" + (age === 0 ? "today" : age + " day" + (age === 1 ? "" : "s") + " old") + ")" : "") +
      (F.mufap_as_of ? " · MUFAP " + esc(F.mufap_as_of) : "") + " · built " + esc(D.generated);
  }
  function freshness() {
    var el = $("fresh"), F = D.freshness || {}, age = ageDays(F.prices_as_of);
    var mode = cookie("pkm_refresh") || "ask", stale = age == null || age >= 1;
    var can = api && api.refresh, html = dataLine();
    el.hidden = false;
    el.className = "fresh";
    el.onclick = function (e) { if (e.target && e.target.id === "f-reload") location.reload(); };
    if (api && api.running) {
      el.className = "fresh stale";
      el.innerHTML = html + " · <b>fetching fresh data…</b> (started " + esc(api.started) + "; the page reloads when done)";
      return poll();
    }
    if (api && api.ok === false && api.finished) {
      html += " · <span class='neg'>the last fetch (" + esc(api.finished) + ") had problems: " +
        esc((api.tail || []).join("; ") || "unknown") + " (details: logs/refresh.log in the data folder)</span> <a id='f-reload'>reload</a>";
    }
    if (can && mode === "auto" && stale && store("autoFetched") !== today() && !(api && api.cooldown)) {
      store("autoFetched", today());
      return refresh();
    }
    if (mode === "ask" && stale) {
      el.className = "fresh stale";
      el.innerHTML = html + ". " + (can
        ? "Fetch fresh data before you use these numbers? <button class='btn' id='f-go'>Fetch now</button> " +
          "<button class='btn ghost' id='f-keep'>Use stored data</button>"
        : "This page can't fetch by itself: run <code>python3 pkm.py daily</code> (menu 11), or start the server with " +
          "<code>dashboard.py serve --allow-refresh</code>. <button class='btn ghost' id='f-keep'>Use stored data</button>") +
        " <label class='ck small'><input type='checkbox' id='f-remember'> remember my choice</label>";
      var rem = function () { return $("f-remember").checked; };
      if ($("f-go")) $("f-go").onclick = function () { if (rem()) cookie("pkm_refresh", "auto"); refresh(); };
      $("f-keep").onclick = function () { if (rem()) cookie("pkm_refresh", "stored"); el.className = "fresh"; el.innerHTML = dataLine() + " · using stored data"; };
      return;
    }
    el.innerHTML = html + (can ? " · <a id='f-now'>Fetch now</a>" : "") +
      (mode !== "ask" ? " · remembered: " + (mode === "auto" ? "fetch automatically when stale" : "use stored data") +
        " (<a id='f-reset'>ask me again</a>)" : "");
    if ($("f-now")) $("f-now").onclick = refresh;
    if ($("f-reset")) $("f-reset").onclick = function () { cookie("pkm_refresh", "ask"); freshness(); };
  }
  function refresh() {
    var el = $("fresh");
    el.className = "fresh stale";
    el.innerHTML = dataLine() + " · <b>asking the server to fetch fresh data…</b>";
    fetch("api/refresh", { method: "POST", headers: { "X-PKM-Refresh": "1" }, credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        if (!x.ok) { el.innerHTML = dataLine() + " · <span class='neg'>" + esc(x.j.error || "refresh refused") + "</span>"; return; }
        api = x.j; freshness();
      })
      .catch(function (e) { el.innerHTML = dataLine() + " · <span class='neg'>could not reach the server: " + esc(e.message) + "</span>"; });
  }
  function poll() {
    if (polling) return;
    polling = setInterval(function () {
      fetch("api/status", { cache: "no-store", credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (st) {
        api = st;
        if (st.running) return;
        clearInterval(polling); polling = null;
        if (st.ok) location.reload(); else freshness();
      }).catch(function () {});
    }, 3000);
  }
  function checkFreshness() {
    if (window.PKM_DATA || location.protocol === "file:") { liveBar(); return freshness(); }
    fetch("api/status", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (st) { api = st; freshness(); liveBar(); if (st && st.live && liveOn()) liveTick(); })
      .catch(function () { freshness(); });
  }

  // ---------------------------------------------------------------- live prices
  // Optional: the server's /api/live returns the PSX portal's market watch (cached 30 s on the
  // server). With Live switched on, prices refresh once a minute while the market is open, and the
  // holdings, buy ideas, price calculator and screener use them. Off by default; the choice is
  // kept in the pkm_live cookie.
  var LV = null, liveTimer = null, liveErr = null;
  function liveOn() { return cookie("pkm_live") === "1"; }
  function quote(sym) { return LV && liveOn() ? (LV.quotes || {})[sym] || null : null; }
  function liveBar() {
    var el = $("livebar");
    if (!(api && api.live)) {
      if (window.PKM_DATA || location.protocol === "file:" || (api && !api.live)) {
        el.hidden = false;
        el.innerHTML = "Live prices: " + (window.PKM_DATA || location.protocol === "file:"
          ? "not in " + (SOURCE === "device" ? "this browser copy" : "the one-file version") + "; open the dashboard from its server (<code>dashboard.py serve --allow-live</code>)."
          : "off on this server (start it with <code>--allow-live</code>).") +
          " From the command line: <code>python3 pkdata.py live</code>, or <code>--live</code> on any advice.";
      }
      return;
    }
    el.hidden = false;
    var on = liveOn();
    el.innerHTML = "<label class='ck'><input type='checkbox' id='lv-on'" + (on ? " checked" : "") + "> <b>Live prices</b></label> " +
      (on ? (LV ? "<span class='dot-live'></span>PSX at " + esc(LV.fetched.slice(11, 16)) + " · " +
        (LV.market_open ? "market open, updates every minute" : "market closed: last trades") +
        " · <a id='lv-now'>update now</a>" : "loading…") +
        (liveErr ? " · <span class='neg'>" + esc(liveErr) + "</span>" : "") +
        "<span class='muted small'> · the portal can lag the exchange; orders go through your broker</span>"
        : "<span class='muted'>off: everything uses the end-of-day data above</span>");
    $("lv-on").onchange = function () {
      cookie("pkm_live", this.checked ? "1" : "0");
      if (this.checked) liveTick(); else { clearTimeout(liveTimer); liveTimer = null; liveBar(); redrawLive(); }
    };
    if ($("lv-now")) $("lv-now").onclick = liveTick;
  }
  function liveTick() {
    clearTimeout(liveTimer); liveTimer = null;
    if (!liveOn()) return;
    fetch("api/live", { headers: { "X-PKM-Live": "1" }, cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        if (!x.ok) { liveErr = x.j.error || "live prices failed"; }
        else { LV = x.j; liveErr = x.j.error ? "PSX didn't answer the last try; showing " + LV.fetched.slice(11, 16) : null; }
      })
      .catch(function (e) { liveErr = "could not reach the server: " + e.message; })
      .then(function () {
        liveBar(); redrawLive();
        if (liveOn() && (!LV || LV.market_open) && document.visibilityState !== "hidden") liveTimer = setTimeout(liveTick, 60000);
      });
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && liveOn() && api && api.live && !liveTimer) liveTick();
  });
  function currentView() { var b = $("tabs").querySelector("button.on"); return b ? b.getAttribute("data-v") : "overview"; }
  function redrawLive() {
    var v = currentView();
    if (v === "overview") drawLiveCard(); else if (v === "screener") drawScreener(); else if (v === "mine") renderMine();
  }
  function drawLiveCard() {
    var card = $("ov-livecard");
    if (!card) return;
    if (!(LV && liveOn())) { card.hidden = true; return; }
    var syms = D.stocks.filter(function (s) { return s.owned || s.watch || s.held || state.compare.indexOf(s.symbol) >= 0; })
      .map(function (s) { return s.symbol; });
    card.hidden = false;
    $("ov-live").innerHTML = "<tr><th class='l'>Stock</th><th>Live</th><th>Change</th><th>vs last close on file</th><th class='hide-m'>High</th><th class='hide-m'>Low</th><th>Volume</th></tr>" +
      syms.map(function (sym) {
        var s = bySym[sym], x = quote(sym);
        if (!x) return "<tr>" + cell(symCell(s), "l") + "<td colspan='6' class='l muted'>not quoted</td></tr>";
        var vs = s.close ? x.current / s.close - 1 : null, ch = x.change_pct == null ? null : x.change_pct / 100;
        return "<tr>" + cell(symCell(s), "l") + cell("<b>" + num(x.current, 2) + "</b>") + cell(pct(ch, 2), sgn(ch)) + cell(pct(vs, 2), sgn(vs)) +
          cell(num(x.high, 2), "hide-m") + cell(num(x.low, 2), "hide-m") + cell(num(x.volume)) + "</tr>";
      }).join("");
    $("ov-livenote").textContent = "PSX data portal at " + LV.fetched + " (Pakistan time). Change is against the previous close; " +
      "\"vs last close on file\" is against the end-of-day data the rankings use.";
  }
  // Recalculate the price calculator from a new price, keeping the charges it estimated.
  function liveCalc(c, px, held) {
    if (!c || px == null) return c;
    var n = Object.assign({}, c), k = c.qty;
    var feeStop = c.loss_at_stop ? c.loss_at_stop - k * (c.price - c.stop) : 0;
    var feeTgt = k * (c.target - c.price) - c.gain_at_target;
    n.price = px; n.value = k * px;
    n.loss_at_stop = px > c.stop ? k * (px - c.stop) + (feeStop || 0) : 0;
    n.gain_at_target = k * (c.target - px) - feeTgt;
    n.reward_risk = n.loss_at_stop > 0 ? n.gain_at_target / n.loss_at_stop : null;
    n.breakeven_win_rate = n.loss_at_stop > 0 && n.gain_at_target > 0 ? n.loss_at_stop / (n.loss_at_stop + n.gain_at_target) : null;
    if (held && c.vs_cost_now != null) n.vs_cost_now = c.vs_cost_now + k * (px - c.price);
    return n;
  }
  function theirsCell(t) {
    if (!t) return cell("<span class='muted'>–</span>", "l");
    var col = t.stance === "long" ? "pos" : t.stance === "short" ? "neg" : "";
    var ag = t.agreement || "";
    return cell("<b class='" + col + "'>" + esc(t.signal) + "</b> <span class='muted small'>" + esc(t.text.replace(t.signal, "").replace(/^, /, "")) + "</span>" +
      (ag ? "<br><span class='small " + (ag.indexOf("disagree") === 0 ? "neg" : ag.indexOf("agree") === 0 ? "pos" : "") + "'>" + esc(ag) + "</span>" : ""), "l");
  }
  function stOf(v) { return v == null ? null : v > 0.005 ? "GREEN" : v < -0.005 ? "RED" : "FLAT"; }
  function stBadge(s) { return s ? "<span class='st " + s + "'>" + (s === "GREEN" ? "▲ GREEN" : s === "RED" ? "▼ RED" : "= FLAT") + "</span>" : "–"; }
  function when(d, t) { return d ? esc(d) + (t ? " " + esc(t) : "") : "–"; }
  function plTxt(v, p) { return v == null ? "–" : "<span class='" + sgn(v) + "'>" + (v >= 0 ? "+" : "−") + num(Math.abs(v)) + (p == null ? "" : " (" + pct(p) + ")") + "</span>"; }
  function liveHold(hh) {
    var x = quote(hh.symbol);
    if (!x || hh.price == null) return hh;
    var px = x.current, n = Object.assign({}, hh, { price: px, live: true, eod_price: hh.price });
    n.value = hh.qty * px;
    n.unrealised_pct = hh.cost ? n.value / hh.cost - 1 : null;
    n.calc = liveCalc(hh.calc, px, true);
    var d = px - hh.price;
    if (hh.net_pl != null) {
      n.net_pl = hh.net_pl + hh.qty * d; n.net_pl_pct = hh.cost ? n.net_pl / hh.cost : null; n.status = stOf(n.net_pl);
      n.lots = (hh.lots || []).map(function (l) {
        var m = Object.assign({}, l); if (l.net_pl != null) { m.net_pl = l.net_pl + l.qty * d; m.status = stOf(m.net_pl); } return m;
      });
    }
    n.price_source = "live"; n.price_date = LV.date; n.price_time = (LV.fetched || "").slice(11, 16);
    if (hh.stop != null && px <= hh.stop && hh.action !== "SELL") {
      n.action = "SELL"; n.why = "live price " + num(px, 2) + " is at or below the stop " + num(hh.stop, 2) + " (end-of-day advice: " + (hh.action || "–") + ")";
    }
    return n;
  }

  // ---------------------------------------------------------------- boot
  var BLANK_TABS = ["mine", "risk", "data"];
  function boot(data) {
    D = data;
    D.stocks.forEach(function (s) { bySym[s.symbol] = s; });
    $("meta").textContent = SOURCE === "blank" ? "Your portfolio · no market data loaded" :
      (SOURCE === "sample" ? "Sample data · " : "Built " + D.generated + " · ") + D.stocks.length +
      " shares (" + D.scope + ") · prices to " + (D.calendar[D.calendar.length - 1] || "–");
    Array.prototype.forEach.call($("tabs").querySelectorAll("[data-v]"), function (b) {
      b.hidden = SOURCE === "blank" && BLANK_TABS.indexOf(b.getAttribute("data-v")) < 0;
    });
    if (SOURCE === "blank") { blankBar(); show("mine"); return; }
    if (SOURCE === "sample" || D.sample) sampleBar(); else if (SOURCE === "feed") feedBar(); else checkFreshness();
    var fromHash = (location.hash.match(/compare=([^&]*)/) || [])[1];
    var saved = fromHash ? decodeURIComponent(fromHash).split(",") : (store("compare") || []);
    var slots = store("slots") || {};
    saved.forEach(function (s) { if (bySym[s] && slots[s]) state.slots[s] = slots[s]; addCompare(s); });
    if (!state.compare.length) D.stocks.filter(function (s) { return s.owned || s.held || s.watch; }).slice(0, 3).forEach(function (s) { addCompare(s.symbol); });
    show(fromHash ? "compare" : (store("view") || "overview"));
  }
  // ---------------------------------------------------------------- your data on this device
  // The GitHub Pages copy has no data of its own (market data and ledgers never go in the repo).
  // You load the data.json that `dashboard.py build` writes (or the one-file dashboard.html);
  // it is kept in this browser's IndexedDB and never leaves the device.
  var SOURCE = "server", LOADED_AT = null;
  var IDB = {
    open: function () {
      return new Promise(function (res, rej) {
        var r = indexedDB.open("psx-dashboard", 1);
        r.onupgradeneeded = function () { r.result.createObjectStore("kv"); };
        r.onsuccess = function () { res(r.result); }; r.onerror = function () { rej(r.error); };
      });
    },
    get: function (k) { return IDB.open().then(function (db) { return new Promise(function (res, rej) { var q = db.transaction("kv").objectStore("kv").get(k); q.onsuccess = function () { res(q.result); }; q.onerror = function () { rej(q.error); }; }); }); },
    set: function (k, v) { return IDB.open().then(function (db) { return new Promise(function (res, rej) { var tx = db.transaction("kv", "readwrite"); tx.objectStore("kv").put(v, k); tx.oncomplete = function () { res(); }; tx.onerror = function () { rej(tx.error); }; }); }); },
    del: function (k) { return IDB.open().then(function (db) { return new Promise(function (res) { var tx = db.transaction("kv", "readwrite"); tx.objectStore("kv").delete(k); tx.oncomplete = function () { res(); }; }); }); }
  };
  function parseDataFile(text) {
    text = String(text);
    var t = text.replace(/^\uFEFF/, "").trim();
    if (t.charAt(0) === "{") return JSON.parse(t);
    var m = text.match(/window\.PKM_DATA=(\{[\s\S]*?\});<\/script>/);   // the one-file dashboard.html
    if (m) return JSON.parse(m[1].replace(/<\\\//g, "</"));
    throw new Error("not a dashboard data file");
  }
  function validData(d) { return d && Array.isArray(d.stocks) && Array.isArray(d.calendar); }
  function pickFile() {
    var inp = document.createElement("input");
    inp.type = "file"; inp.accept = ".json,.html,application/json,text/html";
    inp.onchange = function () {
      var f = inp.files && inp.files[0];
      if (!f) return;
      f.text().then(function (txt) {
        var d = parseDataFile(txt);
        if (!validData(d)) throw new Error("this file has no dashboard data");
        return IDB.set("data", { data: d, name: f.name, loaded: new Date().toISOString() });
      }).then(function () { sampleFlag(false); location.reload(); })
        .catch(function (e) { alert("Couldn't load that file: " + e.message); });
    };
    inp.click();
  }
  function howToMake() {
    return '<ol><li>On your phone (Termux) or computer, run <code>python3 psx-mufap/scripts/dashboard.py build</code>. ' +
      'It writes <code>dashboard/data.json</code> in your data folder. The daily update also writes the one-file <code>dashboard.html</code>; either works.</li>' +
      '<li>Tap <b>Load data file</b> and pick it. It is stored only in this browser, on this device.</li>' +
      '<li>Load a newer file whenever you want fresher numbers.</li></ol>';
  }
  function showLoader(reason) {
    $("tabs").hidden = true; document.querySelector("main").hidden = true;
    var L = $("loader"); L.hidden = false;
    L.innerHTML = '<div class="card"><h2>Your PSX &amp; MUFAP desk</h2><p>Rankings, compare, your portfolio with sell, trim or hold, ' +
      "dividends, MUFAP funds and a SIP planner, in one place.</p>" + privacyNote() +
      '<div class="row-actions"><button class="btn big" id="ld-blank">Start my portfolio</button></div>' +
      '<p class="small muted" style="margin-top:6px">A clean slate: add your shares, mutual funds, cash and dividends straight away. ' +
      "Prices come from your trades (or what you type) until you load market data.</p>" +
      '<h2 style="margin-top:18px">Or load your data</h2>' +
      '<p class="muted">This copy of the dashboard has no data of its own: PSX market data and your ledger never go in the repo. ' +
      "Load your own file for the full desk (rankings, compare, advice with price history), or try the sample to see every tab working.</p>" + howToMake() +
      '<div class="row-actions"><button class="btn ghost" id="ld-pick">Load data file</button></div>' +
      (location.protocol === "file:" ? "" : '<p><button class="linkbtn" id="ld-sample">or try sample data to explore</button></p>') +
      (reason ? '<p class="note">' + esc(reason) + "</p>" : "") + "</div>";
    $("ld-pick").onclick = pickFile;
    $("ld-blank").onclick = function () { startBlank(true); };
    if ($("ld-sample")) $("ld-sample").onclick = startSample;
  }
  function privacyNote() {
    return '<p class="privacy"><b>Your data is yours.</b> It stays in this browser on this device: never in the repo, never uploaded, ' +
      "no accounts, no trackers. Export it whenever you like, and import it on another phone or computer.</p>";
  }
  // Import & export for every way of opening the dashboard (the feed mode has its own, for holdings).
  function csvCell(v) { v = v == null ? "" : String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function toCSV(cols, rows) {
    return [cols.join(",")].concat(rows.map(function (r) { return cols.map(function (c) { return csvCell(r[c]); }).join(","); })).join("\r\n") + "\r\n";
  }
  function sharesCSV() {
    return toCSV(["symbol", "name", "sector", "shariah", "close", "last_date", "r1w", "r1m", "r3m", "r1y", "ytd", "vol", "pe", "div_yield", "score", "watch", "owned"],
      D.stocks.map(function (s) { return Object.assign({}, s, { div_yield: (s.div || {}).yield }); }));
  }
  function holdingsCSV() {
    var hs = ((D.mine || {}).holdings) || [];
    return toCSV(["symbol", "qty", "avg_cost", "cost", "price", "price_date", "value", "unrealised", "unrealised_pct", "action", "stop", "target", "status", "why"], hs);
  }
  function importExportHTML() {
    var hasMine = ((D.mine || {}).holdings || []).length > 0;
    return '<h2 style="margin-top:18px">Import &amp; export</h2>' +
      '<div class="row-actions"><button class="btn" id="ie-import">Import a data file…</button>' +
      '<button class="btn ghost" id="ie-json">Export data (.json)</button>' +
      '<button class="btn ghost" id="ie-shares">Shares (.csv)</button>' +
      (hasMine ? '<button class="btn ghost" id="ie-hold">My holdings (.csv)</button>' : "") + "</div>" +
      '<p class="note"><b>Export data</b> saves everything this page shows in one file; <b>Import</b> takes that file (or the ' +
      "<code>data.json</code> / <code>dashboard.html</code> your tools write) on any phone or computer. The CSVs open in Excel, " +
      "Google Sheets or LibreOffice." + (SOURCE === "sample" ? " In sample mode the exports hold the sample." : "") + "</p>";
  }
  function wireImportExport() {
    var stamp = todayISO();
    if ($("ie-import")) $("ie-import").onclick = pickFile;
    if ($("ie-json")) $("ie-json").onclick = function () {
      download((SOURCE === "sample" ? "psx-sample-data-" : "psx-dashboard-data-") + stamp + ".json", JSON.stringify(D), "application/json");
    };
    if ($("ie-shares")) $("ie-shares").onclick = function () { download("psx-shares-" + stamp + ".csv", sharesCSV(), "text/csv"); };
    if ($("ie-hold")) $("ie-hold").onclick = function () { download("psx-holdings-" + stamp + ".csv", holdingsCSV(), "text/csv"); };
  }
  function renderData() {
    if (SOURCE === "feed") return renderFeedData();
    var src = { server: "your dashboard server (data.json next to this page)", file: "the one-file dashboard you opened",
      device: "a file you loaded on this device", sample: "sample data: real PSX and MUFAP names, made-up prices",
      blank: "a clean slate on this device: your own entries, no market data loaded" }[SOURCE];
    $("dt-card").innerHTML = "<h2>Your data</h2>" +
      '<ul class="list"><li><span>Source</span><span>' + esc(src) + "</span></li>" +
      "<li><span>Built</span><span>" + esc(D.generated || "–") + "</span></li>" +
      "<li><span>Prices up to</span><span>" + esc(D.calendar[D.calendar.length - 1] || "–") + "</span></li>" +
      "<li><span>Shares</span><span>" + num(D.stocks.length) + " (" + esc(D.scope || "") + ")</span></li>" +
      (LOADED_AT ? "<li><span>Loaded</span><span>" + esc(LOADED_AT.name) + " · " + esc(new Date(LOADED_AT.loaded).toLocaleString()) + "</span></li>" : "") +
      "</ul>" + (SOURCE === "sample" ? '<div class="row-actions"><button class="btn" id="dt-pick">Load my data file</button>' +
        '<button class="btn ghost" id="dt-exit">Exit sample</button></div>' + howToMake() :
      SOURCE === "server" ? '<p class="note">Served by <code>dashboard.py serve</code>. To refresh, run the daily update or use the refresh banner.</p>' :
      '<div class="row-actions"><button class="btn" id="dt-pick">Load a newer data file</button>' +
      (SOURCE === "device" ? '<button class="btn danger" id="dt-forget">Forget data on this device</button>' : "") + "</div>" + howToMake()) +
      importExportHTML() + (canEdit() ? holdingsIOHTML() : "") + privacyNote() +
      '<p class="note">PSX market data is for personal use: don\'t republish it.</p>';
    wireImportExport();
    if (canEdit()) wireHoldingsIO();
    if (SOURCE !== "sample" && location.protocol !== "file:") {
      $("dt-card").insertAdjacentHTML("beforeend", '<p class="note">Want to see what every tab can do? ' +
        '<button class="linkbtn" id="dt-sample">Try the sample data</button>. Your own data stays as it is.</p>');
      $("dt-sample").onclick = startSample;
    }
    if ($("dt-exit")) $("dt-exit").onclick = exitSample;
    if ($("dt-pick")) $("dt-pick").onclick = pickFile;
    if ($("dt-forget")) $("dt-forget").onclick = function () {
      if (confirm("Remove the loaded data from this device?")) IDB.del("data").then(function () { location.reload(); });
    };
  }
  function fromDevice(reason) {
    return IDB.get("data").then(function (rec) {
      if (rec && validData(rec.data)) { SOURCE = "device"; LOADED_AT = rec; window.PKM_DATA = rec.data; return start(rec.data); }
      return IDB.get("blank").then(function (b) { return b ? startBlank(false) : showLoader(reason); });
    }).catch(function () { showLoader(reason); });
  }
  // ---------------------------------------------------------------- the site's price feed + your holdings in this browser
  // On GitHub Pages a GitHub Action (tools/web_feed.py) publishes PSX and MUFAP prices, encrypted, in
  // feed/. Your passphrase unlocks them here. Your holdings are a ledger kept in this browser's IndexedDB
  // (the same format as portfolio.py's ledger.json), never uploaded; Data has import, export and backup.
  var FEED_ST = null, FEED = null, FEED_KEY = null, LEDGER = null, PRESETS = null;
  function repoInfo() {
    var host = location.hostname.match(/^([a-z0-9-]+)\.github\.io$/i), seg = location.pathname.split("/").filter(Boolean)[0];
    return host && seg ? { owner: host[1], repo: seg } : { owner: "salmankhwaja", repo: "Day-Trader-PSX" };
  }
  function runUrl() { var r = repoInfo(); return "https://github.com/" + r.owner + "/" + r.repo + "/actions/workflows/feed.yml"; }
  function ago(iso) {
    var t = Date.parse(iso || ""); if (isNaN(t)) return "–";
    var m = Math.round((Date.now() - t) / 60000);
    return m < 60 ? m + " min ago" : m < 2880 ? Math.round(m / 60) + " h ago" : Math.round(m / 1440) + " days ago";
  }
  function startWeb(reason) {
    if (!window.WebFeed || !window.Ledger || location.protocol === "file:") return fromDevice(reason);
    WebFeed.status().then(function (st) {
      FEED_ST = st;
      if (!(st && st.psx && st.psx.available)) return fromDevice(reason);
      return IDB.get("feedkey").then(function (stored) {
        if (!stored) return IDB.get("data").then(function (rec) {
          return rec ? fromDevice(reason) : IDB.get("blank").then(function (b) { return b ? startBlank(false) : showUnlock(); });
        });
        return WebFeed.stillValid(stored).then(function (ok) {
          if (ok) return openFeed(stored.key);
          return IDB.del("feedkey").then(function () { showUnlock("The site's passphrase has changed: enter the new one."); });
        });
      });
    }).catch(function () { fromDevice(reason); });
  }
  function showUnlock(note) {
    $("tabs").hidden = true; document.querySelector("main").hidden = true;
    var L = $("loader"), ps = (FEED_ST || {}).psx || {};
    L.hidden = false;
    L.innerHTML = '<div class="card"><h2>Unlock prices</h2><p class="muted">This site publishes PSX and MUFAP prices ' +
      "for " + num(ps.shares || 0) + " shares (" + esc(ps.first || "") + " to " + esc(ps.last || "") + "), encrypted, because PSX " +
      "doesn't allow its data to be republished. Enter the passphrase set as the <code>PSX_DATA_KEY</code> secret of this repo. " +
      "It is checked here, on this device; nothing is sent anywhere.</p>" +
      '<form id="ul-form" autocomplete="on"><input type="text" name="username" value="psx-feed" autocomplete="username" hidden>' +
      '<input type="password" id="ul-pass" autocomplete="current-password" placeholder="Passphrase" style="width:100%;padding:10px" required>' +
      '<label class="small" style="display:block;margin-top:8px"><input type="checkbox" id="ul-keep" checked> Keep this device unlocked ' +
      '<span class="muted">(stores a locked key in this browser, never the passphrase)</span></label>' +
      '<div class="row-actions"><button class="btn big" type="submit">Unlock</button></div></form>' +
      '<p class="note" id="ul-msg">' + esc(note || "") + "</p>" +
      '<p class="small">No passphrase? <button class="linkbtn" id="ul-blank">Start your portfolio without prices</button> · ' +
      '<button class="linkbtn" id="ul-sample">try the sample data</button> · ' +
      '<button class="linkbtn" id="ul-file">load a data file instead</button></p></div>';
    $("ul-sample").onclick = startSample;
    $("ul-blank").onclick = function () { startBlank(true); };
    $("ul-file").onclick = function () { showLoader(""); };
    $("ul-form").onsubmit = function (e) {
      e.preventDefault();
      var btn = e.target.querySelector("button[type=submit]");
      btn.disabled = true; $("ul-msg").textContent = "Checking…";
      WebFeed.unlock($("ul-pass").value).then(function (k) {
        return ($("ul-keep").checked ? IDB.set("feedkey", k) : Promise.resolve()).then(function () { return openFeed(k.key); });
      }).catch(function (err) { btn.disabled = false; $("ul-msg").textContent = err.message === "wrong passphrase" ? "That passphrase didn't unlock the prices." : "Couldn't unlock: " + err.message; });
    };
    setTimeout(function () { if ($("ul-pass")) $("ul-pass").focus(); }, 50);
  }
  function openFeed(key) {
    FEED_KEY = key;
    $("loader").hidden = false;
    $("loader").innerHTML = '<div class="card"><h2>Loading prices…</h2><p class="muted">Decrypting on this device.</p></div>';
    return Promise.all([WebFeed.load(key, FEED_ST), IDB.get("ledger"), fetch("../brokers.json").then(function (r) { return r.json(); })]).then(function (x) {
      FEED = x[0]; LEDGER = Ledger.normalise(x[1] || Ledger.empty()); PRESETS = x[2];
      SOURCE = "feed";
      $("loader").hidden = true; $("tabs").hidden = false; document.querySelector("main").hidden = false;
      boot(WebFeed.build(FEED, LEDGER, Ledger));
    }).catch(function (e) { showUnlock("Couldn't load the prices: " + e.message); });
  }
  function rebuild() {
    D = SOURCE === "feed" ? WebFeed.build(FEED, LEDGER, Ledger, null, { profile: chosenProfile() }) : recompute(BASE);
    bySym = {}; D.stocks.forEach(function (s) { bySym[s.symbol] = s; });
    var on = Object.keys(views).filter(function (k) { return $("v-" + k).classList.contains("on"); })[0] || "mine";
    rendered = {}; show(on);
  }
  function saveLedger() {
    if (SOURCE === "sample") {   // the sample's practice portfolio lives in this tab only
      try { sessionStorage.setItem("pkm_sample_ledger", JSON.stringify(LEDGER)); } catch (e) {}
      return Promise.resolve().then(rebuild);
    }
    if (!canEdit()) return Promise.resolve().then(rebuild);
    return IDB.set("ledger", LEDGER).then(rebuild);
  }
  function feedBar() {
    var el = $("fresh"), st = FEED_ST || {}, ps = st.psx || {}, mf = st.mufap || {};
    el.hidden = false; el.className = "fresh";
    el.innerHTML = "Prices: PSX close <b>" + esc(ps.last || "–") + "</b>" + (mf.date ? " · MUFAP " + esc(mf.date) : "") +
      " · feed updated " + esc(ago(st.updated)) + ' · <a href="' + runUrl() + '" target="_blank" rel="noopener">Refresh prices now</a>' +
      ' · <span class="muted">your holdings stay in this browser</span>';
    $("livebar").hidden = true;
  }
  function download(name, text, type) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: type || "application/octet-stream" }));
    a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }
  function todayISO() { var d = new Date(); return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
  function fmsg(id, text, ok) { var el = $(id); if (el) { el.textContent = text; el.className = "note " + (ok ? "pos" : "neg"); } }


  // ---------------------------------------------------------------- your portfolio, kept and advised in the browser
  // Wherever the data lives in this browser (GitHub Pages, a loaded file, the one-file dashboard, the sample),
  // "My portfolio" is worked out here from your ledger (ledger.js: the same maths as portfolio.py and
  // advice.py) and your chosen risk appetite. dashboard.py serve stays read-only: it reads your Termux ledger.
  var BASE = null;
  var PROFILE_NAMES = { conservative: "Conservative", moderate: "Moderate", aggressive: "Aggressive", very_aggressive: "Very aggressive" };
  function webOf() { return (D && D.web) || (BASE && BASE.web) || (FEED && FEED.summary && FEED.summary.web) || null; }
  function engineOn() { return !!(window.Ledger && window.WebFeed && LEDGER && webOf() && webOf().profiles); }
  function canEdit() { return engineOn() && SOURCE !== "server"; }
  function chosenProfile() {
    var W = webOf() || {}, p = store("risk_profile");
    return (W.profiles || {})[p] ? p : (W.profile || "moderate");
  }
  function fmtSetting(k, v) {
    if (v == null) return "–";
    if (typeof v === "object") return Object.keys(v).map(function (x) { return x.replace("_", " ") + " " + Math.round(v[x] * 100) + "%"; }).join(", ");
    if (/pct|^gate_max|risk_per_trade/.test(k)) return (v * 100).toFixed(1).replace(/\.0$/, "") + "%";
    return String(Math.round(v * 100) / 100);
  }
  var RISK_SHOWN = ["risk_per_trade", "max_position_pct", "max_holdings", "cash_reserve_pct", "max_open_risk_pct",
    "stop_atr_mult", "min_stop_pct", "max_stop_pct", "target_r", "gate_max_drawdown", "gate_min_sharpe", "max_annual_loss_pct"];
  function recompute(base) {
    var d = Object.assign({}, base), W = base.web || {}, prof = chosenProfile();
    d.stocks = (base.stocks || []).map(function (x) { return Object.assign({}, x); });
    d.risk = Object.assign({}, base.risk || {});
    if (LEDGER && LEDGER.entries.length) {
      var today = base.sample ? base.sample.as_of : todayISO();
      var blank = SOURCE === "blank";
      var owned = WebFeed.applyLedger(d, LEDGER, Ledger, {
        S: WebFeed.settingsFor(base, prof), rowsOf: blank ? blankRows() : WebFeed.rowsFromSeries(base),
        ideas: base.ideas || ((base.mine || {}).buy_ideas) || [], fundIndex: blank ? blankNavs(W.fund_index) : W.fund_index || {}, categories: (base.funds || {}).categories,
        bench3m: ((base.benchmark || {}).metrics || {})["3m"], today: today, advice_date: base.generated, profile: prof });
      d.stocks.forEach(function (x) { x.owned = !!owned[x.symbol]; });
      if (blank && d.mine) (d.mine.funds || []).forEach(function (f) {   // no MUFAP table to rank against on a clean slate
        if (f.action === "NO DATA") { f.action = "HOLD"; f.why = "valued at your NAV; ranking within its category needs MUFAP data (load a data file)"; }
      });
      (d.dividend_calendar || []).forEach(function (x) { x.held = !!owned[x.symbol]; });
    } else if (canEdit()) d.mine = null;   // an empty browser portfolio: nothing to show yet
    var P = (W.profiles || {})[prof] || {}, S = WebFeed.settingsFor(base, prof);
    d.risk.profile = prof;
    d.risk.settings = RISK_SHOWN.map(function (k) { return { key: k, value: fmtSetting(k, S[k] != null ? S[k] : P[k]), about: (W.about || {})[k] || "" }; });
    if (P.allocation) d.risk.allocation_target = P.allocation;
    return d;
  }
  function loadLedger(data) {
    var W = data.web || {}, clone = function (x) { return x ? JSON.parse(JSON.stringify(x)) : null; };
    PRESETS = W.brokers || PRESETS;
    if (SOURCE === "server") { LEDGER = Ledger.normalise(clone(W.ledger) || Ledger.empty()); return Promise.resolve(); }
    if (SOURCE === "sample") {
      var kept = null;
      try { kept = JSON.parse(sessionStorage.getItem("pkm_sample_ledger") || "null"); } catch (e) {}
      LEDGER = Ledger.normalise(kept || clone(W.ledger) || Ledger.empty());
      return Promise.resolve();
    }
    return IDB.get("ledger").then(function (lg) {
      if (lg && lg.entries && lg.entries.length) { LEDGER = Ledger.normalise(lg); return; }
      LEDGER = Ledger.normalise(clone(W.ledger) || Ledger.empty());   // start from the holdings in the file you loaded
      if (LEDGER.entries.length) return IDB.set("ledger", LEDGER);
    }).catch(function () { LEDGER = Ledger.normalise(clone(W.ledger) || Ledger.empty()); });
  }
  /** Boot a data.json-shaped file (server, loaded file, one-file dashboard, sample) with the browser portfolio. */
  function start(data) {
    BASE = data;
    if (!(window.Ledger && window.WebFeed && data.web && data.web.profiles)) { LEDGER = null; return boot(data); }   // an older data.json
    return loadLedger(data).then(function () { boot(recompute(BASE)); }, function () { LEDGER = null; boot(data); });
  }
  function setProfile(p) {
    store("risk_profile", p);
    var on = Object.keys(views).filter(function (k) { return $("v-" + k).classList.contains("on"); })[0] || "mine";
    D = SOURCE === "feed" ? WebFeed.build(FEED, LEDGER, Ledger, null, { profile: p }) : recompute(BASE);
    bySym = {}; D.stocks.forEach(function (s) { bySym[s.symbol] = s; });
    rendered = {}; show(on);
  }
  var QUIZ = { open: false, answers: [] };
  function profileLine(S) {
    return "Risk " + fmtSetting("risk_per_trade", S.risk_per_trade) + " of capital per new buy · up to " + fmtSetting("max_position_pct", S.max_position_pct) +
      " in one share · at most " + fmtSetting("max_holdings", S.max_holdings) + " shares · keep " + fmtSetting("cash_reserve_pct", S.cash_reserve_pct) +
      " cash · stops " + fmtSetting("min_stop_pct", S.min_stop_pct) + "–" + fmtSetting("max_stop_pct", S.max_stop_pct) + " below entry · targets " +
      fmtSetting("target_r", S.target_r) + "× the risk" + (S.allocation ? " · aim for " + fmtSetting("allocation", S.allocation) : "") + ".";
  }
  function scoreQuiz(a, W) {   // risk.py score_quiz
    var cap = [], wil = [];
    W.quiz.forEach(function (q, i) { (q.dim === "capacity" ? cap : wil).push(a[i]); });
    var level = function (xs) { return Math.min(4, Math.max(1, Math.round(xs.reduce(function (t, x) { return t + x; }, 0) / xs.length))); };
    var lc = level(cap), lw = level(wil);
    if (a[0] === 1 || a[2] === 1) lc = 1;   // money needed within 2 years, or under a month saved, caps it
    var fin = Math.min(lc, lw);
    return { capacity: lc, willingness: lw, profile: W.order[fin - 1], worst: (W.worst_year || [])[a[7] - 1],
      limited_by: lc < lw ? "capacity" : lw < lc ? "willingness" : "both" };
  }
  function renderRiskCard(id, parent) {
    var box = $(id), W = webOf() || {}, prof = chosenProfile();
    if (!box) { box = document.createElement("div"); box.id = id; parent.insertBefore(box, parent.firstChild); }
    var S = Object.assign({}, (W.profiles || {})[prof] || {}, WebFeed.settingsFor(D.web ? D : BASE || {}, prof));
    var html = '<div class="card" style="margin-bottom:12px"><h2>Your risk appetite</h2>' +
      '<div class="seg" role="radiogroup" aria-label="Risk appetite">' + (W.order || []).map(function (p) {
        return '<button type="button" data-prof="' + p + '" class="' + (p === prof ? "on" : "") + '" aria-checked="' + (p === prof) + '">' + esc(PROFILE_NAMES[p] || p) + "</button>";
      }).join("") + "</div>" +
      '<p class="small" style="margin:10px 0 4px">' + esc(profileLine(S)) + "</p>" +
      '<p class="note">Sell, trim or hold, stop-losses, targets, buy-idea sizes and order tickets on this page follow this choice' +
      (prof === W.profile && SOURCE !== "sample" ? " (with any values you set yourself in config.json)" : "") + ". Saved in this browser. " +
      '<button class="linkbtn" data-quiz="1">' + (QUIZ.open ? "Close the quiz" : "Not sure? Take the 8-question quiz") + "</button></p>";
    if (QUIZ.open) {
      html += '<form class="quiz" id="' + id + '-quiz">' + W.quiz.map(function (q, i) {
        return '<fieldset><legend>' + (i + 1) + ". " + esc(q.q) + "</legend>" + q.answers.map(function (a, j) {
          return '<label class="qopt"><input type="radio" name="q' + i + '" value="' + (j + 1) + '"' + (QUIZ.answers[i] === j + 1 ? " checked" : "") + "> " + esc(a) + "</label>";
        }).join("") + "</fieldset>";
      }).join("") + '<div class="row-actions"><button class="btn" type="submit">See my result</button></div><p class="note" id="' + id + '-qres"></p></form>';
    }
    box.innerHTML = html + '<p class="note">Rule-based suggestions from your chosen limits, not investment advice. Nothing here places an order.</p></div>';
    box.querySelectorAll("[data-prof]").forEach(function (b) { b.onclick = function () { setProfile(b.getAttribute("data-prof")); }; });
    box.querySelector("[data-quiz]").onclick = function () { QUIZ.open = !QUIZ.open; renderRiskCard(id, parent); };
    var form = $(id + "-quiz");
    if (form) form.onsubmit = function (e) {
      e.preventDefault();
      var a = W.quiz.map(function (q, i) { var c = form.querySelector('input[name="q' + i + '"]:checked'); return c ? +c.value : 0; });
      QUIZ.answers = a;
      if (a.indexOf(0) >= 0) { $(id + "-qres").textContent = "Answer all eight, please (question " + (a.indexOf(0) + 1) + " is missing)."; return; }
      var r = scoreQuiz(a, W);
      $(id + "-qres").innerHTML = "Your answers point to <b>" + esc(PROFILE_NAMES[r.profile]) + "</b> (ability to take risk " + r.capacity + "/4, comfort with it " +
        r.willingness + "/4" + (r.limited_by !== "both" ? "; set by your " + r.limited_by : "") + "). Worst year you could live with: " +
        Math.round((r.worst || 0) * 100) + "%. " + '<button class="btn" type="button" id="' + id + '-use">Use ' + esc(PROFILE_NAMES[r.profile]) + "</button>";
      $(id + "-use").onclick = function () { QUIZ.open = false; setProfile(r.profile); };
    };
  }
  function serverNote() {
    var box = $("mi-edit");
    if (!box) { box = document.createElement("div"); box.id = "mi-edit"; $("v-mine").insertBefore(box, $("mi-risk") ? $("mi-risk").nextSibling : $("v-mine").firstChild); }
    box.innerHTML = '<div class="card" style="margin-bottom:12px"><h2>Your holdings</h2><p class="muted">This page is served by <code>dashboard.py</code> ' +
      "from your Termux ledger, so it shows and advises, but doesn't change it. Record trades with <code>portfolio.py buy / sell</code> (or the menu), " +
      "or open the GitHub Pages copy, load your data and add them there.</p></div>";
  }


  // ---------------------------------------------------------------- a clean slate: your portfolio with no data file
  // Start my portfolio works on a blank browser: no data file, no passphrase. Shares are valued at your
  // last trade or a price you type ("Update prices"); funds at your last NAV, a NAV you type, or, on a
  // github.io site that also hosts PK Wealth, the MUFAP NAVs it publishes. Advice that needs price
  // history (trend, volatility stops, buy ideas) waits for market data; the rules that don't (position
  // size, minimum stop distance, cash reserve) apply now. Loading a data file later keeps everything.
  var MANUAL = {};   // {SYMBOL or fund name: {price, date}} typed in clean-slate mode
  var BLANK_MKT = null; // PK Wealth's public prices.json as fetched this visit (fund NAVs, its "updated" time)
  function startBlank(fresh) {
    SOURCE = "blank";
    var web = fetch("sample-data.json", { cache: "no-cache" }).then(function (r) { return r.json(); }).then(function (x) {
      var w = Object.assign({}, x.web || {}); delete w.ledger; w.fund_index = {}; return w;   // profiles, quiz, broker tariffs: not market data
    });
    var navs = /\.github\.io$/i.test(location.hostname)
      ? fetch(location.origin + "/WealthTracker/data/prices.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
      : Promise.resolve(null);
    return Promise.all([web, navs, IDB.get("prices").catch(function () { return null; }), fresh ? IDB.set("blank", true) : null]).then(function (x) {
      MANUAL = x[2] || {}; BLANK_MKT = x[1];
      var idx = {}, items = (((x[1] || {}).funds) || {}).items || [];
      items.forEach(function (f) { if (f.fund && f.nav) idx[f.fund] = { nav: f.nav, date: f.date, category: f.category || null, amc: f.amc || null }; });
      x[0].fund_index = idx;
      $("loader").hidden = true; $("tabs").hidden = false; document.querySelector("main").hidden = false;
      return start({ generated: todayISO(), scope: "your portfolio", calendar: [], series: {}, stocks: [], sectors: [], benchmark: { symbol: "KSE100", metrics: null },
        notes: {}, dividend_calendar: [], portfolio: null, proposal: null, funds: null, mine: null, risk: {}, market: null, web: x[0] });
    }).catch(function (e) { showLoader("Couldn't start an empty portfolio (" + e.message + ")."); });
  }
  function blankRows() {
    var last = {};
    Ledger.ordered(LEDGER.entries).forEach(function (e) { if ((e.type === "buy" || e.type === "sell") && e.price) last[e.symbol] = { date: e.date, close: e.price }; });
    Object.keys(MANUAL).forEach(function (k) { var m = MANUAL[k]; if (m && m.symbol && (!last[k] || m.date >= last[k].date)) last[k] = { date: m.date, close: m.price }; });
    return function (sym) { return last[sym] ? [last[sym]] : []; };
  }
  function blankNavs(feedIdx) {
    var idx = Object.assign({}, feedIdx || {});
    Ledger.ordered(LEDGER.entries).forEach(function (e) {
      if ((e.type === "fund_buy" || e.type === "fund_sell") && e.nav && (!idx[e.fund] || e.date >= idx[e.fund].date)) idx[e.fund] = { nav: e.nav, date: e.date, category: (idx[e.fund] || {}).category || e.category || null };
    });
    Object.keys(MANUAL).forEach(function (k) { var m = MANUAL[k]; if (m && m.fund && (!idx[k] || m.date >= idx[k].date)) idx[k] = { nav: m.price, date: m.date, category: (idx[k] || {}).category || null }; });
    return idx;
  }
  function blankBar() {
    var el = $("fresh"), n = Object.keys(fundIndex()).length;
    el.hidden = false; el.className = "fresh";
    el.innerHTML = "<b>Your portfolio, from a clean slate.</b> Shares are valued at your last trade or a price you type (<i>Update prices</i>)" +
      (n ? "; funds at today's MUFAP NAV (" + num(n) + " funds, via PK Wealth)" : "; funds at your last NAV or one you type") +
      ". Trend, volatility stops and buy ideas need price history: load a data file or unlock the site's prices, and everything you add here stays." +
      "<br>" + blankMarketLine() +
      '<div class="row-actions"><button class="btn" id="bb-pick">Load a data file</button>' +
      (FEED_ST && FEED_ST.psx && FEED_ST.psx.available ? '<button class="btn ghost" id="bb-unlock">Unlock prices</button>' : "") + "</div>";
    $("bb-pick").onclick = pickFile;
    if ($("bb-unlock")) $("bb-unlock").onclick = function () { IDB.del("blank").then(function () { location.reload(); }); };
    $("livebar").hidden = true;
  }
  // Where the site's prices stand: when the scheduled job last fetched them, and that the next run
  // replaces them on its own. Nothing here can start a fetch: only the repo owner can run the job.
  function blankMarketLine() {
    var m = BLANK_MKT || {}, f = m.funds || {}, st = FEED_ST || {}, ps = st.psx || {}, bits = [];
    if (f.count) {
      // MUFAP lists each NAV with its validity date. Most funds carry the last dealing day, but some
      // money-market and cash funds already list the next one (a Friday NAV valid on Monday), so the
      // newest date is misleading: show the date most funds carry, and say how many are ahead of it.
      var cnt = {}, main = null, ahead = 0;
      (f.items || []).forEach(function (i) { if (i.date) cnt[i.date] = (cnt[i.date] || 0) + 1; });
      Object.keys(cnt).forEach(function (d) { if (main == null || cnt[d] > cnt[main]) main = d; });
      Object.keys(cnt).forEach(function (d) { if (main && d > main) ahead += cnt[d]; });
      bits.push("MUFAP NAVs as of " + esc(main || f.latest_date || "?") + " (fetched " + ago(m.updated) + ")" +
        (ahead ? "; " + ahead + " funds, mostly money-market, already list a later date: MUFAP shows the day each NAV applies to" : ""));
    }
    else bits.push("MUFAP NAVs: none here (they come from PK Wealth on the same github.io site)");
    if (st.updated) bits.push(ps.available ? "PSX closes fetched " + ago(st.updated) + " (unlock to use them)" : "PSX closes: the site's PSX feed is off");
    return '<span class="small">Site prices: ' + bits.join(" · ") +
      ". A scheduled job refreshes them on weekdays (midday, after the close, and late evening for NAVs) and Saturday night; " +
      "each visit picks up the newest. A NAV you type is used until the site has a newer one; your transactions are never changed.</span>";
  }
  function renderPrices(box) {   // clean-slate mode: type today's price for each share and NAV for each fund
    var M = D.mine || {}, HS = M.holdings || [], FS = M.funds || [];
    if (!HS.length && !FS.length) return '<p class="muted">Add a holding first.</p>';
    return '<form id="ed-prices" class="edform"><h3 class="edh">Update prices</h3>' +
      '<p class="small muted">Today\'s price per share, or a fund\'s NAV. Leave a box as it is to keep the last one.</p>' +
      HS.map(function (h) { return '<label>' + esc(h.symbol) + ' <span class="muted">last ' + esc(h.price_date || "") + '</span><input type="number" data-price-sym="' + esc(h.symbol) + '" data-was="' + v(h.price) + '" value="' + v(h.price) + '"></label>'; }).join("") +
      FS.map(function (f) { var x = blankNavs(fundIndex())[f.fund] || {}; return '<label>' + esc(f.fund) + ' <span class="muted">NAV ' + esc(x.date || "") + '</span><input type="number" data-price-fund="' + esc(f.fund) + '" data-was="' + v(x.nav) + '" value="' + v(x.nav) + '"></label>'; }).join("") +
      '<label>As of <input type="date" id="ep-date" value="' + todayISO() + '"></label>' +
      '<div class="row-actions"><button class="btn" type="submit">Save prices</button><button class="btn ghost" type="button" data-cancel="1">Cancel</button></div></form>';
  }
  function wirePrices(done) {
    var form = $("ed-prices"); if (!form) return;
    form.onsubmit = function (e) {
      e.preventDefault();
      var date = $("ep-date").value || todayISO(), n = 0;
      form.querySelectorAll("[data-price-sym],[data-price-fund]").forEach(function (inp) {
        var p = parseFloat(String(inp.value).replace(/,/g, "")); if (!(p > 0)) return;
        if (p === parseFloat(inp.getAttribute("data-was"))) return;   // untouched: keep the last price
        var sym = inp.getAttribute("data-price-sym"), fund = inp.getAttribute("data-price-fund"), key = sym || fund;
        var old = MANUAL[key];
        if (old && old.price === p && old.date === date) return;
        MANUAL[key] = sym ? { symbol: sym, price: p, date: date } : { fund: fund, price: p, date: date }; n++;
      });
      IDB.set("prices", MANUAL).then(function () { done(n ? "Updated " + n + " price" + (n > 1 ? "s" : "") + "." : "Nothing changed."); });
    };
  }

  // ---- My portfolio: add trades, funds, cash and dividends here
  var EDIT = { form: null, prefill: null, editId: null };
  function brokerOptions(pick) {
    var names = Object.keys(LEDGER.brokers), want = pick && LEDGER.brokers[pick] ? pick : LEDGER.default_broker;
    return names.map(function (n) { return '<option' + (n === want ? " selected" : "") + ">" + esc(n) + "</option>"; }).join("");
  }
  function presetOptions() {
    return Object.keys(PRESETS.brokers).sort().map(function (k) {
      return '<option value="' + esc(k) + '"' + (k === "finqalab" ? " selected" : "") + ">" + esc(PRESETS.brokers[k].name || k) + "</option>";
    }).join("");
  }
  function fundIndex() { return D.fund_index || (D.web || {}).fund_index || ((BASE || {}).web || {}).fund_index || {}; }
  function v(x) { return x == null ? "" : esc(String(x)); }
  function renderEditor() {
    var box = $("mi-edit");
    if (!box) { box = document.createElement("div"); box.id = "mi-edit"; $("v-mine").insertBefore(box, $("mi-risk") ? $("mi-risk").nextSibling : $("v-mine").firstChild); }
    var n = LEDGER.entries.length, hasB = Object.keys(LEDGER.brokers).length > 0, f = EDIT.form, P = EDIT.prefill || {}, editing = EDIT.editId != null;
    var M = D.mine || {}, HS = M.holdings || [], FS = M.funds || [];
    var where = SOURCE === "sample" ? "practice portfolio: this browser tab only, your own data untouched" : "kept in this browser only";
    var head = '<div class="card" style="margin-bottom:12px"><h2>Your holdings <span class="muted" style="text-transform:none;letter-spacing:0">· ' + where + "</span></h2>" +
      (n ? "" : '<p class="muted">Add what you hold and every tab works it out: green or red after charges, stop-losses, what to sell, trim or hold, and buy ideas sized to your cash. ' +
        "Already use the Python tools? <b>Data › Import</b> takes your <code>ledger.json</code> or a trades CSV.</p>") +
      '<div class="row-actions">' +
      (hasB ? '<button class="btn" data-f="trade">+ Buy or sell shares</button><button class="btn ghost" data-f="fund">+ Mutual fund</button>' +
        '<button class="btn ghost" data-f="cash">+ Cash</button><button class="btn ghost" data-f="div">+ Dividend</button>' +
        '<button class="btn ghost" data-f="list">Transactions (' + n + ")</button>" +
        (SOURCE === "blank" && n ? '<button class="btn ghost" data-f="prices">Update prices</button>' : "") : "") +
      '<button class="btn ghost" data-f="broker">' + (hasB ? "Brokers" : "Start: pick your broker") + "</button></div>";
    // One tap from what you hold: buy more, sell, invest more, redeem
    if (hasB && (HS.length || FS.length) && !f) {
      head += '<div class="quick">' + HS.map(function (h) {
        return '<span class="qh"><b>' + esc(h.symbol) + "</b> " + num(h.qty) + ' <span class="muted">sh</span>' +
          (h.action ? ' <span class="st ' + (h.action === "SELL" ? "RED" : h.action === "TRIM" ? "FLAT" : "GREEN") + '">' + esc(h.action) + "</span>" : "") +
          '<button class="linkbtn" data-q="buy" data-qsym="' + esc(h.symbol) + '">Buy</button><button class="linkbtn" data-q="sell" data-qsym="' + esc(h.symbol) + '" data-qty="' +
          (h.action === "TRIM" && h.trim_qty ? h.trim_qty : h.qty) + '">Sell</button></span>';
      }).join("") + FS.map(function (x) {
        return '<span class="qh"><b>' + esc(x.fund) + '</b> <span class="muted">' + pkr(x.value) + "</span>" +
          '<button class="linkbtn" data-qf="buy" data-fund="' + esc(x.fund) + '">Invest</button><button class="linkbtn" data-qf="sell" data-fund="' + esc(x.fund) +
          '" data-amt="' + (x.value || "") + '">Redeem</button></span>';
      }).join("") + "</div>";
    }
    var body = "", save = '<div class="row-actions"><button class="btn" type="submit">' + (editing ? "Save changes" : "Save") + "</button>" +
      (editing || f ? '<button class="btn ghost" type="button" data-cancel="1">Cancel</button>' : "") + "</div>";
    if (!hasB || f === "broker") {
      body = '<form id="ed-broker" class="edform"><label>Broker <select id="eb-preset">' + presetOptions() + "</select></label>" +
        '<label>Name it <input id="eb-name" placeholder="e.g. Finqalab" required></label>' +
        '<button class="btn" type="submit">Add broker</button>' +
        (hasB ? '<p class="small muted">Yours: ' + Object.keys(LEDGER.brokers).map(function (k) { return esc(k) + (k === LEDGER.default_broker ? " (default)" : ""); }).join(", ") + "</p>" : "") +
        '<p class="small muted">Charges are estimated from the broker\'s published tariff (brokers.json); enter the real ones from your contract note when you have them.</p></form>';
    } else if (f === "trade") {
      body = '<form id="ed-trade" class="edform"><h3 class="edh">' + (editing ? "Edit transaction" : P.side === "sell" ? "Sell shares" : "Buy or sell shares") + "</h3>" +
        '<label>Side <select id="et-side"><option value="buy"' + (P.side !== "sell" ? " selected" : "") + '>Buy</option><option value="sell"' + (P.side === "sell" ? " selected" : "") + ">Sell</option></select></label>" +
        '<label>Symbol <input id="et-sym" list="ed-syms" autocapitalize="characters" required placeholder="e.g. MEBL" value="' + v(P.symbol) + '"></label>' +
        '<label>Shares <input id="et-qty" type="number" required placeholder="e.g. 500" value="' + v(P.qty) + '"></label>' +
        '<label>Price per share <input id="et-px" type="number" required placeholder="e.g. 253.50" value="' + v(P.price) + '"></label>' +
        '<label>Date <input id="et-date" type="date" value="' + v(P.date || todayISO()) + '" required></label><label>Time <input id="et-time" type="time" value="' + v(P.time) + '"></label>' +
        '<label>Broker <select id="et-broker">' + brokerOptions(P.broker) + "</select></label>" +
        '<details' + (P.commission != null || P.stop ? " open" : "") + '><summary class="small">Charges from the contract note, stop-loss, note (optional)</summary>' +
        '<label>Commission <input id="et-c" type="number" placeholder="estimated if empty" value="' + v(P.commission) + '"></label><label>Taxes <input id="et-t" type="number" placeholder="estimated if empty" value="' + v(P.taxes) + '"></label>' +
        '<label>Other (CDC, levies) <input id="et-o" type="number" placeholder="estimated if empty" value="' + v(P.other) + '"></label><label>Your stop-loss <input id="et-stop" type="number" placeholder="worked out if empty" value="' + v(P.stop) + '"></label>' +
        '<label>Note <input id="et-note" placeholder="e.g. contract note #1234" value="' + v(P.note) + '"></label></details>' +
        '<p class="small muted" id="et-calc"></p>' + save + '' +
        '<datalist id="ed-syms">' + (D.stocks.length ? D.stocks.map(function (x) { return '<option value="' + esc(x.symbol) + '">' + esc(x.name || "") + "</option>"; }) :
          Object.keys(LEDGER.entries.reduce(function (a, e) { if (e.symbol) a[e.symbol] = 1; return a; }, {})).map(function (k) { return '<option value="' + esc(k) + '">'; })).join("") + "</datalist></form>";
    } else if (f === "fund") {
      var FI = fundIndex();
      body = '<form id="ed-fund" class="edform"><h3 class="edh">' + (editing ? "Edit fund transaction" : P.side === "sell" ? "Redeem from a fund" : "Mutual fund") + "</h3>" +
        '<label>Side <select id="ef-side"><option value="buy"' + (P.side !== "sell" ? " selected" : "") + '>Invest</option><option value="sell"' + (P.side === "sell" ? " selected" : "") + ">Redeem</option></select></label>" +
        '<label>Fund <input id="ef-fund" list="ed-funds" required placeholder="e.g. Meezan Islamic Fund" value="' + v(P.fund) + '"></label>' +
        '<label>Amount (PKR) <input id="ef-amt" type="number" required placeholder="e.g. 100,000" value="' + v(P.amount) + '"></label>' +
        '<label>NAV <input id="ef-nav" type="number" required placeholder="from MUFAP, or your statement" value="' + v(P.nav) + '"></label>' +
        '<label>Date <input id="ef-date" type="date" value="' + v(P.date || todayISO()) + '" required></label>' +
        '<label>Load % <input id="ef-load" type="number" placeholder="0" value="' + v(P.load_pct) + '"></label>' +
        '<p class="small muted" id="ef-calc">For an older date, type that day\'s NAV from your fund statement.</p>' + save + '' +
        '<datalist id="ed-funds">' + Object.keys(FI).sort().map(function (k) { return '<option value="' + esc(k) + '">' + esc(FI[k].category) + "</option>"; }).join("") + "</datalist></form>";
    } else if (f === "cash") {
      body = '<form id="ed-cash" class="edform"><h3 class="edh">' + (editing ? "Edit cash entry" : "Cash with your broker") + "</h3>" +
        '<label>Kind <select id="ec-kind"><option value="1"' + (!(P.amount < 0) ? " selected" : "") + '>Deposit</option><option value="-1"' + (P.amount < 0 ? " selected" : "") + ">Withdrawal</option></select></label>" +
        '<label>Amount (PKR) <input id="ec-amt" type="number" required placeholder="e.g. 500,000" value="' + v(P.amount != null ? Math.abs(P.amount) : null) + '"></label>' +
        '<label>Date <input id="ec-date" type="date" value="' + v(P.date || todayISO()) + '" required></label>' +
        save + '<p class="small muted">Cash lets buy ideas respect what you can actually spend.</p></form>';
    } else if (f === "div") {
      body = '<form id="ed-div" class="edform"><h3 class="edh">' + (editing ? "Edit dividend" : "Dividend received") + "</h3>" +
        '<label>Symbol <input id="ed-dsym" list="ed-syms2" autocapitalize="characters" required placeholder="e.g. HUBC" value="' + v(P.symbol) + '"></label>' +
        '<label>Received, after tax (PKR) <input id="ed-damt" type="number" required placeholder="e.g. 12,000" value="' + v(P.net) + '"></label>' +
        '<label>Date <input id="ed-ddate" type="date" value="' + v(P.date || todayISO()) + '" required></label>' + save + '' +
        '<datalist id="ed-syms2">' + HS.map(function (h) { return '<option value="' + esc(h.symbol) + '">'; }).join("") + "</datalist></form>";
    } else if (f === "prices") {
      body = renderPrices();
    } else if (f === "list") {
      var E = Ledger.ordered(LEDGER.entries).reverse();
      body = '<div class="tablewrap" style="max-height:55vh"><table><tr><th class="l">Date</th><th class="l">Transaction</th><th>Amount</th><th class="l hide-m">Broker</th><th></th></tr>' +
        (E.length ? E.map(function (e) {
          var what = e.type === "buy" || e.type === "sell" ? "<b class='" + (e.type === "buy" ? "pos" : "neg") + "'>" + e.type.toUpperCase() + "</b> " + esc(e.symbol) + " " + num(e.qty) + " @ " + num(e.price, 2) :
            e.type === "fund_buy" || e.type === "fund_sell" ? (e.type === "fund_buy" ? "Invest " : "Redeem ") + esc(e.fund) + " <span class='muted'>@ " + num(e.nav, 4) + "</span>" :
            e.type === "cash" ? (e.amount >= 0 ? "Deposit" : "Withdrawal") : e.type === "dividend" ? "Dividend " + esc(e.symbol) : esc(e.type);
          var amt = e.type === "buy" || e.type === "sell" ? pkr(e.qty * e.price) : pkr(e.amount != null ? e.amount : e.net);
          var editable = ["buy", "sell", "fund_buy", "fund_sell", "cash", "dividend"].indexOf(e.type) >= 0;
          return "<tr>" + cell(esc(e.date) + (e.time ? " " + esc(e.time) : ""), "l") + cell(what, "l") + cell(amt) + cell(esc(e.broker || ""), "l hide-m") +
            cell((editable ? '<button class="btn ghost small" data-edit="' + e.id + '">Edit</button> ' : "") + '<button class="btn ghost small" data-del="' + e.id + '">Delete</button>') + "</tr>";
        }).join("") : "<tr><td class='l muted' colspan='5'>Nothing recorded yet.</td></tr>") + "</table></div>";
    }
    box.innerHTML = head + body + '<p id="ed-msg" class="note" role="status"></p></div>';
    enhanceNumbers(box);
    var reset = function () { EDIT.form = null; EDIT.prefill = null; EDIT.editId = null; };
    box.querySelectorAll("[data-f]").forEach(function (b) { b.onclick = function () { var to = EDIT.form === b.dataset.f ? null : b.dataset.f; reset(); EDIT.form = to; renderEditor(); }; });
    box.querySelectorAll("[data-cancel]").forEach(function (b) { b.onclick = function () { var back = EDIT.editId != null ? "list" : null; reset(); EDIT.form = back; renderEditor(); }; });
    box.querySelectorAll("[data-q]").forEach(function (b) {
      b.onclick = function () {
        var sym = b.dataset.qsym, st = bySym[sym] || {};
        reset(); EDIT.form = "trade";
        EDIT.prefill = { side: b.dataset.q, symbol: sym, qty: b.dataset.q === "sell" ? b.dataset.qty : "", price: st.close || "" };
        renderEditor(); box.scrollIntoView({ block: "start", behavior: "smooth" });
      };
    });
    box.querySelectorAll("[data-qf]").forEach(function (b) {
      b.onclick = function () {
        var x = fundIndex()[b.dataset.fund] || {};
        reset(); EDIT.form = "fund";
        EDIT.prefill = { side: b.dataset.qf, fund: b.dataset.fund, nav: x.nav || "", amount: b.dataset.qf === "sell" ? Math.round(+b.dataset.amt || 0) || "" : "" };
        renderEditor(); box.scrollIntoView({ block: "start", behavior: "smooth" });
      };
    });
    // Save: a new transaction, or an edited one (the old one is replaced; if the new one doesn't fit, nothing changes)
    var done = function (msg) { reset(); EDIT.form = msg.list ? "list" : null; saveLedger().then(function () { fmsg("ed-msg", msg.text || msg, true); }); };
    var guard = function (fn) {
      return function (e) {
        e.preventDefault();
        var snap = JSON.stringify(LEDGER), id = EDIT.editId;
        try {
          if (id != null) Ledger.remove(LEDGER, id);
          var r = fn();
          done(id != null ? { text: "Changed. " + r, list: true } : r);
        } catch (err) { LEDGER = JSON.parse(snap); fmsg("ed-msg", err.message, false); }
      };
    };
    if ($("ed-broker")) $("ed-broker").onsubmit = function (e) {
      e.preventDefault();
      try {
        var name = $("eb-name").value.trim(); if (!name) throw new Error("name the broker");
        Ledger.addBroker(LEDGER, PRESETS, name, $("eb-preset").value, true); reset(); EDIT.form = "trade"; saveLedger();
      } catch (err) { fmsg("ed-msg", err.message, false); }
    };
    if ($("eb-preset")) $("eb-preset").onchange = function () { if (!$("eb-name").value) $("eb-name").value = (PRESETS.brokers[$("eb-preset").value].name || "").split(" (")[0]; };
    if ($("eb-preset") && !$("eb-name").value) $("eb-preset").onchange();
    var tradeCalc = function () {
      if (!$("et-calc")) return;
      var q = parseFloat(String($("et-qty").value).replace(/,/g, "")), p = parseFloat(String($("et-px").value).replace(/,/g, "")), b = LEDGER.brokers[$("et-broker").value];
      if (!(q > 0) || !(p > 0) || !b) { $("et-calc").textContent = ""; return; }
      var side = $("et-side").value, c = Ledger.estimateCharges(b, q, p, side), fees = c[0] + c[1] + c[2];
      $("et-calc").textContent = "Value " + pkr(q * p) + " · est. charges " + pkr(fees) + " (commission " + num(c[0], 2) + ", tax " + num(c[1], 2) + ", CDC/levies " + num(c[2], 2) + ") → " +
        (side === "buy" ? "you pay about " + pkr(q * p + fees) : "you receive about " + pkr(q * p - fees)) + ". Your contract note wins.";
    };
    if ($("et-sym")) {
      $("et-sym").onchange = function () { var x = bySym[$("et-sym").value.trim().toUpperCase()]; if (x && !$("et-px").value) { $("et-px").value = groupNum(x.close); } tradeCalc(); };
      ["et-qty", "et-px", "et-side", "et-broker"].forEach(function (k) { $(k).addEventListener("input", tradeCalc); $(k).addEventListener("change", tradeCalc); });
      tradeCalc();
    }
    if ($("ed-trade")) $("ed-trade").onsubmit = guard(function () {
      var e = Ledger.recordTrade(LEDGER, PRESETS, { side: $("et-side").value, symbol: $("et-sym").value, qty: $("et-qty").value, price: $("et-px").value,
        date: $("et-date").value, time: $("et-time").value, broker: $("et-broker").value, commission: $("et-c").value, taxes: $("et-t").value,
        other: $("et-o").value, stop: $("et-stop").value, note: $("et-note").value });
      return "Saved: " + e.type + " " + num(e.qty) + " " + e.symbol + " @ " + e.price + (e.estimated.length ? " (charges estimated)" : "");
    });
    var fundCalc = function () {
      if (!$("ef-calc")) return;
      var a = parseFloat(String($("ef-amt").value).replace(/,/g, "")), nv0 = parseFloat(String($("ef-nav").value).replace(/,/g, "")), ld = parseFloat($("ef-load").value) || 0;
      var x = fundIndex()[$("ef-fund").value];
      var hint = x ? "MUFAP NAV " + num(x.nav, 4) + " on " + x.date + " (" + x.category + "). " : "";
      if (a > 0 && nv0 > 0) {
        var units = $("ef-side").value === "sell" ? a / (nv0 * (1 - ld / 100)) : a * (1 - ld / 100) / nv0;
        $("ef-calc").textContent = hint + groupNum(String(a)) + " ÷ " + nv0 + (ld ? " (after " + ld + "% load)" : "") + " = " + num(units, 4) + " units.";
      } else $("ef-calc").textContent = hint + "For an older date, type that day's NAV from your fund statement.";
    };
    if ($("ef-fund")) {
      $("ef-fund").onchange = function () { var x = fundIndex()[$("ef-fund").value]; if (x && !$("ef-nav").value) $("ef-nav").value = x.nav; fundCalc(); };
      $("ef-date").onchange = function () { var x = fundIndex()[$("ef-fund").value]; if (x && $("ef-date").value < x.date && String($("ef-nav").value) === String(x.nav)) $("ef-nav").value = ""; fundCalc(); };
      ["ef-amt", "ef-nav", "ef-load", "ef-side"].forEach(function (k) { $(k).addEventListener("input", fundCalc); $(k).addEventListener("change", fundCalc); });
      fundCalc();
    }
    if ($("ed-fund")) $("ed-fund").onsubmit = guard(function () {
      var x = fundIndex()[$("ef-fund").value];
      var e = Ledger.recordFund(LEDGER, { side: $("ef-side").value, fund: $("ef-fund").value, amount: $("ef-amt").value, nav: $("ef-nav").value,
        date: $("ef-date").value, load_pct: $("ef-load").value, category: x ? x.category : null });
      return "Saved: " + (e.type === "fund_buy" ? "invested " : "redeemed ") + pkr(e.amount) + " in " + e.fund + " (" + num(e.units, 4) + " units).";
    });
    wirePrices(function (msg) { reset(); saveLedger().then(function () { fmsg("ed-msg", msg, true); }); });
    if ($("ed-cash")) $("ed-cash").onsubmit = guard(function () {
      Ledger.recordCash(LEDGER, (+$("ec-kind").value) * parseFloat(String($("ec-amt").value).replace(/,/g, "")), $("ec-date").value); return "Saved.";
    });
    if ($("ed-div")) $("ed-div").onsubmit = guard(function () { Ledger.recordDividend(LEDGER, $("ed-dsym").value, $("ed-damt").value, $("ed-ddate").value); return "Saved."; });
    box.querySelectorAll("[data-edit]").forEach(function (b) {
      b.onclick = function () {
        var e = LEDGER.entries.find(function (x) { return x.id === +b.dataset.edit; });
        if (!e) return;
        reset(); EDIT.editId = e.id;
        if (e.type === "buy" || e.type === "sell") {
          EDIT.form = "trade";
          EDIT.prefill = { side: e.type, symbol: e.symbol, qty: e.qty, price: e.price, date: e.date, time: e.time, broker: e.broker, note: e.note,
            commission: e.commission_estimated ? null : e.commission, taxes: (e.estimated || []).indexOf("taxes") >= 0 ? null : e.taxes,
            other: (e.estimated || []).indexOf("other") >= 0 ? null : e.other, stop: e.type === "buy" ? LEDGER.stops[e.symbol] : null };
        } else if (e.type === "fund_buy" || e.type === "fund_sell") {
          EDIT.form = "fund"; EDIT.prefill = { side: e.type === "fund_sell" ? "sell" : "buy", fund: e.fund, amount: e.amount, nav: e.nav, date: e.date, load_pct: e.load_pct };
        } else if (e.type === "cash") { EDIT.form = "cash"; EDIT.prefill = { amount: e.amount, date: e.date }; }
        else if (e.type === "dividend") { EDIT.form = "div"; EDIT.prefill = { symbol: e.symbol, net: e.net, date: e.date }; }
        renderEditor(); box.scrollIntoView({ block: "start", behavior: "smooth" });
      };
    });
    box.querySelectorAll("[data-del]").forEach(function (b) {
      b.onclick = function () {
        if (!confirm("Delete this transaction?")) return;
        try { Ledger.remove(LEDGER, +b.dataset.del); reset(); EDIT.form = "list"; saveLedger(); } catch (err) { fmsg("ed-msg", err.message, false); }
      };
    });
  }

  // ---- Data: prices, and your holdings in and out (like PK Wealth)
  function b64(u8) { var s = ""; for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]); return btoa(s); }
  function unb64(s) { var b = atob(s), u = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; }
  function passKey(pass, salt, iterations, use) {
    return crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveKey"]).then(function (base) {
      return crypto.subtle.deriveKey({ name: "PBKDF2", salt: salt, iterations: iterations, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, false, [use]);
    });
  }
  function backup(pass) {
    var stamp = todayISO();
    if (!pass) return Promise.resolve(download("psx-holdings-backup-" + stamp + ".json", JSON.stringify({ format: "psx-desk-backup", v: 1, enc: "none", ledger: LEDGER }), "application/json"));
    var salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12)), it = 310000;
    return passKey(pass, salt, it, "encrypt").then(function (k) {
      return crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, k, new TextEncoder().encode(JSON.stringify(LEDGER)));
    }).then(function (ct) {
      download("psx-holdings-backup-" + stamp + ".json", JSON.stringify({ format: "psx-desk-backup", v: 1, enc: "AES-256-GCM/PBKDF2-SHA256", iterations: it,
        salt: b64(salt), iv: b64(iv), data: b64(new Uint8Array(ct)) }), "application/json");
    });
  }
  /** A backup, a ledger.json from portfolio.py, or a trades CSV. Backups and ledgers replace; CSV rows are added. */
  function importText(text, pass) {
    var t = String(text).replace(/^﻿/, "").trim();
    if (t.charAt(0) !== "{") {
      var r = Ledger.importCSV(LEDGER, PRESETS, t);
      return saveLedger().then(function () {
        return "Added " + r.added + " trades" + (r.skipped ? ", skipped " + r.skipped + " already there" : "") + (r.errors.length ? "; problems: " + r.errors.slice(0, 5).join("; ") : "") + ".";
      });
    }
    var o = JSON.parse(t);
    var take = function (lg) {
      if (LEDGER.entries.length && !confirm("Replace the " + LEDGER.entries.length + " entries on this device with the " + lg.entries.length + " in the file?")) return "Nothing changed.";
      LEDGER = Ledger.importLedger(lg);
      return saveLedger().then(function () { return "Loaded " + LEDGER.entries.length + " entries."; });
    };
    if (o.format === "psx-desk-backup" && o.enc !== "none") {
      if (!pass) return Promise.reject(new Error("this backup is encrypted: type its passphrase in the box first"));
      return passKey(pass, unb64(o.salt), o.iterations, "decrypt").then(function (k) {
        return crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(o.iv) }, k, unb64(o.data));
      }).then(function (pt) { return take(JSON.parse(new TextDecoder().decode(pt))); }, function (e) {
        if (e && /entries/.test(e.message || "")) throw e;
        throw new Error("that passphrase didn't open the backup");
      });
    }
    return Promise.resolve(take(o.format === "psx-desk-backup" ? o.ledger : o));
  }
  var PASSBOX = "";   // the backup passphrase box keeps its text when the tab redraws (not stored anywhere)
  function holdingsIOHTML() {
    var n = LEDGER ? LEDGER.entries.length : 0;
    return '<h2 style="margin-top:18px">Your holdings</h2>' +
      (SOURCE === "sample" ? "<p>" + num(n) + " practice entries, kept in <b>this browser tab only</b>: they go when you exit the sample, and your own holdings are never touched. " +
        "Exports and backups below hold the practice portfolio.</p>" :
      "<p>" + num(n) + " entries, kept <b>only in this browser on this device</b> (IndexedDB). Nothing is uploaded: not to GitHub, not to anyone. " +
      "Another phone or computer has its own copy, so move them with a backup. Clearing this site's data in the browser erases them.</p>") +
      '<label class="small">Backup passphrase <input type="password" id="fd-pass" autocomplete="new-password" placeholder="for encrypted backups" style="width:100%;max-width:320px"></label>' +
      '<div class="row-actions"><button class="btn" id="fd-backup">Save backup</button><button class="btn ghost" id="fd-import">Restore or import…</button></div>' +
      '<div class="row-actions"><button class="btn ghost" id="fd-csv">Export trades CSV</button><button class="btn ghost" id="fd-ledger">Export ledger.json</button>' +
      '<button class="btn danger" id="fd-erase">Erase holdings on this device</button></div><p id="fd-msg"></p>' +
      '<p class="note"><b>Save backup</b>: everything, encrypted with the passphrase above (leave it empty for a plain file). <b>Restore or import</b> takes a backup, ' +
      "a <code>ledger.json</code> from <code>portfolio.py</code> (Termux or computer) or a trades CSV (<code>" + Ledger.FIELDS.join(",") + "</code>). " +
      "<b>ledger.json</b> goes the other way: put it in your <code>pkmarket/portfolio/</code> folder and the Python tools see the same holdings.</p>" +
      "";
  }
  function wireHoldingsIO() {
    $("fd-pass").value = PASSBOX;
    $("fd-pass").oninput = function () { PASSBOX = $("fd-pass").value; };
    $("fd-backup").onclick = function () { backup($("fd-pass").value).then(function () { fmsg("fd-msg", "Backup saved to your downloads.", true); }); };
    $("fd-csv").onclick = function () { download("psx-trades-" + todayISO() + ".csv", Ledger.exportCSV(LEDGER), "text/csv"); };
    $("fd-ledger").onclick = function () { download("ledger.json", JSON.stringify(LEDGER, null, 1), "application/json"); };
    $("fd-import").onclick = function () {
      var inp = document.createElement("input");
      inp.type = "file"; inp.accept = ".json,.csv,application/json,text/csv";
      inp.onchange = function () {
        var f = inp.files && inp.files[0]; if (!f) return;
        f.text().then(function (t) { return importText(t, $("fd-pass").value); })
          .then(function (m) { fmsg("fd-msg", m, true); }, function (e) { fmsg("fd-msg", "Couldn't import: " + e.message, false); });
      };
      inp.click();
    };
    $("fd-erase").onclick = function () {
      if (!confirm("Erase every holding and entry on this device? Save a backup first if unsure.")) return;
      LEDGER = Ledger.empty(); saveLedger().then(function () { fmsg("fd-msg", "Erased.", true); });
    };
  }
  function renderFeedData() {
    var st = FEED_ST || {}, ps = st.psx || {}, mf = st.mufap || {}, n = LEDGER.entries.length;
    var errs = (st.errors || []).slice(0, 4).map(function (e) { return "<li><span>" + esc(e.source) + "</span><span class='muted small'>" + esc(e.error) + "</span></li>"; }).join("");
    $("dt-card").innerHTML = privacyNote() + "<h2>Prices</h2>" +
      '<ul class="list"><li><span>Source</span><span>this site\'s feed (GitHub Action), decrypted on this device</span></li>' +
      "<li><span>PSX</span><span>" + num(ps.shares || 0) + " shares · " + esc(ps.first || "–") + " to " + esc(ps.last || "–") + " (" + num(ps.sessions || 0) + " sessions)</span></li>" +
      "<li><span>MUFAP</span><span>" + num(mf.funds || 0) + " funds · " + esc(mf.date || "–") + "</span></li>" +
      "<li><span>Feed updated</span><span>" + esc(ago(st.updated)) + "</span></li></ul>" +
      (errs ? '<p class="small muted">Last run had problems:</p><ul class="list">' + errs + "</ul>" : "") +
      '<div class="row-actions"><a class="btn" href="' + runUrl() + '" target="_blank" rel="noopener">Refresh prices now</a>' +
      '<button class="btn ghost" id="fd-lock">Lock this device</button></div>' +
      '<p class="note">Refresh opens the price workflow on GitHub: tap <b>Run workflow</b> (you need to be signed in as the repo owner). ' +
      "New prices arrive in 1–3 minutes; then reload this page. It also runs by itself on the schedule in <code>feed-settings.json</code> (weekdays through the day, and MUFAP NAVs in the evening). No token is ever stored on this site.</p>" +
      holdingsIOHTML() +
      '<p class="note">PSX market data is for personal use: don\'t republish it.</p>';
    wireHoldingsIO();
    $("fd-lock").onclick = function () { IDB.del("feedkey").then(function () { location.reload(); }); };
    if (location.protocol !== "file:") {
      $("dt-card").insertAdjacentHTML("beforeend", '<p class="note">Want to see what every tab can do? <button class="linkbtn" id="dt-sample">Try the sample data</button>. Your own data stays as it is.</p>');
      $("dt-sample").onclick = startSample;
    }
  }

  // ---------------------------------------------------------------- sample data
  // sample-data.json is a made-up market (tools/make_sample.py): sample companies, funds, a sample
  // portfolio and paper account, so every tab can be explored before loading your own data.
  // Sample mode lasts for this browser tab only (sessionStorage) and never touches your own data.
  function sampleFlag(on) {
    try { if (on === undefined) return sessionStorage.getItem("pkm_sample") === "1";
      if (on) sessionStorage.setItem("pkm_sample", "1"); else sessionStorage.removeItem("pkm_sample"); } catch (e) { return false; }
  }
  function startSample() { sampleFlag(true); location.reload(); }
  function exitSample() { sampleFlag(false); location.reload(); }
  function fromSample() {
    return fetch("sample-data.json", { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(r.status + " " + r.statusText); return r.json();
    }).then(function (d) {
      if (!validData(d)) throw new Error("not dashboard data");
      SOURCE = "sample"; window.PKM_DATA = d; $("tabs").hidden = false; document.querySelector("main").hidden = false;
      $("loader").hidden = true; return start(d);
    }).catch(function (e) { sampleFlag(false); showLoader("The sample data couldn't load (" + e.message + ")."); });
  }
  function sampleBar() {
    var el = $("fresh"), S = D.sample || {};
    el.hidden = false; el.className = "fresh sample";
    el.innerHTML = "<b>Sample data.</b> " + esc(S.note || "Real PSX companies and MUFAP fund names with made-up prices: for trying the dashboard, not for decisions.") +
      " Not real PSX or MUFAP prices, and not advice." + (S.as_of ? " Prices to " + esc(S.as_of) + "." : "") +
      '<div class="row-actions"><button class="btn" id="sb-pick">Load my data</button>' +
      '<button class="btn ghost" id="sb-exit">Exit sample</button></div>';
    $("sb-pick").onclick = pickFile;
    // A sample file you exported and imported again is kept on the device: "Exit" forgets it there.
    $("sb-exit").onclick = SOURCE === "sample" ? exitSample : function () { IDB.del("data").then(function () { location.reload(); }); };
    $("livebar").hidden = true;
  }
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(function () {});
  if (window.PKM_DATA) { SOURCE = "file"; start(window.PKM_DATA); }
  else if (sampleFlag()) fromSample();
  else fetch("data.json", { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error(r.status + " " + r.statusText); return r.json();
  }).then(function (d) { SOURCE = "server"; return start(d); }).catch(function (e) {
    // A 404 is normal on GitHub Pages (the repo never holds data): no need to mention it.
    startWeb(location.protocol === "file:" || /^404\b/.test(e.message) ? "" : "No data.json next to this page (" + e.message + ").");
  });
})();
