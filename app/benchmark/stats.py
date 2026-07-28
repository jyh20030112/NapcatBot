"""Statistics computation and output formatting for benchmark results."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_CN_TZ = timezone(timedelta(hours=8))


def compute_stage_stats(
    scenario_name: str,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute aggregate statistics for a list of iteration samples.

    Each sample is a dict with:
    - ``total_ms``: float
    - ``stages``: dict of stage_name → elapsed_ms
    - ``topic_id``, ``action``, etc: metadata
    """
    total_values = [s["total_ms"] for s in samples]

    stage_names: list[str] = []
    if samples:
        stage_names = list(samples[0].get("stages", {}))

    result: dict[str, Any] = {
        "scenario": scenario_name,
        "iterations": len(samples),
        "total": _describe(total_values),
    }

    if stage_names:
        breakdown: dict[str, dict[str, float]] = {}
        for name in stage_names:
            values = [s["stages"].get(name, 0.0) for s in samples]
            breakdown[name] = _describe(values)
        result["breakdown"] = breakdown

    return result


def format_terminal(all_stats: list[dict[str, Any]], *, show_breakdown: bool = True) -> str:
    """Format benchmark results as a plain-text terminal report."""
    lines: list[str] = []

    total_iters = sum(s["iterations"] for s in all_stats)
    lines.append("=" * 72)
    lines.append(f"  NapcatBot Pipeline Benchmark  ({total_iters} total iterations)")
    lines.append("=" * 72)
    lines.append("")

    # -------- Summary table --------
    header = f" {'Scenario':<22} {'Avg':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'Stdev':>8} {'Min':>8} {'Max':>8}"
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)

    for s in all_stats:
        t = s["total"]
        lines.append(
            f" {s['scenario']:<22} "
            f"{t['avg']:>7.2f} "
            f"{t['p50']:>7.2f} "
            f"{t['p95']:>7.2f} "
            f"{t['p99']:>7.2f} "
            f"{t['stddev']:>7.2f} "
            f"{t['min']:>7.2f} "
            f"{t['max']:>7.2f}"
        )
    lines.append(sep)
    lines.append("  Unit: milliseconds (ms)")
    lines.append("")

    # -------- Stage breakdown --------
    if show_breakdown:
        stage_names: list[str] = []
        for s in all_stats:
            if "breakdown" in s:
                stage_names = list(s["breakdown"])
                break

        if stage_names:
            lines.append("Stage Breakdown (avg ms):")
            lines.append("")

            # Build a column per stage
            col_width = max(len(n) for n in stage_names) + 2
            scenario_width = max(len(s["scenario"]) for s in all_stats) + 2

            # Header row
            header = " " * scenario_width
            for name in stage_names:
                header += f" {name:>{col_width - 1}}"
            lines.append(header)

            # Data rows
            for s in all_stats:
                row = f" {s['scenario']:<{scenario_width - 1}}"
                breakdown = s.get("breakdown", {})
                for name in stage_names:
                    if name in breakdown:
                        row += f" {breakdown[name]['avg']:>{col_width - 1}.2f}"
                    else:
                        row += f" {'—':>{col_width - 1}}"
                lines.append(row)

            lines.append("")

    return "\n".join(lines)


def write_json_log(all_stats: list[dict[str, Any]], output_path: str | Path, *, raw_samples: list[dict[str, Any]] | None = None) -> None:
    """Write per-scenario aggregate statistics as a JSON file.

    If *raw_samples* is provided they are included as per-iteration detail.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc: dict[str, Any] = {
        "timestamp": datetime.now(_CN_TZ).isoformat(timespec="seconds"),
        "total_iterations": sum(s["iterations"] for s in all_stats),
        "scenarios": all_stats,
    }
    if raw_samples:
        doc["raw_samples"] = raw_samples

    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _describe(values: list[float]) -> dict[str, float]:
    if not values:
        return {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "stddev": 0, "min": 0, "max": 0, "count": 0}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    return {
        "avg": round(statistics.mean(values), 3),
        "p50": round(_percentile(sorted_vals, n, 50), 3),
        "p95": round(_percentile(sorted_vals, n, 95), 3),
        "p99": round(_percentile(sorted_vals, n, 99), 3),
        "stddev": round(statistics.stdev(values) if n > 1 else 0.0, 3),
        "min": round(sorted_vals[0], 3),
        "max": round(sorted_vals[-1], 3),
        "count": n,
    }


def _percentile(sorted_vals: list[float], n: int, p: int) -> float:
    """Compute the p-th percentile of a sorted list (nearest-rank method)."""
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    rank = (p / 100.0) * (n - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return sorted_vals[lower]
    frac = rank - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac
