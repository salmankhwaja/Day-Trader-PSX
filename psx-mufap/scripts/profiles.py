"""Every variable that drives a buy, sell or hold suggestion, and four ready-made risk styles.

How settings are layered (later wins):
  1. built-in defaults (common.DEFAULT_CONFIG)
  2. your risk profile's values (config.json "risk_profile": conservative | moderate |
     aggressive | very_aggressive; set it with `risk.py quiz` or `risk.py profile NAME`)
  3. anything you set yourself in config.json

So you can pick a profile and still override single values, e.g. keep "moderate" but set
"max_holdings": 6. `risk.py settings` shows every value and where it came from.

Higher-risk profiles aim for more return by taking bigger positions, wider stops, more
momentum and fewer, more concentrated holdings. That raises the chance of large losses as well
as large gains: no setting maximises profit without also raising risk.
"""

# key: (group, description, how to read the number)
VARIABLES = {
    # --- screening and ranking
    "min_avg_volume": ("screen", "skip shares averaging fewer than this many shares traded a day (60 sessions), with --all", "shares/day"),
    "score_weights": ("screen", "how the ranking score weighs 1M, 3M, 6M, 1Y returns and the 1Y Sharpe ratio", "relative weights"),
    "candidates": ("screen", "how many top-ranked shares get backtested for buy ideas", "count"),
    # --- backtest gates a buy idea must pass (on the untouched out-of-sample period)
    "train_split": ("backtest", "share of history used to tune a strategy; the rest is the out-of-sample test", "fraction"),
    "strategies": ("backtest", "strategies tried for each share", "list"),
    "gate_max_drawdown": ("backtest", "largest acceptable out-of-sample fall from peak", "fraction"),
    "gate_min_sharpe": ("backtest", "minimum out-of-sample Sharpe ratio", "ratio"),
    "gate_min_excess_return": ("backtest", "out-of-sample yearly return must beat cash (risk_free_annual) by at least this", "fraction/year"),
    "max_per_sector": ("backtest", "most buy ideas from one sector", "count"),
    # --- stops and targets
    "stop_atr_mult": ("stops", "stop distance = this x the average daily move", "multiple"),
    "vol_window": ("stops", "days used for the average daily move", "days"),
    "min_stop_pct": ("stops", "stop at least this far below entry (so daily noise doesn't trigger it)", "fraction"),
    "max_stop_pct": ("stops", "stop at most this far below entry", "fraction"),
    "target_r": ("stops", "target = entry + this x (entry - stop)", "multiple"),
    "stop_limit_gap": ("stops", "order tickets: a stop-loss order's limit price sits this far below its trigger, "
                       "so it still fills when the price drops fast", "fraction"),
    # --- position sizing and portfolio limits
    "risk_per_trade": ("sizing", "capital lost if a new buy hits its stop", "fraction of capital"),
    "max_position_pct": ("sizing", "most of the portfolio in one share (above it: TRIM)", "fraction"),
    "max_holdings": ("sizing", "most different shares held at once (no buy ideas beyond it)", "count"),
    "cash_reserve_pct": ("sizing", "cash kept aside, never used for buy ideas", "fraction"),
    "max_open_risk_pct": ("sizing", "total capital at risk if every holding hit its stop at once", "fraction"),
    # --- reviewing holdings
    "trend_fast": ("review", "short moving average for the trend test", "days"),
    "trend_slow": ("review", "long moving average for the trend test", "days"),
    "review_lag_pct": ("review", "REVIEW when 3-month return trails KSE-100 by more than this (and the trend is down)", "fraction"),
    # --- funds
    "fund_review_bottom": ("funds", "REVIEW a fund you hold in this bottom share of its category", "fraction"),
    "fund_stale_days": ("funds", "leave out funds whose NAV is older than this", "days"),
    # --- allocation, loss tolerance, SIP
    "allocation": ("plan", "target split between shares, fixed income and money market", "fractions"),
    "max_annual_loss_pct": ("plan", "the worst year you said you could live with (from the risk quiz)", "fraction"),
    "expected_returns": ("plan", "assumed yearly returns for the SIP calculator, when no data is on file", "fraction/year"),
}

PROFILES = {
    "conservative": {
        "min_avg_volume": 100000, "candidates": 15,
        "score_weights": {"1m": 0.5, "3m": 1.0, "6m": 1.0, "1y": 1.5, "sharpe": 2.0},
        "train_split": 0.7, "strategies": ["sma", "breakout", "rsi"],
        "gate_max_drawdown": 0.20, "gate_min_sharpe": 0.5, "gate_min_excess_return": 0.02, "max_per_sector": 1,
        "stop_atr_mult": 2.0, "vol_window": 14, "min_stop_pct": 0.04, "max_stop_pct": 0.10, "target_r": 2.0, "stop_limit_gap": 0.01,
        "risk_per_trade": 0.005, "max_position_pct": 0.15, "max_holdings": 12, "cash_reserve_pct": 0.30,
        "max_open_risk_pct": 0.03,
        "trend_fast": 50, "trend_slow": 200, "review_lag_pct": 0.03,
        "fund_review_bottom": 0.5, "fund_stale_days": 5,
        "allocation": {"equity": 0.20, "fixed_income": 0.40, "money_market": 0.40}, "max_annual_loss_pct": 0.10,
    },
    "moderate": {
        "min_avg_volume": 50000, "candidates": 15,
        "score_weights": {"1m": 1.0, "3m": 1.0, "6m": 1.0, "1y": 1.0, "sharpe": 1.0},
        "train_split": 0.7, "strategies": ["sma", "breakout", "rsi"],
        "gate_max_drawdown": 0.35, "gate_min_sharpe": 0.0, "gate_min_excess_return": 0.0, "max_per_sector": 2,
        "stop_atr_mult": 2.5, "vol_window": 14, "min_stop_pct": 0.05, "max_stop_pct": 0.15, "target_r": 2.0, "stop_limit_gap": 0.01,
        "risk_per_trade": 0.01, "max_position_pct": 0.25, "max_holdings": 10, "cash_reserve_pct": 0.10,
        "max_open_risk_pct": 0.06,
        "trend_fast": 50, "trend_slow": 200, "review_lag_pct": 0.05,
        "fund_review_bottom": 1 / 3.0, "fund_stale_days": 5,
        "allocation": {"equity": 0.50, "fixed_income": 0.30, "money_market": 0.20}, "max_annual_loss_pct": 0.20,
    },
    "aggressive": {
        "min_avg_volume": 25000, "candidates": 20,
        "score_weights": {"1m": 1.5, "3m": 1.5, "6m": 1.0, "1y": 0.5, "sharpe": 0.5},
        "train_split": 0.7, "strategies": ["sma", "breakout", "rsi"],
        "gate_max_drawdown": 0.45, "gate_min_sharpe": 0.0, "gate_min_excess_return": 0.0, "max_per_sector": 3,
        "stop_atr_mult": 3.0, "vol_window": 14, "min_stop_pct": 0.07, "max_stop_pct": 0.20, "target_r": 2.5, "stop_limit_gap": 0.015,
        "risk_per_trade": 0.02, "max_position_pct": 0.35, "max_holdings": 8, "cash_reserve_pct": 0.05,
        "max_open_risk_pct": 0.10,
        "trend_fast": 50, "trend_slow": 200, "review_lag_pct": 0.08,
        "fund_review_bottom": 0.25, "fund_stale_days": 5,
        "allocation": {"equity": 0.75, "fixed_income": 0.15, "money_market": 0.10}, "max_annual_loss_pct": 0.30,
    },
    "very_aggressive": {
        "min_avg_volume": 10000, "candidates": 25,
        "score_weights": {"1m": 2.0, "3m": 1.5, "6m": 1.0, "1y": 0.5, "sharpe": 0.0},
        "train_split": 0.7, "strategies": ["sma", "breakout", "rsi"],
        "gate_max_drawdown": 0.55, "gate_min_sharpe": 0.0, "gate_min_excess_return": 0.0, "max_per_sector": 3,
        "stop_atr_mult": 3.5, "vol_window": 14, "min_stop_pct": 0.08, "max_stop_pct": 0.25, "target_r": 3.0, "stop_limit_gap": 0.02,
        "risk_per_trade": 0.03, "max_position_pct": 0.50, "max_holdings": 6, "cash_reserve_pct": 0.0,
        "max_open_risk_pct": 0.15,
        "trend_fast": 20, "trend_slow": 100, "review_lag_pct": 0.10,
        "fund_review_bottom": 0.25, "fund_stale_days": 5,
        "allocation": {"equity": 0.90, "fixed_income": 0.05, "money_market": 0.05}, "max_annual_loss_pct": 0.40,
    },
}
DEFAULT_PROFILE = "moderate"
ORDER = ["conservative", "moderate", "aggressive", "very_aggressive"]

# Used only when there is no data on file to derive them (see sip.py). Assumptions, not forecasts.
EXPECTED_RETURNS = {"equity": 0.14, "fixed_income": 0.11, "money_market": 0.10}


def resolve(user):
    """(merged values, {key: 'profile'|'yours'|'default'}) for a user's raw config dict."""
    from common import DEFAULT_CONFIG
    name = user.get("risk_profile", DEFAULT_PROFILE)
    if name not in PROFILES:
        raise SystemExit("config.json risk_profile %r is not one of: %s" % (name, ", ".join(ORDER)))
    cfg, src = dict(DEFAULT_CONFIG), {}
    for k in DEFAULT_CONFIG:
        src[k] = "default"
    cfg["expected_returns"] = dict(EXPECTED_RETURNS)
    src["expected_returns"] = "default"
    for k, v in PROFILES[name].items():
        cfg[k] = v
        src[k] = "profile"
    for k, v in user.items():
        cfg[k] = v
        src[k] = "yours"
    cfg["risk_profile"] = name
    src["risk_profile"] = "yours" if "risk_profile" in user else "default"
    return cfg, src
