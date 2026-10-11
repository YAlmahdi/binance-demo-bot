"""Synthetic engineering fixtures, never evidence of historical returns."""
import math
from demo_futures.data import Candle
from demo_futures.ml_research.config import START, STEP
from demo_futures.ml_research.opportunities import Opportunity
from demo_futures.strategy import Signal


def candle(index, opening=100, high=101, low=99, close=100, start=START):
    time = start + index*STEP
    return Candle(time, opening, high, low, close, 100, time+STEP-1, 10000, 10)


def history(count=700, direction=1):
    result = []
    for i in range(count):
        p = 100 + direction*i*.05 + math.sin(i/3)
        c = candle(i, p, p+1, p-1, p)
        result.append(Candle(c.open_time,c.open,c.high,c.low,c.close,100+i%13,c.close_time,c.quote_volume,c.trades))
    return result


def opportunity(candles, index=0, side="LONG", symbol="BTCUSDT", atr=1):
    time = candles[index].close_time
    return Opportunity(f"{symbol}:{time}", symbol, time, index, Signal(side,"Synthetic isolated fixture",atr))
