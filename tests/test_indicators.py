import math
import unittest
from dataclasses import replace
from unittest.mock import patch

from demo_futures.data import Candle
from demo_futures.indicators import Features, atr, build_features, ema, macd, relative_volume, rsi, sma
from demo_futures.strategy import BaselineStrategy


def bar(i, price=100, high=None, low=None, volume=100):
    return Candle(i * 300000, price, high if high is not None else price + 1,
                  low if low is not None else price - 1, price, volume, (i + 1) * 300000 - 1, volume * price, 10)


class IndicatorTests(unittest.TestCase):
    def test_sma_reference_and_warmup(self):
        self.assertEqual(sma([1, 2, 3, 4], 3), [None, None, 2, 3])

    def test_ema_20_50_200_independent_linear_reference(self):
        for period in (20, 50, 200):
            values = ema(range(1, period + 3), period)
            self.assertTrue(all(v is None for v in values[:period - 1]))
            self.assertAlmostEqual(values[period - 1], (period + 1) / 2)
            self.assertAlmostEqual(values[period], (period + 1) / 2 + 1)
            self.assertAlmostEqual(values[period + 1], (period + 1) / 2 + 2)

    def test_rsi_wilder_hand_calculation(self):
        values = rsi([10, 11, 10, 12, 11], 3)
        self.assertEqual(values[:3], [None] * 3)
        self.assertAlmostEqual(values[3], 75)
        self.assertAlmostEqual(values[4], 54.54545454545)

    def test_rsi_rising_falling_and_flat(self):
        self.assertEqual(rsi(range(20))[-1], 100)
        self.assertEqual(rsi(range(20, 0, -1))[-1], 0)
        self.assertEqual(rsi([10] * 20)[-1], 50)

    def test_atr_gap_and_wilder_smoothing(self):
        candles = [bar(0, 10, 11, 9), bar(1, 13, 14, 12), bar(2, 12, 13, 11)]
        self.assertEqual(atr(candles, 2), [None, 3, 2.5])

    def test_macd_independent_linear_reference(self):
        line, signal, hist = macd([1, 2, 3, 4, 5], 2, 3, 2)
        self.assertEqual(line, [None, None, .5, .5, .5])
        self.assertEqual(signal, [None, None, None, .5, .5])
        self.assertEqual(hist, [None, None, None, 0, 0])

    def test_macd_default_warmup(self):
        line, signal, hist = macd(range(50))
        self.assertEqual(next(i for i, v in enumerate(line) if v is not None), 25)
        self.assertEqual(next(i for i, v in enumerate(signal) if v is not None), 33)
        self.assertEqual(next(i for i, v in enumerate(hist) if v is not None), 33)

    def test_volume_excludes_current_bar_from_reference(self):
        result = relative_volume([10] * 20 + [30, 0])
        self.assertEqual(result[:20], [None] * 20)
        self.assertEqual(result[20:], [3, 0])
        self.assertIsNone(relative_volume([0] * 21)[-1])

    def test_invalid_indicator_inputs(self):
        for period in (0, -1, True):
            with self.assertRaises(ValueError):
                ema([1, 2, 3], period)
        with self.assertRaises(ValueError):
            ema([1, math.nan], 2)
        with self.assertRaises(ValueError):
            relative_volume([1, -1], 1)
        with self.assertRaises(ValueError):
            macd([1, 2], 3, 2)

    def test_every_feature_and_signal_is_invariant_to_future_data(self):
        original = [bar(i, 100 + i * .05 + math.sin(i / 3), volume=100 + i % 13) for i in range(260)]
        changed = original[:230] + [replace(c, open=c.open * 3, high=c.high * 3,
                                            low=c.low * 3, close=c.close * 3, volume=c.volume * 20)
                                   for c in original[230:]]
        self.assertEqual(build_features(original)[:230], build_features(changed)[:230])
        strategy = BaselineStrategy()
        self.assertEqual(strategy.signals(original)[:230], strategy.signals(changed)[:230])
        self.assertEqual(build_features(original[:230]), build_features(original)[:230])

    def test_baseline_long_short_no_trade_and_warmup(self):
        bullish = Features(110, 105, 100, 60, 2, 1, 1, 2, 1.2)
        bearish = Features(90, 95, 100, 40, -2, -1, -1, 2, 1.2)
        cases = [(bar(0, 115), bullish, "LONG"), (bar(0, 85), bearish, "SHORT"),
                 (bar(0, 115), replace(bullish, rsi14=80), "NO TRADE"),
                 (bar(0, 115), replace(bullish, relative_volume=.9), "NO TRADE"),
                 (bar(0, 115), replace(bullish, atr14=0), "NO TRADE"),
                 (bar(0, 115), replace(bullish, ema200=None), "NO TRADE")]
        for candle, features, side in cases:
            with self.subTest(side=side), patch("demo_futures.strategy.build_features", return_value=[features]):
                signal = BaselineStrategy().signals([candle])[0]
                self.assertEqual(signal.side, side)
                self.assertTrue(signal.reason)
