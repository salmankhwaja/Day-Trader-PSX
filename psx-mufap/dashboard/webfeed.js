/* webfeed.js: the price feed the GitHub Action publishes (tools/web_feed.py), read in the browser.
 *
 * feed/status.json is public (when it ran, how much it has; no prices). Everything from PSX is
 * encrypted: AES-256-GCM, key = PBKDF2-SHA256(passphrase, feed/key.json salt). The key is derived
 * here, on the device, and can be kept in this browser's IndexedDB as a non-extractable key (the
 * passphrase itself is never stored). build() turns the feed plus your browser ledger into the
 * same data shape as dashboard.py's data.json, so every tab works unchanged.
 * Pure apart from fetch/crypto; build() also runs in Node (tests).
 */
(function (root) {
  "use strict";
  var BASE = "../../feed/";   // the dashboard lives at <site>/psx-mufap/dashboard/, the feed at <site>/feed/
  var CHECK = "psx-feed-ok";
  var subtle = function () { return root.crypto && root.crypto.subtle; };
  var unb64 = function (s) { var b = atob(s), u = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; };

  function getJSON(name, fresh) {
    return fetch(BASE + name, { cache: fresh ? "no-store" : "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(name + ": " + r.status);
      return r.json();
    });
  }
  function status() { return getJSON("status.json", true).catch(function () { return null; }); }

  function gunzip(buf) {
    if (typeof DecompressionStream === "undefined") return Promise.reject(new Error("this browser can't unpack the feed (update it)"));
    return new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
  }
  function open(doc, key) {
    return subtle().decrypt({ name: "AES-GCM", iv: unb64(doc.iv) }, key, unb64(doc.data)).then(function (pt) {
      return /\+gzip$/.test(doc.enc || "") ? gunzip(pt) : pt;
    }).then(function (pt) { return JSON.parse(new TextDecoder().decode(pt)); });
  }
  /** The passphrase -> a non-extractable AES key, checked against key.json. Throws on a wrong passphrase. */
  function unlock(passphrase) {
    return getJSON("key.json", true).then(function (kd) {
      return subtle().importKey("raw", new TextEncoder().encode(passphrase), "PBKDF2", false, ["deriveKey"]).then(function (base) {
        return subtle().deriveKey({ name: "PBKDF2", salt: unb64(kd.salt), iterations: kd.iterations, hash: "SHA-256" },
          base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
      }).then(function (key) {
        return open(kd.check, key).then(function (t) {
          if (t !== CHECK) throw new Error("wrong passphrase");
          return { key: key, salt: kd.salt };
        }, function () { throw new Error("wrong passphrase"); });
      });
    });
  }
  /** A stored key still matches the feed (the passphrase may have been changed since). */
  function stillValid(stored) {
    return getJSON("key.json", true).then(function (kd) {
      if (kd.salt !== stored.salt) return false;
      return open(kd.check, stored.key).then(function (t) { return t === CHECK; }, function () { return false; });
    });
  }
  /** {summary, months: {YYYY-MM: {syms, days}}, navMonths: {YYYY-MM: {syms: fund names, days}}} */
  function load(key, st) {
    var months = ((st && st.psx && st.psx.months) || []).slice(), navs = ((st && st.mufap && st.mufap.months) || []).slice();
    var get = function (f) { return getJSON(f).then(function (d) { return open(d, key); }); };
    return Promise.all([get("summary.enc.json")].concat(months.map(function (m) { return get("psx/" + m + ".enc.json"); }))
      .concat(navs.map(function (m) { return get("mufap/" + m + ".enc.json").catch(function () { return null; }); }))).then(function (all) {
      var out = { summary: all[0], months: {}, navMonths: {} };
      months.forEach(function (m, i) { out.months[m] = all[i + 1]; });
      navs.forEach(function (m, i) { if (all[months.length + 1 + i]) out.navMonths[m] = all[months.length + 1 + i]; });
      return out;
    });
  }

  // ------------------------------------------------------------- building the dashboard's data
  function history(months) {
    var dates = [], rows = {};
    Object.keys(months).sort().forEach(function (m) {
      var M = months[m];
      Object.keys(M.days).sort().forEach(function (d) {
        dates.push(d);
        var day = M.days[d];
        M.syms.forEach(function (s, i) {
          var c = day.c[i];
          if (c != null) (rows[s] = rows[s] || []).push({ date: d, close: c, volume: day.v[i] || 0 });
        });
      });
    });
    return { dates: dates, rows: rows };
  }

  /** feed {summary, months} + ledger -> data in dashboard.py's data.json shape. L = Ledger module. */
  function build(feed, lg, L, today, opts) {
    var S0 = feed.summary, H = history(feed.months), D = {};
    Object.keys(S0).forEach(function (k) { D[k] = S0[k]; });
    today = today || new Date().toISOString().slice(0, 10);
    D.calendar = H.dates;
    D.series = {};
    var want = {};
    (S0.stocks || []).forEach(function (s) { want[s.symbol] = 1; });
    if (S0.benchmark && S0.benchmark.symbol) want[S0.benchmark.symbol] = 1;
    lg.entries.forEach(function (e) { if (e.symbol) want[e.symbol] = 1; });
    var idx = {};
    H.dates.forEach(function (d, i) { idx[d] = i; });
    Object.keys(want).forEach(function (s) {
      var arr = new Array(H.dates.length).fill(null);
      (H.rows[s] || []).forEach(function (r) { arr[idx[r.date]] = r.close; });
      D.series[s] = arr;
    });
    D.portfolio = null; D.proposal = null; D.source = "feed";
    D.mine = null;
    var rowsOf = function (s) { return H.rows[s] || []; };
    var owned = applyLedger(D, lg, L, {
      S: settingsFor(S0, opts && opts.profile), rowsOf: rowsOf, ideas: S0.ideas || [], fundIndex: S0.fund_index || (S0.web || {}).fund_index || {},
      categories: (S0.funds || {}).categories, bench3m: ((S0.benchmark || {}).metrics || {})["3m"], today: today, advice_date: S0.generated,
      profile: (opts && opts.profile) || ((S0.web || {}).profile)
    });
    var watch = {};
    (lg.watchlist || []).forEach(function (s) { watch[s] = 1; });
    var bySym = {};
    (D.stocks || []).forEach(function (s) { bySym[s.symbol] = s; });
    (D.stocks || []).forEach(function (x) { x.owned = !!owned[x.symbol]; x.held = false; x.watch = !!watch[x.symbol]; });
    ((D.market || {}).rows || []).forEach(function (x) { x.owned = !!owned[x.symbol]; x.watch = !!watch[x.symbol]; });
    (D.dividend_calendar || []).forEach(function (x) { x.held = !!owned[x.symbol]; });
    D.owned_unlisted = Object.keys(owned).filter(function (x) { return !bySym[x]; });
    return D;
  }

  /** The settings the advice engine uses for a risk appetite: your own (with any overrides) when it is
   *  the profile in your config, else that profile's published values. data = data.json or the feed summary. */
  function settingsFor(data, profile) {
    var W = (data && data.web) || {}, base = (data && data.settings) || W.settings || {};
    if (!profile || profile === W.profile || !(W.profiles || {})[profile]) return Object.assign({}, base);
    return Object.assign({}, base, W.profiles[profile]);
  }

  /** Recompute "My portfolio" (D.mine) and portfolio risk from a ledger, in the browser: the same maths as
   *  portfolio.py / advice.py (ledger.js). ctx: S settings, rowsOf(sym) -> [{date, close}] oldest first,
   *  ideas (market-wide buy ideas with entry), fundIndex, categories, bench3m, today, advice_date, profile.
   *  Returns {symbol: true} for the shares held. */
  function applyLedger(D, lg, L, ctx) {
    var S = ctx.S, rowsOf = ctx.rowsOf, owned = {}, bySym = {}, today = ctx.today;
    (D.stocks || []).forEach(function (s) { bySym[s.symbol] = s; });
    D.mine = null;
    if (!lg || !lg.entries || !lg.entries.length) return owned;
    var priceOf = function (s) { var r = rowsOf(s); return r.length ? { price: r[r.length - 1].close, date: r[r.length - 1].date, source: "close", time: "15:30" } : null; };
    var navOf = function (f) { var x = (ctx.fundIndex || {})[f]; return x ? { nav: x.nav, date: x.date, category: x.category } : null; };
    var s = L.summary(lg, priceOf, navOf, today);
    s.holdings.forEach(function (p) { owned[p.symbol] = 1; });
    var rv = L.review(lg, s, rowsOf, S, ctx.bench3m, function (sym) { return (bySym[sym] || {}).payouts || []; }, today);
    var rvBy = {};
    rv.forEach(function (r) { rvBy[r.symbol] = r; });
    // Buy ideas keep their backtested entry; the stop and target follow the chosen risk appetite.
    var ideas = (ctx.ideas || []).map(function (i0) {
      var i = Object.assign({}, i0), rows = rowsOf(i.symbol);
      if (rows.length && i.entry > 0) {
        var sf = L.stopFor(rows, i.entry, i.price_date || rows[rows.length - 1].date, S);
        if (sf && sf.stop > 0 && sf.stop < i.entry) {
          i.stop = sf.stop; i.target = sf.target; i.risk_per_share = Math.round((i.entry - sf.stop) * 100) / 100; i.stop_pct = sf.stop / i.entry - 1;
        }
      }
      return i;
    });
    var sized = L.sizeIdeas(ideas, lg, s, rv, S, 3);
    var r4 = function (x) { return x == null ? null : Math.round(x * 10000) / 10000; };
    var fees = {};
    lg.entries.forEach(function (e) {
      if ((e.type !== "buy" && e.type !== "sell") || /bonus issue/.test(e.note || "")) return;
      var f = fees[e.broker] = fees[e.broker] || { trades: 0, turnover: 0, commission: 0, taxes: 0, other: 0, estimated: 0 };
      f.trades++; f.turnover += e.qty * e.price; f.commission += e.commission; f.taxes += e.taxes; f.other += e.other;
      f.estimated += e.commission_estimated ? 1 : 0;
    });
    D.mine = {
      second_opinion: null, source: "browser", profile: ctx.profile || null,
      tickets: L.tickets(rv, sized.ideas, lg, S),
      summary: { value: s.value, cost: s.cost, unrealised: s.unrealised, realised: s.realised, dividends: s.dividends, fees: s.fees, cash: s.cash },
      funds: L.reviewFunds(s.funds, ctx.fundIndex, ctx.categories).map(function (f) { f.unrealised_pct = r4(f.unrealised_pct); return f; }),
      holdings: s.holdings.map(function (p) {
        var r = rvBy[p.symbol] || {}, i = bySym[p.symbol] || {};
        return { symbol: p.symbol, qty: p.qty, avg_cost: Math.round(p.avg_cost * 100) / 100, cost: Math.round(p.cost * 100) / 100, price: p.price,
          price_date: p.price_date, value: p.value, unrealised: p.unrealised, unrealised_pct: r4(p.unrealised_pct), dividends: p.dividends,
          brokers: p.brokers, first_buy: p.first_buy, days_held: p.days_held, sector: i.sector, shariah: i.shariah, action: r.action, why: r.why,
          notes: r.notes || [], stop: r.stop, stop_source: r.stop_source, target: r.target, weight: r4(r.weight), trim_qty: r.trim_qty, calc: r.calc,
          first_buy_time: p.first_buy_time, price_source: p.price_source, price_time: p.price_time, net_pl: p.net_pl, net_pl_pct: r4(p.net_pl_pct),
          status: p.status, theirs: null,
          lots: p.lots.map(function (l) { return { date: l.date, time: l.time, qty: l.qty, broker: l.broker, unit_cost: Math.round(l.unit_cost * 10000) / 10000, cost: l.cost, net_pl: l.net_pl, status: l.status }; }) };
      }),
      sales: s.sales.slice(-100),
      fees: Object.keys(fees).sort().map(function (k) { return Object.assign({ broker: k }, fees[k]); }),
      dividends: lg.entries.filter(function (e) { return e.type === "dividend"; }).slice(-100),
      buy_ideas: sized.ideas, buy_note: sized.note || null, advice_date: ctx.advice_date, settings: S
    };
    var total = s.value + (s.cash || 0);
    // When no new share fits (max_holdings reached) sizeIdeas returns only a note: work the risk out here.
    var openR = sized.open_risk != null ? sized.open_risk : Math.round(rv.reduce(function (t, r) {
      return t + (r.price && r.stop != null && r.price > r.stop ? r.qty * (r.price - r.stop) : 0); }, 0) * 100) / 100;
    var budget = sized.risk_budget != null ? sized.risk_budget : Math.round(S.max_open_risk_pct * total * 100) / 100;
    D.risk = Object.assign({}, D.risk || {}, { portfolio: { profile: ctx.profile || (D.risk || {}).profile, total: total, cash: s.cash,
      open_risk: openR, open_risk_pct: total ? openR / total : null, risk_budget: budget } });
    return owned;
  }

  /** rowsOf for a data.json: its series are closes aligned with its calendar. */
  function rowsFromSeries(D) {
    var cache = {};
    return function (sym) {
      if (cache[sym]) return cache[sym];
      var v = (D.series || {})[sym], cal = D.calendar || [], out = [];
      if (v) for (var i = 0; i < cal.length; i++) if (v[i] != null) out.push({ date: cal[i], close: v[i] });
      if (!out.length) { var st = (D.stocks || []).find(function (x) { return x.symbol === sym; }); if (st && st.close) out.push({ date: st.last_date, close: st.close }); }
      return (cache[sym] = out);
    };
  }

  /** A share's close on a date, or on the last trading day before it (weekend, holiday) up to 10 days
   *  back: {date, close} or null. From the feed's monthly files, else a data.json's series/calendar.
   *  Also a fund's NAV from the monthly NAV files (same shape, fund names as syms): pass keepCase. */
  function closeOn(months, D, sym, date, keepCase) {
    sym = String(sym || "").trim();
    if (!keepCase) sym = sym.toUpperCase();
    if (!sym || !/^\d{4}-\d{2}-\d{2}$/.test(date || "")) return null;
    var earliest = new Date(Date.parse(date + "T00:00:00Z") - 10 * 864e5).toISOString().slice(0, 10), i, d;
    var ms = Object.keys(months || {}).filter(function (m) { return m <= date.slice(0, 7) && m >= earliest.slice(0, 7); }).sort().reverse();
    for (var a = 0; a < ms.length; a++) {
      var M = months[ms[a]], k = (M.syms || []).indexOf(sym);
      if (k < 0) continue;
      var days = Object.keys(M.days || {}).filter(function (x) { return x <= date && x >= earliest; }).sort().reverse();
      for (i = 0; i < days.length; i++) { var c = M.days[days[i]].c[k]; if (c != null) return { date: days[i], close: c }; }
    }
    var v = D && (D.series || {})[sym], cal = (D && D.calendar) || [];
    if (v) for (i = cal.length - 1; i >= 0; i--) { d = cal[i]; if (d <= date && d >= earliest && v[i] != null) return { date: d, close: v[i] }; }
    return null;
  }

  var api = { BASE: BASE, closeOn: closeOn, status: status, unlock: unlock, stillValid: stillValid, load: load, open: open, history: history, build: build, applyLedger: applyLedger, settingsFor: settingsFor, rowsFromSeries: rowsFromSeries };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WebFeed = api;
})(typeof self !== "undefined" ? self : this);
