"""Run Phase 1 diagnostics or the separate offline Phase 2 backtest."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments and arguments[0] == "backtest":
        # Do not import the authenticated Phase 1 CLI in the offline path.
        from demo_futures.backtest_cli import main as backtest_main
        return backtest_main(arguments[1:])
    from demo_futures.cli import main as diagnostic_main
    previous = sys.argv
    try:
        sys.argv = [previous[0], *arguments]
        return diagnostic_main()
    finally:
        sys.argv = previous


if __name__ == "__main__":
    raise SystemExit(main())
