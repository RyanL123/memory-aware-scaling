#!/usr/bin/env python3
"""Plot Prometheus metric CSVs from multiple runs for comparison."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# Ensure project root is on path for imports when run as script
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.prometheus.data_retriever import (
    AVG_ROCKSDB_BLOCK_CACHE_HIT_RATE,
    DEFAULT_STEP_SECONDS,
    NUM_TASK_SLOTS_USED,
    PROMETHEUS_METRICS,
    SOURCE_THROUGHPUT_PER_SEC,
    TOTAL_MANAGED_MEMORY_USED_BYTES,
)

# Canonical metric name -> human-readable y-axis label
CANONICAL_TO_READABLE: dict[str, str] = {
    SOURCE_THROUGHPUT_PER_SEC: "Source Throughput (records/sec)",
    TOTAL_MANAGED_MEMORY_USED_BYTES: "Total Managed Memory Used (bytes)",
    NUM_TASK_SLOTS_USED: "Num Task Slots Used",
    AVG_ROCKSDB_BLOCK_CACHE_HIT_RATE: "Avg RocksDB Block Cache Hit Rate",
}

CANONICAL_NAMES: list[str] = [name for name, _ in PROMETHEUS_METRICS]

# Fixed colors for ds2, justin, a4s (consistent across all plots)
DATASET_COLORS: dict[str, str] = {
    "ds2": "C0",   # blue
    "justin": "C1",  # orange
    "a4s": "C2",    # green
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot Prometheus metric CSVs from ds2, justin, and/or a4s runs.",
    )
    parser.add_argument("--ds2", help="Path to ds2 metrics CSV.")
    parser.add_argument("--justin", help="Path to justin metrics CSV.")
    parser.add_argument("--a4s", help="Path to a4s metrics CSV.")
    parser.add_argument(
        "--output",
        default=".",
        help="Output directory for plot images (default: current directory).",
    )
    return parser.parse_args()


def load_csv(path: Path) -> dict[str, np.ndarray]:
    """Load a metrics CSV and return {canonical_name: array of floats/NaN}."""
    rows: list[dict[str, float | str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))

    result: dict[str, np.ndarray] = {}
    for name in CANONICAL_NAMES:
        values: list[float] = []
        for row in rows:
            raw = row.get(name, "")
            if raw == "" or raw is None:
                values.append(float("nan"))
            else:
                try:
                    values.append(float(raw))
                except (ValueError, TypeError):
                    values.append(float("nan"))
        result[name] = np.array(values, dtype=float)
    return result


def sanitize_filename(name: str) -> str:
    """Convert canonical metric name to a safe filename."""
    return re.sub(r"[^\w\-]", "_", name)


def main() -> None:
    args = parse_args()

    datasets: dict[str, Path] = {}
    if args.ds2:
        datasets["ds2"] = Path(args.ds2)
    if args.justin:
        datasets["justin"] = Path(args.justin)
    if args.a4s:
        datasets["a4s"] = Path(args.a4s)

    if not datasets:
        raise SystemExit("At least one of --ds2, --justin, or --a4s must be provided.")

    for label, p in datasets.items():
        if not p.exists():
            raise SystemExit(f"File not found: {p}")

    # Load all CSVs
    loaded: dict[str, dict[str, np.ndarray]] = {}
    for label, path in datasets.items():
        loaded[label] = load_csv(path)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    for canonical in CANONICAL_NAMES:
        fig, ax = plt.subplots()
        has_any = False

        for label in ("ds2", "justin", "a4s"):
            if label not in loaded:
                continue
            arr = loaded[label].get(canonical)
            if arr is None or len(arr) == 0:
                continue
            if not np.any(np.isfinite(arr)):
                continue
            has_any = True
            x = np.arange(len(arr), dtype=float) * DEFAULT_STEP_SECONDS
            color = DATASET_COLORS[label]
            ax.plot(x, arr, color=color, label=label)

        if not has_any:
            plt.close(fig)
            print(f"Skipped {canonical}: no valid data")
            continue

        ax.set_xlabel("Time (seconds)")
        ax.set_ylabel(CANONICAL_TO_READABLE.get(canonical, canonical))
        ax.legend()
        ax.set_title(CANONICAL_TO_READABLE.get(canonical, canonical))
        filename = sanitize_filename(canonical) + ".png"
        out_path = output_dir / filename
        fig.tight_layout()
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
