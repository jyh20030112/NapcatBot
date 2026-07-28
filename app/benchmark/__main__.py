"""CLI entry point for NapcatBot pipeline benchmark.

Usage:
    python -m app.benchmark [--iterations N] [--scenarios ...] [--output PATH] [--no-breakdown]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .runner import BenchmarkRunner
from .scenarios import ALL_SCENARIOS

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s | %(name)s | %(message)s",
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="NapcatBot pipeline latency benchmark — measures end-to-end "
        "message handling time across different scenarios.",
    )
    parser.add_argument(
        "-n",
        "--iterations",
        type=int,
        default=50,
        help="Number of runs per scenario (default: 50)",
    )
    parser.add_argument(
        "-s",
        "--scenarios",
        nargs="*",
        choices=list(ALL_SCENARIOS),
        help="Specific scenarios to run (default: all)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="data/benchmark_results.json",
        help="JSON output file path (default: data/benchmark_results.json)",
    )
    parser.add_argument(
        "--no-breakdown",
        action="store_true",
        help="Suppress per-stage breakdown in terminal output",
    )
    parser.add_argument(
        "--real-llm",
        action="store_true",
        help="Use real LLM calls (reads API key from .env). "
        "WARNING: costs API credits! Reduce --iterations to 3-5.",
    )
    args = parser.parse_args(argv)

    if args.real_llm and args.iterations > 10:
        print(
            "⚠  WARNING: --real-llm with >10 iterations will cost API credits. "
            "Consider --iterations 3"
        )

    runner = BenchmarkRunner(
        iterations=args.iterations,
        scenarios=args.scenarios or None,
        output_path=args.output,
        show_breakdown=not args.no_breakdown,
        real_llm=args.real_llm,
    )

    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        print("\nBenchmark interrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
