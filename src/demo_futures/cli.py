import argparse
from datetime import datetime, timezone
import json
import logging
import time
from pathlib import Path

from .client import DemoClient, APIError
from .config import Settings, SafetyError, SYMBOLS, INTERVALS
from .collector import collect
from .data import SQLiteStore, DataQualityError


def utc_ms(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError()
        return int(dt.astimezone(timezone.utc).timestamp() * 1000)
    except ValueError:
        raise argparse.ArgumentTypeError("Use ISO UTC timestamp, e.g. 2026-10-01T00:00:00Z") from None


def main():
    parser = argparse.ArgumentParser(description="Binance Demo infrastructure — phase 1, no trading")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-public")
    commands.add_parser("check-account")
    gather = commands.add_parser("collect")
    gather.add_argument("--start", required=True, type=utc_ms)
    gather.add_argument("--end", type=utc_ms)
    gather.add_argument("--symbols", nargs="+", choices=SYMBOLS, default=list(SYMBOLS))
    gather.add_argument("--intervals", nargs="+", choices=tuple(INTERVALS), default=list(INTERVALS))
    gather.add_argument("--db", type=Path, default=Path("data/market.sqlite3"))
    order = commands.add_parser("test-order", help="Validates a LIMIT order; creates no order/position")
    order.add_argument("--symbol", choices=SYMBOLS, required=True)
    order.add_argument("--side", choices=("BUY", "SELL"), required=True)
    order.add_argument("--quantity", required=True)
    order.add_argument("--price", required=True)
    args = parser.parse_args()
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=logging.INFO, format="%(asctime)sZ %(levelname)s %(name)s %(message)s")
    try:
        client = DemoClient(Settings.load(args.env_file))
        if args.command == "check-public":
            result = {"environment": "demo", "rest_origin": client.settings.base_url,
                      "server_time_ms": client.verify(), "status": "connected", "execution_enabled": False}
        elif args.command == "check-account":
            result = client.account_check()
        elif args.command == "test-order":
            client.test_order(args.symbol, args.side, args.quantity, args.price)
            result = {"status": "test_order_validated", "order_created": False}
        else:
            result = collect(client, SQLiteStore(args.db), args.start, args.end, args.symbols, args.intervals)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (APIError, SafetyError, DataQualityError) as exc:
        logging.error("%s", exc)
        return 1
    except Exception:
        # Unexpected parsing/transport errors also stop the process without revealing secrets.
        logging.error("Unexpected response or local I/O failure; stopped. Run offline tests and check connectivity.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
