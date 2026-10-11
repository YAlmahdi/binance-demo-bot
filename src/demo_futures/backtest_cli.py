"""Separate offline entry point. Never imports Settings, client, or collector."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .backtest import BacktestEngine, FundingEvent
from .data import Candle
from .risk import BacktestConfig
from .reporting import write_report


def load_history(path, symbols, interval):
    path = Path(path).resolve()
    if path.suffix.lower() not in (".sqlite3", ".sqlite", ".db") or not path.is_file():
        raise ValueError("An existing historical SQLite database is required")
    markets, funding = {}, {}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        for symbol in symbols:
            rows = db.execute(
                "SELECT open_time,open,high,low,close,volume,close_time,quote_volume,trades "
                "FROM candles WHERE symbol=? AND interval=? ORDER BY open_time", (symbol, interval)).fetchall()
            markets[symbol] = [Candle(*row) for row in rows]
            funding[symbol] = [FundingEvent(row[0], row[1], row[2]) for row in db.execute(
                "SELECT timestamp,rate,mark_price FROM funding WHERE symbol=? ORDER BY timestamp", (symbol,))]
    return markets, funding


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline historical backtest â€” no credentials or Binance access")
    parser.add_argument("--db", type=Path, default=Path("data/market.sqlite3"))
    parser.add_argument("--symbols", nargs="+", choices=("BTCUSDT", "ETHUSDT"), default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--interval", choices=("5m", "15m", "1h", "4h"), default="5m")
    parser.add_argument("--initial-equity", default="10000")
    parser.add_argument("--fee-rate", default="0.0005", help="Per-side assumed fee fraction")
    parser.add_argument("--slippage-rate", default="0.0002", help="Per-fill assumed adverse fraction")
    parser.add_argument("--allow-missing-funding", action="store_true", help="Explicitly assume zero when funding history is absent")
    parser.add_argument("--output", type=Path, default=Path("reports/phase2-sample"))
    args = parser.parse_args(argv)
    try:
        markets, funding = load_history(args.db, args.symbols, args.interval)
        config = BacktestConfig(initial_equity=args.initial_equity, fee_rate=args.fee_rate,
                                slippage_rate=args.slippage_rate, allow_missing_funding=args.allow_missing_funding)
        result = BacktestEngine(config).run(markets, args.interval, funding)
        write_report(result, args.output)
        print("Offline backtest completed.")
        print("Trades:", result.metrics["trades"])
        print("Net PnL AFTER assumed fees, slippage and funding:", result.metrics["net_pnl"], "USDT")
        print("Maximum drawdown:", result.metrics["maximum_drawdown_pct"], "%")
        print("NO TRADE net PnL:", result.no_trade_metrics["net_pnl"], "USDT")
        print("Report:", (args.output / "report.md").resolve())
        return 0
    except (ValueError, ArithmeticError, sqlite3.Error, OSError):
        print("Backtest failed: check historical data, configuration and output path. No network or credential access was used.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
