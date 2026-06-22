import sys

from src.run_daily import run


if __name__ == "__main__":
    argv = ["--init" if arg == "--backfill" else arg for arg in sys.argv[1:]]
    run(argv)
