import csv
import json
from contextlib import closing
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from demo_futures.backtest import BacktestEngine, FundingEvent, EquityPoint, metrics
from demo_futures.backtest_cli import load_history, main
from demo_futures.data import Candle, SQLiteStore
from demo_futures.reporting import write_report
from demo_futures.risk import BacktestConfig, ContractSpec
from demo_futures.strategy import Signal

SPEC = ContractSpec(".01", ".001", ".001", "1")


def candle(index, opening=100, high=101, low=99, close=100, start=0):
    timestamp = start + index * 300000
    return Candle(timestamp, opening, high, low, close, 100, timestamp + 299999, 10000, 10)


class Scripted:
    version = "synthetic-test-only"
    def __init__(self, actions, atr=1):
        self.actions, self.atr = actions, atr
    def signals(self, candles):
        return [Signal(self.actions.get(i, "NO TRADE"), "Synthetic timing fixture", self.atr)
                for i in range(len(candles))]


def run(candles, actions=None, config=None, funding=None, markets=None):
    cfg = config or BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0, allow_missing_funding=True)
    return BacktestEngine(cfg, {"BTCUSDT": SPEC, "ETHUSDT": SPEC}, Scripted(actions or {})).run(
        markets or {"BTCUSDT": candles}, funding=funding)


class BacktestTests(unittest.TestCase):
    def test_signal_enters_next_bar_and_final_signal_never_fills(self):
        result = run([candle(0), candle(1, close=101)], {0: "LONG", 1: "SHORT"})
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.signal_time, 299999)
        self.assertEqual(trade.entry_time, 300000)
        self.assertEqual(trade.exit_time, 599999)
        self.assertEqual(trade.net_pnl, D(25))
        self.assertEqual(trade.exit_reason, "end_of_data")
        self.assertTrue(any(d.action == "NO_NEXT_BAR" for d in result.decisions))

    def test_long_cost_accounting_no_double_slippage(self):
        cfg = BacktestConfig(fee_rate=".001", slippage_rate=".001", funding_reserve_rate=0, allow_missing_funding=True)
        result = run([candle(0), candle(1, close=101)], {0: "LONG"}, cfg)
        t = result.trades[0]
        self.assertEqual(t.entry_price, D("100.10"))
        self.assertEqual(t.exit_price, D("100.89"))
        self.assertEqual(t.gross_pnl, t.quantity)
        self.assertEqual(t.slippage_cost, t.quantity * D(".21"))
        self.assertEqual(t.fees, t.quantity * D(".20099"))
        self.assertEqual(t.net_pnl, t.quantity * D(".58901"))
        self.assertEqual(result.metrics["final_equity"] - cfg.initial_equity, t.net_pnl)

    def test_short_pnl_and_costs_hand_calculated(self):
        cfg = BacktestConfig(fee_rate=".001", slippage_rate=".001", funding_reserve_rate=0, allow_missing_funding=True)
        result = run([candle(0), candle(1, close=99)], {0: "SHORT"}, cfg)
        t = result.trades[0]
        self.assertEqual(t.entry_price, D("99.90"))
        self.assertEqual(t.exit_price, D("99.10"))
        self.assertEqual(t.net_pnl, t.quantity * D(".601"))
        self.assertEqual(t.net_pnl, t.gross_pnl - t.fees - t.slippage_cost - t.funding_cost)

    def test_stop_wins_when_both_levels_touched(self):
        result = run([candle(0), candle(1, high=104, low=97)], {0: "LONG"})
        self.assertEqual(result.trades[0].exit_reason, "stop_loss_both_touched")
        self.assertEqual(result.trades[0].exit_price, D(98))
        self.assertEqual(result.metrics["net_pnl"], D(-50))

    def test_short_stop_wins_ambiguous_bar(self):
        result = run([candle(0), candle(1, high=103, low=96)], {0: "SHORT"})
        self.assertEqual(result.trades[0].exit_price, D(102))
        self.assertEqual(result.trades[0].exit_reason, "stop_loss_both_touched")

    def test_stop_gap_uses_open_not_guaranteed_stop_and_blocks_entries(self):
        rows = [candle(0), candle(1), candle(2, 90, 91, 89, 90), candle(3, 90, 91, 89, 90)]
        result = run(rows, {0: "LONG", 1: "LONG", 2: "LONG"})
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.exit_price, D(90))
        self.assertEqual(trade.exit_time, 600000)
        self.assertLess(trade.net_pnl, -trade.risk_budget)
        self.assertEqual(trade.exit_reason, "stop_gap")
        self.assertTrue(any("daily loss halt" in d.reason for d in result.decisions))

    def test_gap_target_has_no_favorable_price_improvement(self):
        result = run([candle(0), candle(1), candle(2, 110, 111, 109, 110)], {0: "LONG"})
        self.assertEqual(result.trades[0].exit_reference, D(103))
        self.assertEqual(result.trades[0].exit_reason, "target_gap_no_improvement")

    def test_funding_signed_long_pays_short_receives(self):
        event = FundingEvent(450000, ".001", 100)
        for side, expected in (("LONG", D("2.5")), ("SHORT", D("-2.5"))):
            with self.subTest(side=side):
                result = run([candle(0), candle(1)], {0: side}, funding={"BTCUSDT": [event]})
                self.assertEqual(result.trades[0].funding_cost, expected)
                self.assertEqual(result.trades[0].net_pnl, -expected)

    def test_funding_at_entry_excluded_but_existing_position_pays_before_gap_exit(self):
        events = [FundingEvent(300000, ".001", 100), FundingEvent(600000, ".001", 100)]
        result = run([candle(0), candle(1), candle(2, 90, 91, 89, 90)], {0: "LONG"}, funding={"BTCUSDT": events})
        self.assertEqual(result.trades[0].funding_cost, D("2.5"))

    def test_funding_fallback_uses_known_open_not_future_close(self):
        result = run([candle(0), candle(1, close=101)], {0: "LONG"}, funding={"BTCUSDT": [FundingEvent(450000, ".001")]})
        self.assertEqual(result.trades[0].funding_cost, D("2.5"))
        self.assertEqual(result.trades[0].funding_mark_fallbacks, 1)

    def test_holding_time_limit(self):
        cfg = BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0, max_holding_bars=1, allow_missing_funding=True)
        result = run([candle(0), candle(1), candle(2)], {0: "LONG"}, cfg)
        self.assertEqual(result.trades[0].exit_reason, "holding_time_limit")

    def test_no_pyramiding(self):
        result = run([candle(i) for i in range(4)], {0: "LONG", 1: "LONG", 2: "LONG"})
        self.assertEqual(len(result.trades), 1)
        self.assertTrue(any("pyramiding prohibited" in d.reason for d in result.decisions))

    def test_shared_portfolio_cap_and_deterministic_priority(self):
        rows = [candle(0), candle(1)]
        result = run(rows, {0: "LONG"}, markets={"ETHUSDT": rows, "BTCUSDT": rows})
        self.assertEqual([t.symbol for t in result.trades], ["BTCUSDT"])
        self.assertTrue(any(d.symbol == "ETHUSDT" and "position cap" in d.reason for d in result.decisions))

    def test_cumulative_daily_loss_halt_and_reduced_sizing(self):
        rows = [candle(0)] + [candle(i, high=101, low=97) for i in range(1, 9)]
        result = run(rows, {i: "LONG" for i in range(8)})
        self.assertEqual(len(result.trades), 5)
        sizes = [t.quantity for t in result.trades]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertTrue(all(t.planned_loss <= t.risk_budget for t in result.trades))
        self.assertTrue(any("daily loss halt" in d.reason for d in result.decisions))

    def test_unrealized_loss_triggers_conservative_daily_flatten(self):
        rows = [candle(0)] + [candle(i, high=101, low=97) for i in range(1, 5)] + [candle(5)]
        result = run(rows, {i: "LONG" for i in range(5)})
        self.assertEqual(result.trades[-1].exit_reason, "daily_loss_intrabar_conservative")
        self.assertEqual(result.trades[-1].exit_reference, D(99))

    def test_halt_resets_at_utc_day_boundary_only(self):
        rows = [candle(0), candle(1)] + [candle(i, 90, 91, 89, 90) for i in range(2, 290)]
        result = run(rows, {0: "LONG", 2: "LONG", 287: "LONG"})
        self.assertEqual(len(result.trades), 2)
        self.assertEqual(result.trades[1].entry_time, 86400000)
        self.assertLess(result.trades[1].quantity, result.trades[0].quantity)

    def test_zero_trade_baseline_and_undefined_metrics(self):
        result = run([candle(0), candle(1)])
        self.assertEqual(result.metrics["net_pnl"], 0)
        self.assertEqual(result.no_trade_metrics["net_pnl"], 0)
        self.assertIsNone(result.metrics["win_rate_pct"])
        self.assertIsNone(result.metrics["profit_factor"])
        self.assertEqual(result.metrics["profit_factor_status"], "no_trades")

    def test_drawdown_includes_unrealized_path_and_recovery(self):
        points = [EquityPoint(0, D(10000), "start"), EquityPoint(1, D(11000), "peak"),
                  EquityPoint(2, D(8800), "trough"), EquityPoint(3, D(10000), "recovered")]
        result = metrics([], points, 10000)
        self.assertEqual(result["maximum_drawdown"], 2200)
        self.assertEqual(result["maximum_drawdown_pct"], 20)

    def test_positive_and_negative_trade_profit_factor(self):
        wins = run([candle(0), candle(1, high=104)], {0: "LONG"}).trades
        loss = run([candle(0), candle(1, low=97)], {0: "LONG"}).trades
        points = [EquityPoint(0, D(10000), "start"), EquityPoint(1, D(10025), "end")]
        result = metrics(wins + loss, points, 10000)
        self.assertEqual(result["profit_factor"], D("1.5"))
        self.assertEqual(result["win_rate_pct"], 50)

    def test_bad_history_alignment_and_funding_rejected(self):
        with self.assertRaises(ValueError):
            run([candle(0), candle(2)])
        with self.assertRaises(ValueError):
            run([candle(0)], markets={"BTCUSDT": [candle(0)], "ETHUSDT": [candle(1)]})
        cfg = BacktestConfig()
        with self.assertRaises(ValueError):
            run([candle(0)], config=cfg)
        with self.assertRaises(ValueError):
            run([candle(0)], funding={"BTCUSDT": [FundingEvent(1, 0), FundingEvent(1, 0)]})
        with self.assertRaises(ValueError):
            FundingEvent(1, "NaN")

    def test_engine_reproducibility_and_data_hash(self):
        rows = [candle(0), candle(1, close=101)]
        first, second = run(rows, {0: "LONG"}), run(rows, {0: "LONG"})
        self.assertEqual(first.trades, second.trades)
        self.assertEqual(first.decisions, second.decisions)
        self.assertEqual(first.equity, second.equity)
        self.assertEqual(first.data_hash, second.data_hash)
        changed = run([rows[0], replace(rows[1], close=100)], {0: "LONG"})
        self.assertNotEqual(first.data_hash, changed.data_hash)

    def test_reports_have_journals_config_hash_and_no_nonfinite_metrics(self):
        result = run([candle(0), candle(1, close=101)], {0: "LONG"})
        with tempfile.TemporaryDirectory() as temp:
            report = write_report(result, temp)
            payload = json.loads((Path(temp) / "report.json").read_text())
            self.assertEqual(report["data_sha256"], payload["data_sha256"])
            self.assertEqual(len(payload["configuration_sha256"]), 64)
            with (Path(temp) / "trades.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertIn("funding_cost", rows[0])
            self.assertTrue((Path(temp) / "decisions.csv").is_file())
            self.assertTrue((Path(temp) / "equity.csv").is_file())

    def test_readonly_sqlite_and_offline_cli_never_load_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.sqlite3"
            store = SQLiteStore(path)
            for symbol in ("BTCUSDT", "ETHUSDT"):
                store.upsert_candles(symbol, "5m", [candle(0), candle(1)])
            before = path.read_bytes()
            with patch("demo_futures.config.Settings.load", side_effect=AssertionError("No credential loading")):
                self.assertEqual(main(["--db", str(path), "--allow-missing-funding", "--output", str(Path(temp) / "report")]), 0)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(load_history(path, ["BTCUSDT"], "5m")[0]["BTCUSDT"]), 2)

    def test_daily_halt_rechecked_between_same_open_entries(self):
        cfg = BacktestConfig(fee_rate=".001", slippage_rate=0, funding_reserve_rate=0,
                             max_positions=2, daily_loss_fraction=".00005", allow_missing_funding=True)
        rows = [candle(0), candle(1)]
        result = run(rows, {0: "LONG"}, cfg, markets={"BTCUSDT": rows, "ETHUSDT": rows})
        self.assertEqual([t.symbol for t in result.trades], ["BTCUSDT"])
        self.assertTrue(any(d.symbol == "ETHUSDT" and d.action == "REJECTED"
                            and "daily loss halt" in d.reason for d in result.decisions))

    def test_two_positions_share_remaining_portfolio_leverage(self):
        cfg = BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0,
                             max_positions=2, allow_missing_funding=True)
        rows = [candle(0), candle(1)]
        result = BacktestEngine(cfg, {"BTCUSDT": SPEC, "ETHUSDT": SPEC},
                                Scripted({0: "LONG"}, atr=".2")).run({"BTCUSDT": rows, "ETHUSDT": rows})
        self.assertEqual(len(result.trades), 2)
        self.assertLessEqual(sum(t.quantity * t.entry_price for t in result.trades), D(20000))
        self.assertTrue(all(t.planned_loss <= t.risk_budget for t in result.trades))

    def test_decimal_funding_roundoff_tolerated_but_material_mismatch_rejected(self):
        event = FundingEvent(450000, ".000123456789123456789", "100.123456789123456789")
        result = run([candle(0), candle(1, close=101)], {0: "LONG"}, funding={"BTCUSDT": [event]})
        self.assertLessEqual(abs(result.metrics["accounting_residual_usdt"]), D("1e-12"))
        broken = [EquityPoint(0, D(10000), "start"), EquityPoint(1, D(10025), "wrong")]
        with self.assertRaises(ArithmeticError):
            metrics(result.trades, broken, 10000)

    def test_supported_intervals_and_both_symbols_execute_offline(self):
        for interval, duration in (("5m", 300000), ("15m", 900000), ("1h", 3600000), ("4h", 14400000)):
            with self.subTest(interval=interval):
                rows = [replace(candle(i), open_time=i*duration, close_time=(i+1)*duration-1) for i in range(2)]
                cfg = BacktestConfig(fee_rate=0, slippage_rate=0, funding_reserve_rate=0,
                                     max_positions=2, allow_missing_funding=True)
                result = BacktestEngine(cfg, {"BTCUSDT": SPEC, "ETHUSDT": SPEC}, Scripted({0: "LONG"})).run(
                    {"BTCUSDT": rows, "ETHUSDT": rows}, interval=interval)
                self.assertEqual({t.symbol for t in result.trades}, {"BTCUSDT", "ETHUSDT"})
                self.assertTrue(all(t.entry_time == duration for t in result.trades))

    def test_root_backtest_route_does_not_import_authenticated_cli(self):
        import runpy, sys
        root = Path(__file__).resolve().parents[1]
        route = runpy.run_path(str(root / "run.py"))["main"]
        with patch.dict(sys.modules, {"demo_futures.cli": None}):
            with self.assertRaises(SystemExit) as stopped:
                route(["backtest", "--help"])
            self.assertEqual(stopped.exception.code, 0)

    def test_original_phase1_help_route_still_works_without_credentials(self):
        import runpy
        route = runpy.run_path(str(Path(__file__).resolve().parents[1] / "run.py"))["main"]
        with patch("demo_futures.config.Settings.load", side_effect=AssertionError("No credential access")):
            with self.assertRaises(SystemExit) as stopped:
                route(["--help"])
            self.assertEqual(stopped.exception.code, 0)

    def test_unknown_intrabar_exit_does_not_receive_unproven_funding_credit(self):
        event = FundingEvent(450000, ".001", 100)
        result = run([candle(0), candle(1, low=96)], {0: "SHORT"}, funding={"BTCUSDT": [event]})
        t = result.trades[0]
        self.assertEqual(t.exit_reason, "take_profit")
        self.assertEqual(t.funding_cost, 0)
        self.assertEqual(t.uncertain_funding_credits_skipped, 1)
        self.assertEqual(t.net_pnl, D(75))
        # Debits remain conservatively charged on an unknown-time exit bar.
        result = run([candle(0), candle(1, high=104)], {0: "LONG"}, funding={"BTCUSDT": [event]})
        self.assertEqual(result.trades[0].funding_cost, D("2.5"))
