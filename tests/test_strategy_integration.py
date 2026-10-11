"""Full baseline plus simulator checks; generated candles are test fixtures, not evidence of returns."""
import math
from dataclasses import replace
import unittest

from demo_futures.backtest import BacktestEngine
from demo_futures.data import Candle
from demo_futures.risk import BacktestConfig


def history(direction=1):
    bars = []
    for i in range(700):
        price = 100 + direction * i * .05 + math.sin(i / 3)
        bars.append(Candle(i * 300000, price, price + 1, price - 1, price,
                           100 + i % 13, (i + 1) * 300000 - 1, 10000, 10))
    return bars


class BaselineIntegrationTests(unittest.TestCase):
    def test_unmocked_baseline_executes_long_and_short_after_warmup(self):
        for symbol, direction, side in (("BTCUSDT", 1, "LONG"), ("ETHUSDT", -1, "SHORT")):
            with self.subTest(symbol=symbol):
                result = BacktestEngine(BacktestConfig(allow_missing_funding=True)).run({symbol: history(direction)})
                self.assertGreater(len(result.trades), 0)
                self.assertTrue(all(t.side == side and t.entry_time > t.signal_time for t in result.trades))
                self.assertTrue(all(t.signal_time >= 200 * 300000 - 1 for t in result.trades))
                self.assertTrue(all(t.planned_loss <= t.risk_budget for t in result.trades))
                self.assertAlmostEqual(result.metrics["final_equity"] - 10000, result.metrics["net_pnl"], places=12)

    def test_future_bars_cannot_change_earlier_decisions_fills_or_equity(self):
        original = history()
        cutoff = original[599].close_time
        changed = original[:600] + [replace(c, open=c.open*3, high=c.high*3,
                                            low=c.low*3, close=c.close*3, volume=c.volume*20)
                                    for c in original[600:]]
        engine = BacktestEngine(BacktestConfig(allow_missing_funding=True))
        first = engine.run({"BTCUSDT": original})
        second = engine.run({"BTCUSDT": changed})
        self.assertGreater(len([t for t in first.trades if t.exit_time <= cutoff]), 0)
        self.assertEqual([d for d in first.decisions if d.timestamp <= cutoff],
                         [d for d in second.decisions if d.timestamp <= cutoff])
        self.assertEqual([t for t in first.trades if t.exit_time <= cutoff],
                         [t for t in second.trades if t.exit_time <= cutoff])
        self.assertEqual([e for e in first.equity if e.timestamp <= cutoff],
                         [e for e in second.equity if e.timestamp <= cutoff])
