/* ledger.js: your PSX and MUFAP holdings, kept in the browser. Pure; works in the browser and in Node.
 *
 * The ledger has exactly the shape of the Python tools' portfolio/ledger.json, so a ledger moves
 * between the website and portfolio.py (Termux or computer) without conversion. The arithmetic
 * follows portfolio.py and advice.py line for line, and tests/test_all.py checks the two agree:
 *   lots        FIFO per (symbol, broker); average cost includes buying charges
 *   GREEN/RED   selling every lot at the price now, after estimated selling charges
 *   stops       stop_atr_mult x average daily move, min_stop_pct..max_stop_pct below entry, trailing
 *   actions     SELL (at/below stop), TRIM (over max_position_pct), REVIEW (below both averages and
 *               lagging KSE-100 over 3 months), HOLD
 */
(function (root) {
  "use strict";
  var FIELDS = ["date", "side", "symbol", "qty", "price", "broker", "commission", "taxes", "other", "note", "stop", "time"];
  var r2 = function (x) { return Math.round(x * 100) / 100; };
  var r4 = function (x) { return Math.round(x * 10000) / 10000; };

  function empty() { return { version: 1, brokers: {}, default_broker: null, entries: [], stops: {}, next_id: 1 }; }
  function normalise(lg) {
    var e = empty();
    lg = lg || {};
    Object.keys(e).forEach(function (k) { if (lg[k] == null) lg[k] = e[k]; });
    return lg;
  }

  // ------------------------------------------------------------- brokers (brokers.json presets)
  function presetBroker(presets, key) {
    var bk = presets.brokers[String(key).toLowerCase()];
    if (!bk) throw new Error("no broker preset " + key);
    var b = {};
    ["sales_tax_pct", "cvt_pct", "cdc_per_share", "levies_pct"].forEach(function (k) { if (presets._defaults[k] != null) b[k] = presets._defaults[k]; });
    Object.keys(bk).forEach(function (k) { if (["name", "confidence", "source"].indexOf(k) < 0) b[k] = bk[k]; });
    b.preset = String(key).toLowerCase(); b.full_name = bk.name; b.source = bk.source; b.confidence = bk.confidence; b.as_of = presets._as_of;
    return b;
  }
  function tiersOf(b) {
    if (b.tiers && b.tiers.length) return b.tiers;
    return [{ max_price: null, per_share: b.per_share != null ? +b.per_share : (b.commission_pct == null ? 0.03 : 0), pct: b.commission_pct != null ? +b.commission_pct : 0.15 }];
  }
  /** [commission, taxes, other] from a broker's schedule (portfolio.estimate_charges). */
  function estimateCharges(b, qty, price, side) {
    b = b || {};
    var value = qty * price, tier = null, ts = tiersOf(b);
    for (var i = 0; i < ts.length; i++) { tier = ts[i]; if (tier.max_price != null && price <= +tier.max_price) break; }
    var commission = Math.max(qty * +(tier.per_share || 0), value * +(tier.pct || 0) / 100, +(b.min_commission || 0));
    var taxes = commission * +(b.sales_tax_pct || 0) / 100;
    if (side === "buy") taxes += value * +(b.cvt_pct || 0) / 100;
    var other = qty * +(b.cdc_per_share || 0) + value * +(b.levies_pct || 0) / 100 + value * +(b.other_pct || 0) / 100;
    return [r2(commission), r2(taxes), r2(other)];
  }
  function sumCharges(b, qty, price, side) { var c = estimateCharges(b, qty, price, side); return c[0] + c[1] + c[2]; }

  function addBroker(lg, presets, name, presetKey, makeDefault) {
    lg.brokers[name] = presetBroker(presets, presetKey || "psx-minimum");
    if (makeDefault || !lg.default_broker) lg.default_broker = name;
    return name;
  }
  function resolveBroker(lg, presets, name) {
    name = name || lg.default_broker;
    if (!name) throw new Error("add a broker first");
    var hit = Object.keys(lg.brokers).find(function (k) { return k.toLowerCase() === String(name).toLowerCase(); });
    if (hit) return hit;
    lg.brokers[name] = presetBroker(presets, "psx-minimum");
    lg.brokers[name].auto_added = true;
    return name;
  }

  // ------------------------------------------------------------- recording
  function stamp() { var d = new Date(); return d.toISOString().slice(0, 10) + " " + d.toTimeString().slice(0, 5); }
  function addEntry(lg, e) { e.id = lg.next_id; lg.next_id += 1; e.recorded = stamp(); lg.entries.push(e); return e; }
  function ordered(entries) {
    return entries.slice().sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : (a.time || "") < (b.time || "") ? -1 : (a.time || "") > (b.time || "") ? 1 : a.id - b.id;
    });
  }
  function checkDate(s) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s || "") || isNaN(new Date(s + "T00:00:00"))) throw new Error("date must be YYYY-MM-DD: " + s);
    return s;
  }
  function checkTime(t) {
    if (!t) return null;
    var m = String(t).match(/^(\d{1,2}):(\d{2})$/);
    if (!m || +m[1] > 23 || +m[2] > 59) throw new Error("time must be HH:MM (24-hour): " + t);
    return ("0" + m[1]).slice(-2) + ":" + m[2];
  }
  /** portfolio.record_trade: estimates missing charges, refuses a sale of shares not held then. */
  function recordTrade(lg, presets, t) {
    var side = String(t.side || "").toLowerCase();
    if (side !== "buy" && side !== "sell") throw new Error("side must be buy or sell");
    var symbol = String(t.symbol || "").trim().toUpperCase();
    if (!/^[A-Z0-9][A-Z0-9\-]*$/.test(symbol)) throw new Error("symbol? " + t.symbol);
    var broker = resolveBroker(lg, presets, t.broker);
    var qty = parseInt(String(t.qty).replace(/,/g, ""), 10), price = parseFloat(String(t.price).replace(/,/g, ""));
    if (!(qty > 0) || !(price > 0)) throw new Error("quantity and price must be positive");
    var b = lg.brokers[broker], est = estimateCharges(b, qty, price, side);
    var num = function (v) { return v === "" || v == null ? null : parseFloat(String(v).replace(/,/g, "")); };
    var c = num(t.commission), tx = num(t.taxes), o = num(t.other);
    if (c != null && tx == null) est[1] = r2(c * +(b.sales_tax_pct || 0) / 100 + (side === "buy" ? qty * price * +(b.cvt_pct || 0) / 100 : 0));
    var estimated = [["commission", c], ["taxes", tx], ["other", o]].filter(function (x) { return x[1] == null; }).map(function (x) { return x[0]; });
    var e = { type: side, date: checkDate(t.date), time: checkTime(t.time), symbol: symbol, qty: qty, price: price, broker: broker,
      commission: r2(c == null ? est[0] : c), taxes: r2(tx == null ? est[1] : tx), other: r2(o == null ? est[2] : o),
      commission_estimated: estimated.indexOf("commission") >= 0, estimated: estimated, note: t.note || "" };
    addEntry(lg, e);
    var bad = lots(lg).sales.find(function (x) { return x.unmatched; });
    if (bad) {
      lg.entries.pop(); lg.next_id -= 1;
      throw new Error("that would sell " + bad.symbol + " shares not held at " + bad.broker + " on " + bad.date + " (no short selling)");
    }
    var stop = num(t.stop);
    if (stop != null && side === "buy") {
      if (stop >= price) { lg.entries.pop(); lg.next_id -= 1; throw new Error("a stop-loss must be below the buy price"); }
      lg.stops[symbol] = stop;
    }
    return e;
  }
  function recordFund(lg, f) {
    var side = f.side === "sell" ? "fund_sell" : "fund_buy";
    var amount = parseFloat(String(f.amount).replace(/,/g, "")), nav = parseFloat(String(f.nav).replace(/,/g, ""));
    if (!(amount > 0) || !(nav > 0)) throw new Error("amount and NAV must be positive");
    var load = f.load_pct ? +f.load_pct : 0;
    var units = side === "fund_buy" ? amount * (1 - load / 100) / nav : amount / (nav * (1 - load / 100));
    var e = { type: side, date: checkDate(f.date), fund: String(f.fund).trim(), amount: r2(amount), nav: nav, units: r4(units),
      load_pct: load || null, nav_estimated: false, note: f.note || "" };
    if (side === "fund_buy") e.category = f.category || null;
    return addEntry(lg, e);
  }
  function recordCash(lg, amount, date, note) {
    amount = parseFloat(String(amount).replace(/,/g, ""));
    if (!amount) throw new Error("amount?");
    return addEntry(lg, { type: "cash", date: checkDate(date), amount: r2(amount), broker: lg.default_broker, note: note || "" });
  }
  function recordDividend(lg, symbol, net, date, note) {
    net = parseFloat(String(net).replace(/,/g, ""));
    if (!(net > 0)) throw new Error("net dividend received?");
    return addEntry(lg, { type: "dividend", date: checkDate(date), symbol: String(symbol).toUpperCase(), net: r2(net), gross: null, tax: null, note: note || "" });
  }
  function remove(lg, id) {
    var i = lg.entries.findIndex(function (e) { return e.id === id; });
    if (i < 0) return false;
    var e = lg.entries.splice(i, 1)[0];
    if (lots(lg).sales.some(function (x) { return x.unmatched; })) { lg.entries.splice(i, 0, e); throw new Error("a later sale needs those shares: delete the sale first"); }
    return true;
  }

  // ------------------------------------------------------------- lots and P/L (portfolio.lots / holdings)
  function days(a, b) { return Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 864e5); }
  function lots(lg) {
    var book = {}, sales = [];
    ordered(lg.entries).forEach(function (e) {
      var key = e.symbol + "\u0000" + e.broker, fees;
      if (e.type === "buy") {
        fees = e.commission + e.taxes + e.other;
        (book[key] = book[key] || []).push({ qty: e.qty, date: e.date, time: e.time || null, unit_cost: (e.qty * e.price + fees) / e.qty, price: e.price, id: e.id });
      } else if (e.type === "sell") {
        var q = book[key] || [];
        fees = e.commission + e.taxes + e.other;
        var proceeds = e.qty * e.price - fees, need = e.qty, cost = 0, dw = 0;
        while (need > 0 && q.length) {
          var lot = q[0], take = Math.min(need, lot.qty);
          cost += take * lot.unit_cost; dw += take * days(lot.date, e.date); lot.qty -= take; need -= take;
          if (lot.qty === 0) q.shift();
        }
        var sold = e.qty - need;
        sales.push({ id: e.id, date: e.date, symbol: e.symbol, broker: e.broker, qty: sold, price: e.price, proceeds: r2(proceeds), cost: r2(cost),
          fees: r2(fees), pnl: r2(proceeds - cost), pnl_pct: cost ? proceeds / cost - 1 : null, avg_days_held: sold ? Math.round(dw / sold) : null, unmatched: need });
      }
    });
    return { book: book, sales: sales };
  }
  function statusOf(net) { return net == null ? null : net > 0.005 ? "GREEN" : net < -0.005 ? "RED" : "FLAT"; }

  /** priceOf(symbol) -> {price, date, source:"close"|"live", time} or null. */
  function holdings(lg, priceOf, today) {
    var book = lots(lg).book, divs = {}, by = {};
    lg.entries.forEach(function (e) { if (e.type === "dividend") divs[e.symbol] = (divs[e.symbol] || 0) + e.net; });
    Object.keys(book).forEach(function (key) {
      var sym = key.split("\u0000")[0], broker = key.split("\u0000")[1];
      book[key].forEach(function (l) {
        if (l.qty <= 0) return;
        var p = by[sym] = by[sym] || { symbol: sym, qty: 0, cost: 0, brokers: {}, first_buy: l.date, first_buy_time: l.time, lots: [] };
        p.qty += l.qty; p.cost += l.qty * l.unit_cost; p.brokers[broker] = (p.brokers[broker] || 0) + l.qty;
        if (l.date + (l.time || "") < p.first_buy + (p.first_buy_time || "")) { p.first_buy = l.date; p.first_buy_time = l.time; }
        p.lots.push(Object.assign({}, l, { broker: broker }));
      });
    });
    return Object.keys(by).sort().map(function (sym) {
      var p = by[sym], q = priceOf(sym), px = q ? q.price : null;
      p.avg_cost = p.cost / p.qty;
      p.price = px; p.price_date = q ? q.date : null; p.price_source = q ? q.source || "close" : null; p.price_time = q ? q.time || "15:30" : null;
      p.value = px ? p.qty * px : null; p.unrealised = px ? p.value - p.cost : null; p.unrealised_pct = px && p.cost ? p.value / p.cost - 1 : null;
      var net = px ? 0 : null;
      p.lots.forEach(function (l) {
        l.cost = r2(l.qty * l.unit_cost);
        if (px) {
          l.net_pl = r2(l.qty * px - sumCharges(lg.brokers[l.broker], l.qty, px, "sell") - l.cost);
          l.net_pl_pct = l.cost ? l.net_pl / l.cost : null; net += l.net_pl;
        } else l.net_pl = l.net_pl_pct = null;
        l.status = statusOf(l.net_pl);
      });
      p.lots.sort(function (a, b) { return (a.date + (a.time || "")) < (b.date + (b.time || "")) ? -1 : 1; });
      p.net_pl = net != null ? r2(net) : null; p.net_pl_pct = net != null && p.cost ? p.net_pl / p.cost : null; p.status = statusOf(p.net_pl);
      p.dividends = r2(divs[sym] || 0); p.days_held = days(p.first_buy, today || new Date().toISOString().slice(0, 10));
      return p;
    });
  }
  /** navOf(fund) -> {nav, date, category} or null. Average-cost method, as portfolio.fund_holdings. */
  function fundHoldings(lg, navOf) {
    var pos = {}, realised = [];
    ordered(lg.entries).forEach(function (e) {
      if (e.type === "fund_buy") {
        var p = pos[e.fund] = pos[e.fund] || { fund: e.fund, units: 0, cost: 0, first_buy: e.date, category: e.category || null };
        p.units += e.units; p.cost += e.amount;
      } else if (e.type === "fund_sell") {
        var q = pos[e.fund];
        if (!q || q.units <= 1e-9) return;
        var cost = q.cost * Math.min(e.units, q.units) / q.units;
        q.units -= e.units; q.cost -= cost;
        realised.push({ id: e.id, date: e.date, fund: e.fund, proceeds: e.amount, cost: r2(cost), pnl: r2(e.amount - cost) });
      }
    });
    var out = Object.keys(pos).sort().filter(function (f) { return pos[f].units > 1e-6; }).map(function (f) {
      var p = pos[f], n = navOf(f);
      p.avg_nav = p.cost / p.units; p.nav = n ? n.nav : null; p.nav_date = n ? n.date : null;
      p.category = p.category || (n ? n.category : null);
      p.value = n ? r2(p.units * n.nav) : null; p.unrealised = n ? r2(p.value - p.cost) : null;
      p.unrealised_pct = n && p.cost ? p.value / p.cost - 1 : null;
      return p;
    });
    return { funds: out, realised: realised };
  }
  function cashBalance(lg) {
    if (!lg.entries.some(function (e) { return e.type === "cash"; })) return null;
    var bal = 0;
    lg.entries.forEach(function (e) {
      if (e.type === "cash") bal += e.amount;
      else if (e.type === "buy") bal -= e.qty * e.price + e.commission + e.taxes + e.other;
      else if (e.type === "sell") bal += e.qty * e.price - e.commission - e.taxes - e.other;
      else if (e.type === "dividend") bal += e.net;
      else if (e.type === "fund_buy") bal -= e.amount;
      else if (e.type === "fund_sell") bal += e.amount;
    });
    return r2(bal);
  }
  function summary(lg, priceOf, navOf, today) {
    var hs = holdings(lg, priceOf, today), sales = lots(lg).sales, fh = fundHoldings(lg, navOf);
    var fees = 0, divs = 0;
    lg.entries.forEach(function (e) {
      if (e.type === "buy" || e.type === "sell") fees += (e.commission || 0) + (e.taxes || 0) + (e.other || 0);
      if (e.type === "dividend") divs += e.net;
    });
    var value = hs.reduce(function (t, p) { return t + (p.value || p.cost); }, 0) + fh.funds.reduce(function (t, f) { return t + (f.value || f.cost); }, 0);
    var cost = hs.reduce(function (t, p) { return t + p.cost; }, 0) + fh.funds.reduce(function (t, f) { return t + f.cost; }, 0);
    return { holdings: hs, funds: fh.funds, sales: sales, fund_sales: fh.realised, value: r2(value), cost: r2(cost), unrealised: r2(value - cost),
      realised: r2(sales.reduce(function (t, s) { return t + s.pnl; }, 0) + fh.realised.reduce(function (t, s) { return t + s.pnl; }, 0)),
      dividends: r2(divs), fees: r2(fees), cash: cashBalance(lg) };
  }

  // ------------------------------------------------------------- stops and actions (advice.py)
  function volatility(closes, n, end) {
    end = end == null ? closes.length - 1 : end;
    if (end < 1) return null;
    var start = Math.max(1, end - n + 1), t = 0, k = 0;
    for (var i = start; i <= end; i++) { t += Math.abs(closes[i] - closes[i - 1]); k++; }
    return k ? t / k : null;
  }
  function sma(closes, n, end) {
    if (end + 1 < n) return null;
    var t = 0;
    for (var i = end - n + 1; i <= end; i++) t += closes[i];
    return t / n;
  }
  /** rows: [{date, close}] oldest first. advice.stop_for. */
  function stopFor(rows, entry, entryDate, S) {
    var closes = rows.map(function (r) { return r.close; });
    if (!closes.length) return null;
    var k = S.stop_atr_mult, cap = S.max_stop_pct, tr = S.target_r, floor = S.min_stop_pct, n = S.vol_window || 14;
    var idx = -1;
    rows.forEach(function (r, i) { if (r.date <= entryDate) idx = i; });
    if (idx < 0) idx = rows.length - 1;
    var vEntry = (idx >= 5 ? volatility(closes, n, idx) : null) || volatility(closes, n) || 0;
    var initial = Math.min(Math.max(entry - k * vEntry, entry * (1 - cap)), entry * (1 - floor));
    var since = rows.filter(function (r) { return r.date >= entryDate; }).map(function (r) { return r.close; });
    if (!since.length) since = [closes[closes.length - 1]];
    var vNow = volatility(closes, n) || 0, hi = Math.max.apply(null, since);
    var trailing = Math.min(hi - k * vNow, hi * (1 - floor)), stop = Math.max(initial, trailing);
    return { stop: r2(stop), initial: r2(initial), trailing: r2(trailing), target: r2(entry + tr * (entry - initial)), volatility: r2(vNow),
      stop_pct: closes[closes.length - 1] ? stop / closes[closes.length - 1] - 1 : null };
  }
  function priceCalc(b, qty, price, stop, target, buying) {
    if (!qty || price == null || stop == null || target == null) return null;
    var buyFees = buying ? sumCharges(b, qty, price, "buy") : 0;
    var loss = price > stop ? qty * (price - stop) + buyFees + sumCharges(b, qty, stop, "sell") : 0;
    var gain = qty * (target - price) - buyFees - sumCharges(b, qty, target, "sell");
    return { qty: qty, price: r2(price), stop: r2(stop), target: r2(target), value: r2(qty * price), buy_fees: r2(buyFees),
      loss_at_stop: r2(loss), gain_at_target: r2(gain), stop_move_pct: stop / price - 1, target_move_pct: target / price - 1,
      reward_risk: loss > 0 ? r2(gain / loss) : null, breakeven_win_rate: loss > 0 && gain > 0 ? loss / (loss + gain) : null,
      breakeven_price: r2(price + (buyFees + sumCharges(b, qty, price, "sell")) / qty) };
  }
  function pct1(x) { return (x >= 0 ? "+" : "") + (100 * x).toFixed(1) + "%"; }
  /** advice.review_holdings. rowsOf(sym) -> [{date, close}]; bench3m = KSE-100 3-month return. */
  function review(lg, s, rowsOf, S, bench3m, payoutsOf, today) {
    var total = s.value + (s.cash || 0), soon = new Date(new Date(today + "T00:00:00").getTime() + 30 * 864e5).toISOString().slice(0, 10);
    var out = s.holdings.map(function (p) {
      var sym = p.symbol, r = { symbol: sym, qty: p.qty, avg_cost: r2(p.avg_cost), price: p.price, status: p.status, net_pl: p.net_pl,
        net_pl_pct: p.net_pl_pct, price_date: p.price_date, value: p.value, unrealised_pct: p.unrealised_pct, notes: [] };
      var rows = rowsOf(sym) || [];
      if (!rows.length) { r.action = "NO DATA"; r.why = "no prices for " + sym + " in the feed yet"; r.stop = lg.stops[sym]; return r; }
      var st = stopFor(rows, p.avg_cost, p.first_buy, S), own = lg.stops[sym];
      Object.assign(r, st);
      if (own != null) { r.stop = own; r.stop_source = "yours"; } else r.stop_source = st.trailing > st.initial ? "trailing" : "initial";
      var closes = rows.map(function (x) { return x.close; }), px = closes[closes.length - 1];
      var weight = total ? (p.value || 0) / total : 0;
      r.weight = weight;
      var s50 = sma(closes, S.trend_fast || 50, closes.length - 1), s200 = sma(closes, S.trend_slow || 200, closes.length - 1);
      var down = s50 != null && s200 != null && px < s50 && px < s200;
      var r3 = closes.length > 64 ? closes[closes.length - 1] / closes[closes.length - 64] - 1 : null;
      var lag = r3 != null && bench3m != null ? r3 - bench3m : null, maxw = S.max_position_pct;
      if (px <= r.stop) { r.action = "SELL"; r.why = "closed at " + px.toFixed(2) + ", at or below the stop of " + r.stop.toFixed(2) + " (" + r.stop_source + ")"; }
      else if (weight > maxw && total) {
        var excess = Math.max(1, Math.floor(((weight - maxw) * total) / px));
        r.action = "TRIM"; r.why = Math.round(100 * weight) + "% of the portfolio (limit " + Math.round(100 * maxw) + "%): sell about " + excess; r.trim_qty = excess;
      } else if (down && lag != null && lag < -(S.review_lag_pct || 0.05)) {
        r.action = "REVIEW"; r.why = "below its " + (S.trend_fast || 50) + "- and " + (S.trend_slow || 200) + "-day averages and " + pct1(-lag) + " behind KSE-100 over 3 months";
      } else {
        r.action = "HOLD"; r.why = pct1(px / r.stop - 1) + " above the stop of " + r.stop.toFixed(2);
        if (px >= st.target) r.notes.push("target " + st.target.toFixed(2) + " reached: consider taking some profit or keeping the trailing stop");
      }
      var bk = Object.keys(p.brokers || {}).sort(function (a, b) { return p.brokers[b] - p.brokers[a]; })[0] || lg.default_broker;
      r.broker = bk;
      var b = lg.brokers[bk];
      r.calc = priceCalc(b, p.qty, px, r.stop, st.target, false);
      if (r.calc) {
        var sellNow = sumCharges(b, p.qty, px, "sell");
        Object.assign(r.calc, { held: true, avg_cost: r2(p.avg_cost), vs_cost_now: r2(p.qty * (px - p.avg_cost) - sellNow),
          vs_cost_at_stop: r2(p.qty * (r.stop - p.avg_cost) - sumCharges(b, p.qty, r.stop, "sell")), breakeven_price: r2(p.avg_cost + sellNow / p.qty) });
      }
      (payoutsOf ? payoutsOf(sym) : []).some(function (pay) {
        if (pay.bc_from && today <= pay.bc_from && pay.bc_from <= soon && /\(D\)/.test(pay.details || "")) {
          r.notes.push("book closure " + pay.bc_from + " for " + pay.details + ": selling before then gives up this dividend"); return true;
        }
        return false;
      });
      return r;
    });
    var order = { SELL: 0, TRIM: 1, REVIEW: 2, "NO DATA": 3, HOLD: 4 };
    return out.sort(function (a, b) { return (order[a.action] - order[b.action]) || (a.symbol < b.symbol ? -1 : 1); });
  }
  function openRisk(rv) {
    return r2(rv.reduce(function (t, r) { return t + (r.price && r.stop != null && r.price > r.stop ? r.qty * (r.price - r.stop) : 0); }, 0));
  }
  /** Size the feed's market-wide buy ideas to this ledger (advice.size_for). */
  function sizeIdeas(ideas, lg, s, rv, S, n) {
    var held = {}; s.holdings.forEach(function (p) { held[p.symbol] = 1; });
    var capital = s.value + (s.cash || 0), slots = Math.floor(S.max_holdings) - Object.keys(held).length;
    if (slots <= 0) return { ideas: [], note: "you already hold " + Object.keys(held).length + " shares, the most your style allows" };
    var riskLeft = capital ? S.max_open_risk_pct * capital - openRisk(rv) : null;
    var spendable = s.cash != null ? s.cash - S.cash_reserve_pct * capital : null, b = lg.brokers[lg.default_broker], out = [];
    (ideas || []).forEach(function (i0) {
      if (held[i0.symbol] || out.length >= Math.min(n || 3, slots)) return;
      var i = Object.assign({}, i0, { qty: null }), risk = i.entry - i.stop;
      if (capital && risk > 0) {
        var lim = { "risk per trade": Math.floor(capital * S.risk_per_trade / risk), "max position": Math.floor(capital * S.max_position_pct / i.entry) };
        if (spendable != null) lim["cash after reserve"] = Math.floor(Math.max(spendable, 0) / (i.entry * 1.005));
        if (riskLeft != null) lim["open-risk budget"] = Math.floor(Math.max(riskLeft, 0) / risk);
        var bind = Object.keys(lim).reduce(function (a, k) { return lim[k] < lim[a] ? k : a; }), qty = lim[bind];
        i.limited_by = bind;
        if (qty > 0) {
          var fees = sumCharges(b, qty, i.entry, "buy");
          Object.assign(i, { qty: qty, cost: r2(qty * i.entry + fees), est_fees: r2(fees), broker: lg.default_broker, risk_pkr: r2(qty * risk),
            calc: priceCalc(b, qty, i.entry, i.stop, i.target, true) });
          if (spendable != null) spendable -= i.cost;
          if (riskLeft != null) riskLeft -= i.risk_pkr;
        }
      }
      out.push(i);
    });
    return { ideas: out, open_risk: openRisk(rv), risk_budget: r2(S.max_open_risk_pct * capital) };
  }
  /** advice.order_tickets: what to type into the broker's app. Nothing is ever sent. */
  function tickets(rv, ideas, lg, S) {
    var gap = S.stop_limit_gap || 0.01, out = [];
    var down = function (p) { return Math.floor(p / 0.01 + 1e-9) * 0.01; };
    var validity = function (bk) { var v = (lg.brokers[bk] || {}).stop_validity; return v === "day" ? "today only: place it again each trading morning" : v === "gtc" ? "until cancelled" : "check how long your broker's app keeps it"; };
    rv.forEach(function (r) {
      if (r.price == null) return;
      var bk = r.broker || lg.default_broker;
      if (r.action === "SELL") { out.push({ symbol: r.symbol, broker: bk, side: "SELL", type: "market", qty: r.qty, why: "at or below its stop", validity: "today" }); return; }
      if (r.action === "TRIM" && r.trim_qty) out.push({ symbol: r.symbol, broker: bk, side: "SELL", type: "limit", qty: r.trim_qty, limit: r2(r.price), why: "trim to max_position_pct", validity: "today" });
      if (r.stop && r.stop < r.price) out.push({ symbol: r.symbol, broker: bk, side: "SELL", type: "stop-loss", qty: r.qty, trigger: r2(r.stop), limit: r2(down(r.stop * (1 - gap))), why: "protect the holding (" + (r.stop_source || "") + " stop)", validity: validity(bk) });
      if (r.target && r.target > r.price) out.push({ symbol: r.symbol, broker: bk, side: "SELL", type: "limit (take profit, optional)", qty: r.qty, limit: r2(r.target), why: "target", validity: "your choice" });
    });
    ideas.forEach(function (i) {
      if (!i.qty) return;
      var bk = i.broker || lg.default_broker;
      out.push({ symbol: i.symbol, broker: bk, side: "BUY", type: "limit", qty: i.qty, limit: r2(i.entry), why: "buy idea (check the live price first)", validity: "today" });
      out.push({ symbol: i.symbol, broker: bk, side: "SELL", type: "stop-loss (after the buy fills)", qty: i.qty, trigger: r2(i.stop), limit: r2(down(i.stop * (1 - gap))), why: "protect the new position", validity: validity(bk) });
    });
    return out;
  }
  /** funds.review: HOLD, or REVIEW in the bottom third of its MUFAP category. index = feed fund_index
   *  {fund: {nav, date, category, rank, of}}; cats = the funds table (for the category leaders). */
  function reviewFunds(funds, index, cats) {
    return funds.map(function (f) {
      var x = (index || {})[f.fund];
      if (!x || !x.rank) return Object.assign(f, { action: "NO DATA", why: "not ranked in today's MUFAP table" });
      var rank = 1 - (x.rank - 1) / Math.max(x.of - 1, 1), c = cats && cats[x.category];
      var leaders = (c ? c.funds : []).slice(0, 3).map(function (y) { return y.fund; }).filter(function (y) { return y !== f.fund; }).slice(0, 2);
      return Object.assign(f, rank < 1 / 3 ? { action: "REVIEW", why: "in the bottom 33% of " + x.category + " on 30-day, 90-day and 1-year returns; leaders: " + leaders.join(", ") }
        : { action: "HOLD", why: "ranked " + x.rank + " of " + x.of + " in " + x.category });
    });
  }

  // ------------------------------------------------------------- import / export
  function csvEsc(v) { v = v == null ? "" : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function parseCSV(text) {
    var rows = [], row = [], cur = "", q = false;
    text = String(text).replace(/^﻿/, "");
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (q) { if (ch === '"' && text[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
      else if (ch === '"') q = true;
      else if (ch === ",") { row.push(cur); cur = ""; }
      else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(cur); rows.push(row); row = []; cur = ""; }
      else cur += ch;
    }
    if (cur || row.length) { row.push(cur); rows.push(row); }
    return rows.filter(function (r) { return r.some(function (c) { return c.trim(); }); });
  }
  /** Trades CSV, the same columns as `portfolio.py export` / `import`. */
  function exportCSV(lg) {
    var lines = [FIELDS.join(",")];
    ordered(lg.entries).forEach(function (e) {
      if (e.type === "buy" || e.type === "sell")
        lines.push([e.date, e.type, e.symbol, e.qty, e.price, e.broker, e.commission, e.taxes, e.other, e.note || "", "", e.time || ""].map(csvEsc).join(","));
    });
    return lines.join("\n") + "\n";
  }
  function importCSV(lg, presets, text) {
    var rows = parseCSV(text);
    if (!rows.length) return { added: 0, errors: ["empty file"] };
    var head = rows[0].map(function (h) { return h.trim().toLowerCase(); }), recs = rows.slice(1).map(function (r, i) {
      var o = { _line: i + 2 }; head.forEach(function (h, j) { o[h] = (r[j] || "").trim(); }); return o;
    });
    if (head.indexOf("side") < 0 || head.indexOf("symbol") < 0) return { added: 0, errors: ["needs the columns: " + FIELDS.join(", ")] };
    recs.sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : (a.side === "buy" ? 0 : 1) - (b.side === "buy" ? 0 : 1); });
    var seen = {}, added = 0, skipped = 0, errors = [];
    lg.entries.forEach(function (e) { if (e.type === "buy" || e.type === "sell") seen[[e.date, e.type, e.symbol, e.qty, e.price, e.broker].join("|")] = 1; });
    recs.forEach(function (r) {
      try {
        var k = [r.date, (r.side || "").toLowerCase(), (r.symbol || "").toUpperCase(), parseInt(r.qty, 10), parseFloat(r.price), r.broker || lg.default_broker].join("|");
        if (seen[k]) { skipped++; return; }
        recordTrade(lg, presets, r); seen[k] = 1; added++;
      } catch (e) { errors.push("line " + r._line + ": " + e.message); }
    });
    return { added: added, skipped: skipped, errors: errors };
  }
  /** A ledger.json from portfolio.py (Termux or computer), or this site's own export. */
  function importLedger(text) {
    var o = typeof text === "string" ? JSON.parse(text) : text;
    if (o && o.format === "psx-desk-ledger") o = o.ledger;
    if (!o || !Array.isArray(o.entries) || typeof o.brokers !== "object") throw new Error("not a portfolio ledger (ledger.json)");
    o = normalise(o);
    o.next_id = Math.max(o.next_id || 1, 1 + o.entries.reduce(function (m, e) { return Math.max(m, e.id || 0); }, 0));
    return o;
  }

  var api = { FIELDS: FIELDS, empty: empty, normalise: normalise, presetBroker: presetBroker, estimateCharges: estimateCharges, addBroker: addBroker,
    recordTrade: recordTrade, recordFund: recordFund, recordCash: recordCash, recordDividend: recordDividend, remove: remove, ordered: ordered,
    lots: lots, holdings: holdings, fundHoldings: fundHoldings, cashBalance: cashBalance, summary: summary, statusOf: statusOf,
    volatility: volatility, sma: sma, stopFor: stopFor, priceCalc: priceCalc, review: review, openRisk: openRisk, sizeIdeas: sizeIdeas,
    tickets: tickets, reviewFunds: reviewFunds, exportCSV: exportCSV, importCSV: importCSV, parseCSV: parseCSV, importLedger: importLedger };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Ledger = api;
})(typeof self !== "undefined" ? self : this);
