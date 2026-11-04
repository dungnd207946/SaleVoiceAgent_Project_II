import asyncio
import sys

from tests.bench_estate.cli import main

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
