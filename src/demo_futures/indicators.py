"""Causal standard-library indicators with explicit seed conventions."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


def _inputs(values, period):
    if type(period) is not int or period < 1:
        raise ValueError("Period must be a positive integer")
    result = [float(x) for x in values]
    if not all(math.isfinite(x) for x in result):
        raise ValueError("Indicator inputs must be finite")
    return result


def sma(values, period):
    values = _inputs(values, period)
    result = [None] * len(values)
    window = deque()
    total = 0.0
    for i, value in enumerate(values):
        window.append(value)
        total += value
        if len(window) > period:
            total -= window.popleft()
        if len(window) == period:
            result[i] = total / period
    return result


def ema(values, period):
    values = _inputs(values, period)
    result = [None] * len(values)
    if len(values) < period:
        return result
    previous = sum(values[:period]) / period
    result[period - 1] = previous
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        previous += alpha * (values[i] - previous)
        result[i] = previous
    return result


def rsi(values, period=14):
    values = _inputs(values, period)
    result = [None] * len(values)
    if len(values) <= period:
        return result
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gain = sum(max(x, 0.0) for x in changes[:period]) / period
    loss = sum(max(-x, 0.0) for x in changes[:period]) / period

    def score(g, l):
        return 50.0 if g == l == 0 else (100.0 if l == 0 else 100.0 - 100.0 / (1 + g / l))

    result[period] = score(gain, loss)
    for i in range(period + 1, len(values)):
        change = changes[i - 1]
        gain = (gain * (period - 1) + max(change, 0.0)) / period
        loss = (loss * (period - 1) + max(-change, 0.0)) / period
        result[i] = score(gain, loss)
    return result


def atr(candles, period=14):
    candles = list(candles)
    ranges = []
    for i, candle in enumerate(candles):
        true_range = candle.high - candle.low
        if i:
            true_range = max(true_range, abs(candle.high - candles[i - 1].close),
                             abs(candle.low - candles[i - 1].close))
        ranges.append(true_range)
    ranges = _inputs(ranges, period)
    if any(x < 0 for x in ranges):
        raise ValueError("Invalid candle range")
    result = [None] * len(ranges)
    if len(ranges) >= period:
        previous = sum(ranges[:period]) / period
        result[period - 1] = previous
        for i in range(period, len(ranges)):
            previous = (previous * (period - 1) + ranges[i]) / period
            result[i] = previous
    return result


def macd(values, fast=12, slow=26, signal=9):
    if fast >= slow:
        raise ValueError("MACD fast period must be less than slow period")
    fast_values, slow_values = ema(values, fast), ema(values, slow)
    line = [None if a is None or b is None else a - b for a, b in zip(fast_values, slow_values)]
    available = [value for value in line if value is not None]
    compact_signal = ema(available, signal)
    signal_values = [None] * len(line)
    j = 0
    for i, value in enumerate(line):
        if value is not None:
            signal_values[i] = compact_signal[j]
            j += 1
    histogram = [None if a is None or b is None else a - b for a, b in zip(line, signal_values)]
    return line, signal_values, histogram


def relative_volume(values, period=20):
    values = _inputs(values, period)
    if any(x < 0 for x in values):
        raise ValueError("Volume cannot be negative")
    means = sma(values, period)
    return [None if i < period or not means[i - 1] else value / means[i - 1]
            for i, value in enumerate(values)]


@dataclass(frozen=True)
class Features:
    ema20: float | None
    ema50: float | None
    ema200: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    atr14: float | None
    relative_volume: float | None


def build_features(candles):
    candles = list(candles)
    closes = [c.close for c in candles]
    m, signal, hist = macd(closes)
    columns = [ema(closes, 20), ema(closes, 50), ema(closes, 200), rsi(closes),
               m, signal, hist, atr(candles), relative_volume([c.volume for c in candles])]
    return [Features(*row) for row in zip(*columns)]
