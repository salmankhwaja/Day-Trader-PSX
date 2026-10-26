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
        res, bm, missing = rank.rank_stocks(self.h, C.load_config(self.h))
        self.assertEqual(len(res), 4)
        self.assertEqual(missing, [])
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


if __name__ == "__main__":
    unittest.main()
