"""Offline tests: python3 -m unittest discover tests"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, os.path.join(ROOT, "psx-mufap", "scripts"))

import common as C  # noqa: E402
import pkdata  # noqa: E402
import rank  # noqa: E402
import backtest as B  # noqa: E402
import paper  # noqa: E402
import psxinfo as P  # noqa: E402
import propose  # noqa: E402
import dashboard  # noqa: E402
import portfolio as PF  # noqa: E402
import advice as A  # noqa: E402
import funds as FU  # noqa: E402
import daily  # noqa: E402
import pkm  # noqa: E402
import profiles as PRF  # noqa: E402
import risk as RK  # noqa: E402
import sip as SP  # noqa: E402


def run(fn, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn(argv)
    return rc, out.getvalue()


def rows_from(closes, opens=None):
    return [{"date": "2026-01-%02d" % (i + 1) if i < 31 else "2026-02-%02d" % (i - 30),
             "open": (opens or closes)[i], "close": c, "volume": 0} for i, c in enumerate(closes)]


class Home(unittest.TestCase):
    def setUp(self):
        self.h = tempfile.mkdtemp()
        with open(os.path.join(self.h, "config.json"), "w") as f:
            json.dump({"watchlist": ["UPCO", "DOWNCO", "FLATCO", "WILDCO"]}, f)
        for s in ["UPCO", "DOWNCO", "FLATCO", "WILDCO", "KSE100"]:
            run(pkdata.main, ["--home", self.h, "psx", s, "--from-file",
                              os.path.join(FIX, "psx-%s.json" % s)])
        run(pkdata.main, ["--home", self.h, "mufap", "--from-file", os.path.join(FIX, "mufap-2026-10-26.md")])

    def tearDown(self):
        shutil.rmtree(self.h)


class TestPSX(unittest.TestCase):
    def test_json_rows_to_karachi_dates_sorted(self):
        # 2026-10-23 19:30 UTC is 2026-10-24 00:30 in Karachi
        text = json.dumps({"status": 1, "data": [[1792783800, 101.5, 5000, 100.0], [1792697400, 99.0, 10, 98.0]]})
        rows = pkdata.parse_psx(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["close"], 101.5)
        self.assertEqual(rows[0]["open"], 100.0)
        r = C.write_prices(os.path.join(tempfile.mkdtemp(), "x.csv"), rows)
        self.assertLess(r[0]["date"], r[1]["date"])

    def test_csv_fallback(self):
        rows = pkdata.parse_psx("Date,Open,High,Low,Close,Volume\n2026-10-01,10,11,9,10.5,\"1,000\"\n")
        self.assertEqual(rows[0]["close"], 10.5)
        self.assertEqual(rows[0]["date"], "2026-10-01")

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            pkdata.parse_psx("<html>blocked</html>")


class TestMUFAP(unittest.TestCase):
    def test_markdown(self):
        with open(os.path.join(FIX, "mufap-2026-10-26.md")) as f:
            date, funds = pkdata.parse_mufap(f.read())
        self.assertEqual(date, "2026-10-26")
        self.assertEqual(len(funds), 10)
        cats = {f["category"] for f in funds}
        self.assertEqual(cats, {"Money Market", "Equity"})
        mm = [f for f in funds if f["category"] == "Money Market"][0]
        self.assertEqual(mm["return_type"], "annualized")
        self.assertEqual(mm["fund"], "ABL Cash Fund")  # markdown link stripped
        eq = [f for f in funds if f["category"] == "Equity"]
        self.assertTrue(any(f["d30"] is not None and f["d30"] < 0 for f in eq), "(x.xx) must parse as negative")

    def test_html(self):
        html = """<p>Report Date: Oct 26, 2026</p><table>
        <tr><td colspan=17>Equity (Absolute Return )</td></tr>
        <tr><th>Sector</th><th>Fund Name</th></tr>
        <tr><td>Open-End Funds</td><td><a href='#'>Test Stock Fund</a></td><td></td><td>N/A</td>
        <td>Oct 24, 2026</td><td>1,234.5</td><td>(1.5)</td><td>2</td><td>3</td><td>4</td><td>(5.25)</td>
        <td>6</td><td>7</td><td>8</td><td>9</td><td>N/A</td><td>N/A</td></tr></table>"""
        date, funds = pkdata.parse_mufap(html)
        self.assertEqual(len(funds), 1)
        f = funds[0]
        self.assertEqual((f["fund"], f["nav"], f["ytd"], f["d30"], f["y2"]), ("Test Stock Fund", 1234.5, -1.5, -5.25, None))
        self.assertEqual(f["validity_date"], "2026-10-24")

    def test_nav_history_dedupes(self):
        h = tempfile.mkdtemp()
        for _ in range(2):
            run(pkdata.main, ["--home", h, "mufap", "--from-file", os.path.join(FIX, "mufap-2026-10-26.md")])
        with open(os.path.join(h, "mufap", "nav_history.csv")) as f:
            self.assertEqual(len(f.read().strip().splitlines()), 11)
        shutil.rmtree(h)


class TestRank(Home):
    def test_percentiles(self):
        self.assertEqual(rank.percentiles([1, 2, 3, None]), [0.0, 50.0, 100.0, None])
        self.assertEqual(rank.percentiles([5]), [50.0])

    def test_stocks(self):
        res, bm, notes = rank.rank_stocks(self.h, C.load_config(self.h))
        self.assertEqual(len(res), 4)
        self.assertEqual(notes["missing"], [])
        self.assertIsNotNone(bm)
        scores = [m["score"] for m in res]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_funds_within_category(self):
        _, funds = rank.fund_rows(self.h)
        by = rank.rank_funds(funds)
        self.assertEqual(set(by), {"Money Market", "Equity"})
        for fs in by.values():
            self.assertEqual(len({f["category"] for f in fs}), 1)


class TestBacktest(unittest.TestCase):
    def test_fills_next_open_not_same_bar(self):
        closes = [10] * 5 + [20] * 5
        opens = [10] * 5 + [15] + [20] * 4
        rows = rows_from(closes, opens)
        # go long the moment price jumps (day index 5); the fill must be day 6's open
        s = B.simulate(rows, lambda i: 1 if closes[i] > 10 else 0, cost_bps=0)
        buy = s["trade_log"][0]
        self.assertEqual(buy["date"], rows[6]["date"])
        self.assertEqual(buy["price"], 20)
        self.assertAlmostEqual(s["total"], 0.0)  # bought after the jump: no free profit

    def test_costs_and_cash_yield(self):
        rows = rows_from([10.0] * 10)
        s = B.simulate(rows, lambda i: 1, cost_bps=100)
        self.assertAlmostEqual(s["total"], -0.01, places=6)
        s = B.simulate(rows, lambda i: 0, cost_bps=0, rf_annual=0.10)
        self.assertGreater(s["total"], 0)

    def test_optimize_reports_out_of_sample_tail(self):
        h = tempfile.mkdtemp()
        run(pkdata.main, ["--home", h, "psx", "WILDCO", "--from-file", os.path.join(FIX, "psx-WILDCO.json")])
        rows = C.read_prices(C.price_path(h, "WILDCO"))
        p, s_in, s_out = B.optimize(rows, "sma", 20, 0.0)
        self.assertLess(p["fast"], p["slow"])
        self.assertEqual(s_out["start"], rows[int(len(rows) * 0.7)]["date"])
        self.assertLess(s_in["end"], s_out["start"])
        shutil.rmtree(h)


class TestMomentum(Home):
    def test_runs_and_beats_nothing_magic(self):
        r = B.momentum(self.h, C.load_config(self.h), ["UPCO", "DOWNCO", "FLATCO", "WILDCO"], hold=2)
        self.assertGreater(r["days"], 500)
        self.assertGreaterEqual(min(e["equity"] for e in r["equity"]), 0)


class TestPaper(Home):
    def test_buy_sell_accounting(self):
        run(paper.main, ["--home", self.h, "init", "--cash", "100000"])
        run(paper.main, ["--home", self.h, "buy", "FLATCO", "100", "--price", "50"])
        pf = paper.load(self.h)
        self.assertAlmostEqual(pf["cash"], 100000 - 5000 - 10)  # 20 bps fee
        run(paper.main, ["--home", self.h, "sell", "FLATCO", "all", "--price", "60"])
        pf = paper.load(self.h)
        self.assertNotIn("FLATCO", pf["positions"])
        self.assertAlmostEqual(pf["cash"], 100000 - 5010 + 6000 - 12)
        self.assertAlmostEqual(pf["trades"][-1]["realized"], 6000 - 12 - 5010)

    def test_refuses_overspend_and_shorts(self):
        run(paper.main, ["--home", self.h, "init", "--cash", "1000"])
        with self.assertRaises(SystemExit):
            run(paper.main, ["--home", self.h, "buy", "UPCO", "1000"])
        with self.assertRaises(SystemExit):
            run(paper.main, ["--home", self.h, "sell", "UPCO", "1"])

    def test_funds(self):
        run(paper.main, ["--home", self.h, "init", "--cash", "100000"])
        run(paper.main, ["--home", self.h, "invest", "ABL Cash", "50000"])
        pf = paper.load(self.h)
        self.assertAlmostEqual(pf["cash"], 50000)
        with self.assertRaises(SystemExit):  # ambiguous: two ABL funds in the fixture
            run(paper.main, ["--home", self.h, "invest", "ABL", "10"])
        run(paper.main, ["--home", self.h, "redeem", "ABL Cash", "all"])
        self.assertAlmostEqual(paper.load(self.h)["cash"], 100000)

    def test_signals_dry_run_books_nothing(self):
        run(paper.main, ["--home", self.h, "init"])
        rc, out = run(paper.main, ["--home", self.h, "signals", "--strategy", "momentum"])
        self.assertIn("Nothing booked", out)
        self.assertEqual(paper.load(self.h)["trades"], [])
        run(paper.main, ["--home", self.h, "signals", "--strategy", "momentum", "--apply"])
        pf = paper.load(self.h)
        self.assertTrue(pf["trades"])
        self.assertGreaterEqual(pf["cash"], 0)


class Market(unittest.TestCase):
    """A synthetic 12-share market with sectors, Shariah flags and dividends."""

    def setUp(self):
        self.h = tempfile.mkdtemp()
        with open(os.path.join(FIX, "synthetic-universe.json")) as f:
            d = json.load(f)
        with open(os.path.join(self.h, "universe.json"), "w") as f:
            json.dump(d["universe"], f)
        for c in d["companies"].values():
            P.save_company(self.h, c)
        with open(os.path.join(self.h, "config.json"), "w") as f:
            json.dump({"watchlist": ["SYN01", "SYN05"], "min_avg_volume": 1000}, f)
        for s in list(d["universe"]) + ["KSE100"]:
            run(pkdata.main, ["--home", self.h, "psx", s, "--from-file", os.path.join(FIX, "psx-%s.json" % s)])
        self.cfg = C.load_config(self.h)

    def tearDown(self):
        shutil.rmtree(self.h)


class TestPSXInfo(unittest.TestCase):
    def test_company_page(self):
        with open(os.path.join(FIX, "psx-company-OGDC.html")) as f:
            c = P.parse_company(f.read(), "OGDC")
        self.assertEqual(c["sector"], "OIL & GAS EXPLORATION COMPANIES")
        self.assertEqual(c["name"], "Oil & Gas Development Company Limited")
        self.assertEqual((c["pe"], c["low_52w"], c["high_52w"]), (5.29, 238.2, 352.0))
        self.assertEqual(c["tags"], ["XD"])
        self.assertEqual(len(c["payouts"]), 5)  # the header row is not a payout
        p = c["payouts"][0]
        self.assertEqual((p["announced"], p["cash_pct"], p["kind"], p["bc_from"]), ("2026-09-08", 60.0, "final", "2026-10-09"))

    def test_payout_notation(self):
        self.assertEqual(P.parse_payout_details("32.50%(iii) (D)")["cash_pct"], 32.5)
        d = P.parse_payout_details("25% (D) 10% (B)")
        self.assertEqual((d["cash_pct"], d["bonus_pct"]), (25.0, 10.0))
        self.assertEqual(P.parse_payout_details("15% (R)")["right_pct"], 15.0)

    def test_index_and_universe(self):
        with open(os.path.join(FIX, "psx-index-KMIALLSHR.html")) as f:
            kmi = f.read()
        idx = P.parse_index(kmi)
        self.assertEqual(sorted(idx), ["AASM", "ABOT", "LUCK"])
        self.assertEqual(idx["AASM"]["tags"], ["NC"])
        allshr = kmi.replace("ABOT", "ZZZZ")  # pretend ZZZZ is listed but not in KMI
        uni = P.build_universe(allshr, kmi)
        self.assertFalse(uni["ZZZZ"]["shariah"])
        self.assertTrue(uni["LUCK"]["shariah"])

    def test_dividend_summary(self):
        import datetime as dt
        with open(os.path.join(FIX, "psx-company-OGDC.html")) as f:
            c = P.parse_company(f.read(), "OGDC")
        d = P.dividend_summary({}, "OGDC", c, [], price=298.12, today=dt.date(2026, 10, 26))
        self.assertAlmostEqual(d["dps_ttm"], 17.0)  # 6 + 3.25 + 4.25 + 3.5, Rs 10 face value
        self.assertAlmostEqual(d["yield_ttm"], 17.0 / 298.12)
        self.assertEqual(d["expected_next"]["around"], "2026-10-29")  # last year's IQ, one year on
        d5 = P.dividend_summary({"face_values": {"OGDC": 5}}, "OGDC", c, [], price=298.12, today=dt.date(2026, 10, 26))
        self.assertAlmostEqual(d5["dps_ttm"], 8.5)

    def test_payouts_page(self):
        with open(os.path.join(FIX, "psx-payouts.html")) as f:
            rows = P.parse_payouts_page(f.read())
        self.assertEqual([r["symbol"] for r in rows], ["BAHL", "MCB", "UPCO"])
        self.assertEqual(rows[2]["bonus_pct"], 10.0)


class TestAllMarket(Market):
    def test_all_sector_shariah(self):
        res, _, notes = rank.rank_stocks(self.h, self.cfg, all_=True)
        self.assertEqual(len(res), 12)
        res, _, _ = rank.rank_stocks(self.h, self.cfg, all_=True, sector="bank", shariah=True)
        self.assertTrue(res and all(m["shariah"] and "BANK" in m["sector"] for m in res))
        self.assertTrue(all(m["div_yield"] is not None for m in res))
        res, _, notes = rank.rank_stocks(self.h, self.cfg, all_=True, min_volume=10 ** 9)
        self.assertEqual((len(res), notes["illiquid"]), (0, 12))

    def test_sectors(self):
        res, _, _ = rank.rank_stocks(self.h, self.cfg, all_=True)
        secs = rank.sector_summary(res)
        self.assertEqual(len(secs), 4)
        self.assertEqual(sum(s["count"] for s in secs), 12)

    def test_propose_apply_and_review(self):
        run(paper.main, ["--home", self.h, "init"])
        rc, out = run(propose.main, ["--home", self.h, "run", "--all", "--candidates", "8", "--pick", "3"])
        self.assertIn("Nothing booked", out)
        self.assertEqual(paper.load(self.h)["trades"], [])
        with open(os.path.join(self.h, "proposals", os.listdir(os.path.join(self.h, "proposals"))[0])) as f:
            prop = json.load(f)
        self.assertLessEqual(len(prop["picks"]), 3)
        for e in prop["candidates"]:  # picks passed every out-of-sample gate and are long today
            if e["symbol"] in prop["picks"]:
                self.assertTrue(e["pass"])
                self.assertEqual(e["signal"], 1)
        sectors = [e["sector"] for e in prop["candidates"] if e["symbol"] in prop["picks"]]
        self.assertTrue(all(sectors.count(s) <= 2 for s in sectors))
        run(propose.main, ["--home", self.h, "run", "--all", "--candidates", "8", "--pick", "3", "--apply"])
        pf = paper.load(self.h)
        bought = [k for k, v in pf["positions"].items() if v.get("meta")]
        self.assertEqual(sorted(bought), sorted(prop["picks"]))
        self.assertGreaterEqual(pf["cash"], 0)
        rc, out = run(propose.main, ["--home", self.h, "review"])
        self.assertIn("HOLD", out)
        # A crash in price makes the stop-loss fire
        sym = bought[0]
        pf["positions"][sym]["cost"] *= 2
        paper.save(self.h, pf)
        _, rv = propose.review(self.h, self.cfg, 0.15)
        self.assertEqual([r["action"] for r in rv if r["symbol"] == sym], ["SELL"])

    def test_paper_dividends(self):
        run(paper.main, ["--home", self.h, "init", "--cash", "1000000"])
        run(paper.main, ["--home", self.h, "buy", "SYN03", "1000", "--price", "50"])
        pf = paper.load(self.h)
        pf["positions"]["SYN03"]["opened"] = "2026-01-01"  # held before the synthetic book closure
        paper.save(self.h, pf)
        due = paper.due_dividends(self.h, self.cfg, pf)
        self.assertEqual(len(due), 1)
        d = due[0]  # SYN03: 25% of Rs 10 on 1000 shares = 2500, less 15% tax
        self.assertAlmostEqual(d["gross"], 2500.0)
        self.assertAlmostEqual(d["net"], 2125.0)
        cash = pf["cash"]
        run(paper.main, ["--home", self.h, "dividends", "--apply"])
        pf = paper.load(self.h)
        self.assertAlmostEqual(pf["cash"], cash + 2125.0)
        self.assertEqual(paper.due_dividends(self.h, self.cfg, pf), [])  # credited once only


class TestDashboard(Market):
    def test_build_and_standalone(self):
        run(paper.main, ["--home", self.h, "init"])
        run(paper.main, ["--home", self.h, "mark"])
        data = dashboard.build_data(self.h, self.cfg)
        self.assertEqual(data["scope"], "all")
        self.assertEqual(len(data["stocks"]), 12)
        n = len(data["calendar"])
        self.assertTrue(all(len(v) == n for v in data["series"].values()))
        self.assertIn("KSE100", data["series"])
        s = data["stocks"][0]
        for k in ("sector", "shariah", "div", "payouts", "r1m", "score"):
            self.assertIn(k, s)
        out = os.path.join(self.h, "standalone.html")
        run(dashboard.main, ["--home", self.h, "build", "--standalone", out])
        with open(out) as f:
            page = f.read()
        self.assertIn("window.PKM_DATA=", page)
        self.assertNotIn('<script src="app.js">', page)
        self.assertNotIn("</script><script>alert", page)

    def test_server_is_read_only_and_needs_password_off_loopback(self):
        import threading
        import urllib.error
        import urllib.request
        run(dashboard.main, ["--home", self.h, "build"])
        dashboard.Handler.root, dashboard.Handler.password = os.path.join(self.h, "dashboard"), None
        srv = dashboard.http.server.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            r = opener.open(base + "/data.json")
            self.assertEqual(r.status, 200)
            self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
            for path in ("/config.json", "/../config.json", "/paper/portfolio.json", "/dashboard/"):
                with self.assertRaises(urllib.error.HTTPError) as e:
                    opener.open(base + path)
                self.assertEqual(e.exception.code, 404)
            with self.assertRaises(urllib.error.HTTPError) as e:
                opener.open(urllib.request.Request(base + "/data.json", data=b"x", method="POST"))
            self.assertEqual(e.exception.code, 405)
            dashboard.Handler.password = "s3cret"
            with self.assertRaises(urllib.error.HTTPError) as e:
                opener.open(base + "/data.json")
            self.assertEqual(e.exception.code, 401)
            import base64
            req = urllib.request.Request(base + "/data.json", headers={
                "Authorization": "Basic " + base64.b64encode(b"pkm:s3cret").decode()})
            self.assertEqual(opener.open(req).status, 200)
        finally:
            dashboard.Handler.password = None
            srv.shutdown()
            srv.server_close()
        with self.assertRaises(SystemExit):  # refuses a LAN address without a password
            os.environ.pop("PKM_DASHBOARD_PASSWORD", None)
            dashboard.cmd_serve(argparse_ns(host="0.0.0.0", port=0), self.h, self.cfg)


class TestLedger(Market):
    def pf(self, *args):
        return run(PF.main, ["--home", self.h] + list(args))

    def test_fees_fifo_per_broker_and_pnl(self):
        self.pf("broker", "add", "AKD", "--commission-pct", "0.15", "--min-commission", "50", "--default")
        self.pf("broker", "add", "JSG", "--commission-pct", "0.10")
        # actual contract-note charges on the first buy; estimated on the second
        self.pf("buy", "SYN05", "1000", "50", "--broker", "AKD", "--date", "2026-01-05",
                "--commission", "75", "--taxes", "12", "--other", "8")
        self.pf("buy", "SYN05", "1000", "60", "--broker", "JSG", "--date", "2026-02-05")
        lg = PF.load(self.h)
        self.assertTrue(lg["entries"][1]["commission_estimated"])
        self.assertAlmostEqual(lg["entries"][1]["commission"], 60.0)  # 0.10% of 60,000
        # selling at AKD consumes AKD's lot, not the cheaper-or-older one elsewhere
        self.pf("sell", "SYN05", "400", "70", "--broker", "AKD", "--date", "2026-03-05", "--commission", "50",
                "--taxes", "0", "--other", "0")
        _, sales = PF.lots(PF.load(self.h))
        s = sales[0]
        unit = (50000 + 75 + 12 + 8) / 1000.0
        self.assertAlmostEqual(s["cost"], round(400 * unit, 2))
        self.assertAlmostEqual(s["proceeds"], 400 * 70 - 50)
        self.assertAlmostEqual(s["pnl"], round(28000 - 50 - 400 * unit, 2))
        self.assertEqual(s["avg_days_held"], 59)
        hs = PF.holdings(self.h, PF.load(self.h))
        self.assertEqual(hs[0]["qty"], 1600)
        self.assertEqual(hs[0]["brokers"], {"AKD": 600, "JSG": 1000})
        fees = PF.fee_table(PF.load(self.h))
        self.assertAlmostEqual(fees["AKD"]["commission"] + fees["AKD"]["taxes"] + fees["AKD"]["other"], 75 + 12 + 8 + 50)

    def test_no_short_selling_even_backdated(self):
        self.pf("buy", "SYN05", "100", "50", "--broker", "AKD", "--date", "2026-03-01")
        with self.assertRaises(SystemExit):
            self.pf("sell", "SYN05", "200", "55", "--broker", "AKD", "--date", "2026-03-02")
        with self.assertRaises(SystemExit):  # shares bought on 1 March can't be sold on 1 February
            self.pf("sell", "SYN05", "50", "55", "--broker", "AKD", "--date", "2026-02-01")
        with self.assertRaises(SystemExit):  # held at AKD, not at another broker
            self.pf("sell", "SYN05", "50", "55", "--broker", "JSG", "--date", "2026-03-02")
        self.pf("sell", "SYN05", "all", "55", "--broker", "AKD", "--date", "2026-03-02")
        self.assertEqual(PF.holdings(self.h, PF.load(self.h)), [])
        # deleting the buy would orphan the sale: refused
        with self.assertRaises(SystemExit):
            self.pf("delete", "1")

    def test_cash_and_import(self):
        self.pf("cash", "deposit", "100000", "--broker", "AKD", "--date", "2026-01-01")
        csvp = os.path.join(self.h, "t.csv")
        with open(csvp, "w") as f:
            f.write("date,side,symbol,qty,price,broker,commission,taxes,other,note\n"
                    "2026-01-10,buy,SYN05,500,40,AKD,30,0,5,first\n"
                    "2026-01-20,sell,SYN05,200,45,AKD,15,0,2,\n")
        self.pf("import", csvp)
        lg = PF.load(self.h)
        self.assertAlmostEqual(PF.cash_balance(lg), 100000 - 20035 + 9000 - 17)
        bad = os.path.join(self.h, "bad.csv")
        with open(bad, "w") as f:
            f.write("date,side,symbol,qty,price,broker\n2026-01-30,sell,SYN05,9999,45,AKD\n")
        with self.assertRaises(SystemExit):
            self.pf("import", bad)
        self.assertEqual(len(PF.load(self.h)["entries"]), len(lg["entries"]))  # all-or-nothing

    def test_dividends_due_need_shares_before_book_closure(self):
        # SYN03 payout in the synthetic market: book closure 2026-04-20, 25% of Rs 10
        self.pf("buy", "SYN03", "1000", "30", "--broker", "AKD", "--date", "2026-03-01")
        self.pf("buy", "SYN04", "1000", "30", "--broker", "AKD", "--date", "2026-12-01")  # bought after its closure
        due = PF.due_dividends(self.h, self.cfg, PF.load(self.h))
        self.assertEqual([d["symbol"] for d in due], ["SYN03"])
        self.assertAlmostEqual(due[0]["net"], 2125.0)
        self.pf("dividends", "--apply")
        self.assertEqual(PF.due_dividends(self.h, self.cfg, PF.load(self.h)), [])


class TestAdvice(Market):
    def test_stop_rules(self):
        rows = [{"date": "2026-01-%02d" % (i + 1), "open": 100, "close": 100 + (i % 2), "volume": 1} for i in range(20)]
        st = A.stop_for(rows, 100.0, "2026-01-01", self.cfg)
        self.assertLessEqual(st["initial"], 95.0)    # at least 5% below entry even when calm
        self.assertGreaterEqual(st["initial"], 85.0)  # never more than 15% below
        wild = [{"date": "2026-01-%02d" % (i + 1), "open": 100, "close": 100 + (20 if i % 2 else 0), "volume": 1} for i in range(20)]
        self.assertAlmostEqual(A.stop_for(wild, 100.0, "2026-01-01", self.cfg)["initial"], 85.0)
        up = [{"date": "2026-01-%02d" % (i + 1), "open": 100, "close": 100.0 + 2 * i, "volume": 1} for i in range(20)]
        st = A.stop_for(up, 100.0, "2026-01-01", self.cfg)
        self.assertGreater(st["stop"], st["initial"])  # trailed up behind the rally
        self.assertAlmostEqual(st["target"], 100 + 2 * (100 - st["initial"]), places=1)

    def test_actions_and_buy_sizing(self):
        run(PF.main, ["--home", self.h, "broker", "add", "AKD", "--default"])
        run(PF.main, ["--home", self.h, "cash", "deposit", "1000000", "--date", "2025-01-01"])
        rows = C.read_prices(C.price_path(self.h, "SYN01"))  # a falling share
        run(PF.main, ["--home", self.h, "buy", "SYN01", "1000", str(rows[-200]["close"]), "--broker", "AKD",
                      "--date", rows[-200]["date"]])
        lg = PF.load(self.h)
        s = PF.summary(self.h, lg)
        rv = A.review_holdings(self.h, self.cfg, lg, s)
        self.assertEqual(rv[0]["action"], "SELL")
        lg["stops"]["SYN01"] = 0.01  # your own stop wins over the computed one
        rv = A.review_holdings(self.h, self.cfg, lg, s)
        self.assertNotEqual(rv[0]["action"], "SELL")
        self.assertEqual(rv[0]["stop_source"], "yours")
        ideas, info = A.buy_ideas(self.h, self.cfg, lg, s, n=3, all_=True)
        self.assertTrue(ideas)
        capital = s["value"] + s["cash"]
        spent = 0
        for i in ideas:
            self.assertNotEqual(i["symbol"], "SYN01")
            self.assertLess(i["stop"], i["entry"])
            self.assertGreater(i["target"], i["entry"])
            self.assertLessEqual(i["risk_pkr"], capital * 0.01 + i["risk_per_share"])
            self.assertLessEqual(i["qty"] * i["entry"], capital * 0.25 + i["entry"])
            spent += i["cost"]
        self.assertLessEqual(spent, s["cash"])  # never more than the cash you recorded

    def test_trim_when_too_concentrated(self):
        run(PF.main, ["--home", self.h, "broker", "add", "AKD", "--default"])
        rows = C.read_prices(C.price_path(self.h, "SYN11"))
        run(PF.main, ["--home", self.h, "buy", "SYN11", "100", str(rows[-30]["close"]), "--date", rows[-30]["date"]])
        run(PF.main, ["--home", self.h, "buy", "SYN08", "10", "100", "--date", rows[-30]["date"]])
        lg = PF.load(self.h)
        rv = {r["symbol"]: r for r in A.review_holdings(self.h, self.cfg, lg, PF.summary(self.h, lg))}
        self.assertEqual(rv["SYN11"]["action"], "TRIM")
        self.assertGreater(rv["SYN11"]["trim_qty"], 0)

    def test_dashboard_has_my_portfolio(self):
        run(PF.main, ["--home", self.h, "buy", "SYN05", "100", "50", "--broker", "AKD", "--date", "2026-03-01"])
        data = dashboard.build_data(self.h, self.cfg)
        self.assertEqual([x["symbol"] for x in data["mine"]["holdings"]], ["SYN05"])
        self.assertTrue(next(s for s in data["stocks"] if s["symbol"] == "SYN05")["owned"])
        self.assertIn("AKD", [f["broker"] for f in data["mine"]["fees"]])


class TestBrokersAndFunds(Market):
    def setUp(self):
        super().setUp()
        run(pkdata.main, ["--home", self.h, "mufap", "--from-file", os.path.join(FIX, "mufap-2026-10-26.md")])

    def pf(self, *args):
        return run(PF.main, ["--home", self.h] + list(args))

    def test_every_preset_is_usable(self):
        data = PF.load_presets()
        self.assertIn("psx-minimum", data["brokers"])
        for key in data["brokers"]:
            b = PF.preset_broker(key)
            self.assertTrue(b["source"].startswith("https://"), key)
            c, t, o = PF.estimate_charges(b, 1000, 100.0, "buy")
            self.assertGreaterEqual(c, 150.0 - 1e-9, key)  # never below the PSX minimum (0.15%)
            self.assertAlmostEqual(t, round(c * 0.13, 2), places=2)

    def test_price_tiers(self):
        scs, akd, kh = PF.preset_broker("scs"), PF.preset_broker("akd"), PF.preset_broker("khanani")
        self.assertEqual(PF.estimate_charges(scs, 1000, 3.5)[0], 30.0)       # Rs 0.03/share below Rs 10
        self.assertEqual(PF.estimate_charges(scs, 1000, 20.0)[0], 50.0)      # Rs 0.05/share beats 0.15% of Rs 20,000
        self.assertEqual(PF.estimate_charges(scs, 1000, 100.0)[0], 150.0)    # 0.15% beats Rs 0.05/share
        self.assertEqual(PF.estimate_charges(akd, 1000, 4.0)[0], 30.0)
        self.assertEqual(PF.estimate_charges(kh, 1000, 300.0)[0], 450.0)
        self.assertEqual(PF.estimate_charges(akd, 1000, 100.0, "sell")[1], PF.estimate_charges(akd, 1000, 100.0, "buy")[1])

    def test_broker_commands_and_stop_on_buy(self):
        self.pf("broker", "import", "akd,scs")
        self.pf("broker", "add", "Mine", "--commission-pct", "0.1", "--per-share", "0.02", "--sales-tax-pct", "16", "--default")
        lg = PF.load(self.h)
        self.assertEqual(sorted(lg["brokers"]), ["Mine", "akd", "scs"])
        self.assertEqual(lg["default_broker"], "Mine")
        self.pf("buy", "SYN05", "100", "50", "--date", "2026-03-01", "--stop", "45")
        lg = PF.load(self.h)
        self.assertEqual(lg["stops"]["SYN05"], 45.0)
        e = lg["entries"][-1]
        self.assertEqual(e["broker"], "Mine")
        self.assertAlmostEqual(e["commission"], 5.0)               # 0.1% of 5,000 beats Rs 0.02 x 100
        self.assertAlmostEqual(e["taxes"], 0.8)                    # 16% of the commission
        with self.assertRaises(SystemExit):
            self.pf("buy", "SYN05", "100", "50", "--stop", "55")    # a stop must be below the price
        self.pf("buy", "SYN05", "100", "50", "--date", "2026-03-02", "--commission", "10")
        e = PF.load(self.h)["entries"][-1]
        self.assertEqual((e["commission"], e["taxes"], e["estimated"]), (10.0, 1.6, ["taxes", "other"]))

    def test_funds_ledger(self):
        self.pf("cash", "deposit", "500000", "--date", "2026-01-01")
        self.pf("fund-buy", "ABL Cash", "100000", "--nav", "10", "--load-pct", "1", "--date", "2026-02-01")
        lg = PF.load(self.h)
        e = lg["entries"][-1]
        self.assertEqual(e["fund"], "ABL Cash Fund")
        self.assertAlmostEqual(e["units"], 9900.0)
        self.pf("fund-sell", "ABL Cash Fund", "all", "--nav", "11", "--date", "2026-06-01")
        s = PF.summary(self.h, PF.load(self.h))
        self.assertEqual(s["funds"], [])
        self.assertAlmostEqual(s["fund_sales"][0]["pnl"], 9900 * 11 - 100000)
        self.assertAlmostEqual(s["cash"], 500000 - 100000 + 108900)
        with self.assertRaises(SystemExit):
            self.pf("fund-buy", "ABL", "1000")                      # ambiguous name

    def test_fund_advice_and_review(self):
        date, cats = FU.advise(self.h, "low")
        self.assertEqual([c["category"] for c in cats], ["Money Market"])
        top = cats[0]["funds"]
        self.assertTrue(all(top[i]["score"] >= top[i + 1]["score"] for i in range(len(top) - 1)))
        _, cats = FU.advise(self.h, "high")
        self.assertEqual([c["category"] for c in cats], ["Equity"])
        ranked = [f for f in cats[0]["funds"]]
        # hold the weakest money market fund: review says REVIEW and names leaders
        by = FU.ranked_by_category(self.h)[1]["Money Market"]
        worst = [f for f in by if f.get("score") is not None][-1]["fund"]
        self.pf("fund-buy", worst, "10000", "--date", "2026-02-01")
        _, rv = FU.review(self.h)
        self.assertEqual(rv[0]["action"], "REVIEW")
        self.assertIn("leaders", rv[0]["why"])


class TestPortable(Market):
    def test_android_uses_shared_storage(self):
        shared = tempfile.mkdtemp()
        old, env = C.ANDROID_SHARED, dict(os.environ)
        try:
            C.ANDROID_SHARED = shared
            os.environ.pop("PKM_HOME", None)
            os.environ["ANDROID_ROOT"] = "/system"
            self.assertEqual(C.default_home(), os.path.join(shared, "pkmarket"))
            os.environ.pop("ANDROID_ROOT")
            os.environ.pop("ANDROID_DATA", None)
            self.assertEqual(C.default_home(), os.path.join("~", "pkmarket"))
        finally:
            C.ANDROID_SHARED = old
            os.environ.clear()
            os.environ.update(env)
            shutil.rmtree(shared)

    def test_daily_pipeline_without_downloads(self):
        run(paper.main, ["--home", self.h, "init"])
        run(PF.main, ["--home", self.h, "buy", "SYN05", "100", "50", "--broker", "AKD", "--date", "2026-03-01"])
        rc, out = run(daily.main, ["--home", self.h, "--no-download"])
        self.assertEqual(rc, 0)
        for stepname in ("paper: value", "my portfolio: advice", "dashboard (one file)"):
            self.assertIn("-- " + stepname, out)
        self.assertTrue(os.path.exists(os.path.join(self.h, "dashboard.html")))
        self.assertTrue(os.listdir(os.path.join(self.h, "advice")))

    def test_launcher_passes_through(self):
        rc, out = run(pkm.main, ["rank", "--home", self.h, "stocks", "--top", "2"])
        self.assertIn("PSX ranking", out)
        rc, out = run(pkm.main, ["--help"])
        self.assertIn("numbered menu", out)


class TestProfiles(Market):
    def test_every_profile_sets_every_variable(self):
        for name, vals in PRF.PROFILES.items():
            missing = [k for k in PRF.VARIABLES if k not in vals and k != "expected_returns"]
            self.assertEqual(missing, [], name)

    def test_layering_profile_then_yours(self):
        cfg, src = C.load_config(self.h, with_sources=True)
        self.assertEqual((cfg["risk_profile"], cfg["risk_per_trade"], src["risk_per_trade"]), ("moderate", 0.01, "profile"))
        self.assertEqual(src["min_avg_volume"], "yours")            # the test config sets it
        C.write_user_config(self.h, {"risk_profile": "aggressive", "max_holdings": 3})
        cfg, src = C.load_config(self.h, with_sources=True)
        self.assertEqual(cfg["risk_per_trade"], 0.02)
        self.assertEqual((cfg["max_holdings"], src["max_holdings"]), (3, "yours"))
        C.write_user_config(self.h, {"risk_profile": "reckless"})
        with self.assertRaises(SystemExit):
            C.load_config(self.h)

    def test_score_weights_drive_the_ranking(self):
        C.write_user_config(self.h, {"score_weights": {"1m": 1}})
        res, _, _ = rank.rank_stocks(self.h, C.load_config(self.h), all_=True)
        one_m = [m["1m"] for m in res]
        self.assertEqual(one_m, sorted(one_m, reverse=True))

    def test_conservative_gates_are_stricter(self):
        picks = {}
        for name in ("conservative", "very_aggressive"):
            C.write_user_config(self.h, {"risk_profile": name})
            cfg = C.load_config(self.h)
            ev = [propose.evaluate(self.h, cfg, s, cfg["strategies"]) for s in ("SYN05", "SYN07", "SYN08", "SYN10", "SYN11")]
            picks[name] = sum(1 for e in ev if e["pass"])
        self.assertLessEqual(picks["conservative"], picks["very_aggressive"])


class TestRiskCalculator(Market):
    def test_quiz_takes_the_lower_of_capacity_and_willingness(self):
        r = RK.score_quiz([4, 4, 4, 4, 1, 1, 1, 1])
        self.assertEqual((r["capacity"], r["willingness"], r["profile"]), (4, 1, "conservative"))
        r = RK.score_quiz([1, 4, 4, 4, 4, 4, 4, 4])                 # money needed within 2 years
        self.assertEqual(r["profile"], "conservative")
        r = RK.score_quiz([4, 4, 4, 4, 4, 4, 4, 4])
        self.assertEqual((r["profile"], r["max_annual_loss_pct"]), ("very_aggressive", 0.35))
        self.assertEqual(RK.score_quiz([3, 3, 3, 3, 2, 2, 2, 2])["profile"], "moderate")
        with self.assertRaises(ValueError):
            RK.score_quiz([5, 1, 1])

    def test_quiz_save_profile_set_unset(self):
        run(RK.main, ["--home", self.h, "quiz", "--answers", "4,4,4,4,3,3,3,3", "--save"])
        self.assertEqual(C.load_config(self.h)["risk_profile"], "aggressive")
        run(RK.main, ["--home", self.h, "profile", "conservative"])
        run(RK.main, ["--home", self.h, "set", "max_holdings", "4"])
        self.assertEqual(C.load_config(self.h)["max_holdings"], 4)
        run(RK.main, ["--home", self.h, "unset", "max_holdings"])
        self.assertEqual(C.load_config(self.h)["max_holdings"], 12)
        with self.assertRaises(SystemExit):
            run(RK.main, ["--home", self.h, "set", "no_such_thing", "1"])

    def test_position_size(self):
        r = RK.position_size(1000000, 300, 280, 0.01)
        self.assertEqual((r["qty"], r["risk_pkr"]), (500, 10000.0))
        r = RK.position_size(1000000, 300, 299, 0.01, max_position_pct=0.25)
        self.assertEqual((r["qty"], r["limited_by"]), (833, "max position"))
        with self.assertRaises(ValueError):
            RK.position_size(1000, 300, 310, 0.01)

    def test_portfolio_risk_and_budget_flag(self):
        run(PF.main, ["--home", self.h, "cash", "deposit", "1000000", "--date", "2025-01-01"])
        rows = C.read_prices(C.price_path(self.h, "SYN11"))
        run(PF.main, ["--home", self.h, "buy", "SYN11", "200", str(rows[-60]["close"]), "--broker", "AKD",
                      "--date", rows[-60]["date"]])
        r = RK.portfolio_risk(self.h, C.load_config(self.h))
        h0 = r["holdings"][0]
        px = rows[-1]["close"]
        self.assertAlmostEqual(r["open_risk"], round(200 * (px - h0["stop"]), 2), places=1)
        self.assertAlmostEqual(sum(r["allocation_pct"].values()), 1.0, places=6)
        self.assertIsNotNone(r["var_1m_95"])
        C.write_user_config(self.h, {"max_open_risk_pct": 0.0001})
        r = RK.portfolio_risk(self.h, C.load_config(self.h))
        self.assertTrue(any("over your budget" in f for f in r["flags"]))

    def test_advice_respects_holdings_cap_and_reserve(self):
        run(PF.main, ["--home", self.h, "broker", "add", "AKD", "--default"])
        run(PF.main, ["--home", self.h, "cash", "deposit", "300000", "--date", "2025-01-01"])
        run(PF.main, ["--home", self.h, "buy", "SYN05", "100", "50", "--date", "2026-03-01"])
        C.write_user_config(self.h, {"max_holdings": 1})
        lg = PF.load(self.h)
        s = PF.summary(self.h, lg)
        ideas, info = A.buy_ideas(self.h, C.load_config(self.h), lg, s, n=3, all_=True)
        self.assertEqual(ideas, [])
        self.assertIn("max_holdings", info["note"])
        C.write_user_config(self.h, {"max_holdings": 10, "cash_reserve_pct": 0.5, "risk_per_trade": 0.5,
                                     "max_position_pct": 1.0, "max_open_risk_pct": 1.0})
        cfg = C.load_config(self.h)
        ideas, info = A.buy_ideas(self.h, cfg, lg, s, n=3, all_=True)
        capital = s["value"] + s["cash"]
        spent = sum(i.get("cost") or 0 for i in ideas)
        self.assertLessEqual(spent, s["cash"] - 0.5 * capital + 1)  # the reserve is never spent
        self.assertTrue(all(i.get("limited_by") for i in ideas if i.get("qty")))


class TestSIP(Market):
    def test_projection_and_goal(self):
        self.assertEqual(SP.project(1000, 1, 0.0)[-1]["value"], 12000)
        v = SP.project(1000, 10, 0.12)[-1]["value"]
        self.assertAlmostEqual(v, 224036, delta=5)
        self.assertAlmostEqual(SP.required_monthly(v, 10, 0.12), 1000, delta=1)
        stepped = SP.project(1000, 2, 0.0, step_up=0.10)
        self.assertEqual((stepped[1]["monthly"], stepped[-1]["invested"]), (1100.0, 25200.0))
        self.assertEqual(SP.required_monthly(100, 5, 0.1, lump=1000), 0.0)

    def test_rate_sources(self):
        run(pkdata.main, ["--home", self.h, "mufap", "--from-file", os.path.join(FIX, "mufap-2026-10-26.md")])
        rate, why = SP.fund_rate(self.h, "ABL Cash Fund")
        self.assertAlmostEqual(rate, 0.1678)                        # annualised 3-year, as MUFAP reports it
        rates, src = SP.market_rates(self.h, C.load_config(self.h))
        self.assertIn("MUFAP", src["money_market"])
        self.assertIn("KSE100", src["equity"])
        rc, out = run(SP.main, ["--home", self.h, "plan", "--monthly", "10000", "--years", "5"])
        self.assertIn("moderate profile mix", out)
        rc, out = run(SP.main, ["--home", self.h, "goal", "--target", "1000000", "--years", "5", "--rate", "12"])
        self.assertIn("a month", out)


class TestDocs(unittest.TestCase):
    """The README must keep up with the code: every tool and every setting is documented."""

    def setUp(self):
        with open(os.path.join(ROOT, "README.md")) as f:
            self.readme = f.read()

    def test_every_script_is_in_the_readme(self):
        scripts = sorted(f for f in os.listdir(os.path.join(ROOT, "psx-mufap", "scripts"))
                         if f.endswith((".py", ".sh")) and f not in ("common.py",))
        missing = [f for f in scripts if f not in self.readme]
        self.assertEqual(missing, [], "add these to README.md")

    def test_every_setting_is_in_the_readme(self):
        keys = set(PRF.VARIABLES) | set(C.DEFAULT_CONFIG)
        missing = sorted(k for k in keys if "`%s`" % k not in self.readme and '"%s"' % k not in self.readme)
        self.assertEqual(missing, [], "document these settings in README.md")


def argparse_ns(**kw):
    import argparse
    return argparse.Namespace(**kw)


if __name__ == "__main__":
    unittest.main()
