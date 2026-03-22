#!/usr/bin/env python3
"""Plot benchmark run metrics from results.

Usage examples:
  python scripts/experiements/plot_run.py --query q8 --run-id 1771965764000
  python scripts/experiements/plot_run.py --query q8 --latest
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator


LOGGER = logging.getLogger(__name__)
MEMORY_USED_COLUMN = "total_managed_memory_used_bytes"
MEMORY_TOTAL_COLUMN = "total_managed_memory_total_bytes"


def parse_args() -> argparse.Namespace:
    workspace_root_default = Path(__file__).resolve().parents[2]
    results_root_default = workspace_root_default / "results"

    parser = argparse.ArgumentParser(
        description=(
            "Plot one benchmark run as a single image with all available time-series "
            "metrics in stacked subplots."
        )
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Query directory name under nexmark (example: q8).",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--run-id",
        help="Run id from runs.csv (example: 1771965764000).",
    )
    group.add_argument(
        "--latest",
        action="store_true",
        help="Use the last row in runs.csv for the selected query.",
    )
    parser.add_argument(
        "--results-root",
        default=str(results_root_default),
        help="Path to results root (default: <workspace-root>/results).",
    )
    parser.add_argument(
        "--output",
        help="Output image path (default: <query_dir>/<run_id>_<environment>_<autoscaler>/plot.png).",
    )
    return parser.parse_args()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV file: {path}")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
    return rows


def select_run_row(rows: list[dict[str, str]], run_id: str | None, latest: bool) -> dict[str, str]:
    if not rows:
        raise ValueError("runs.csv has no data rows.")

    if run_id:
        for row in rows:
            if row.get("run_id") == run_id:
                return row
        raise ValueError(f"run_id '{run_id}' not found in runs.csv.")

    if latest or not run_id:
        return rows[-1]

    raise ValueError("Could not resolve run selection.")


def run_name_from_row(run_row: dict[str, str]) -> str:
    run_id = run_row.get("run_id", "").strip()
    environment = run_row.get("environment", "").strip()
    autoscaler = run_row.get("autoscaler", "").strip()
    storage = run_row.get("storage", "").strip()
    if not run_id or not environment or not autoscaler:
        raise ValueError("Selected runs.csv row is missing run_id/environment/autoscaler.")
    if storage:
        return f"{run_id}_{environment}_{autoscaler}_{storage}"
    return f"{run_id}_{environment}_{autoscaler}"


def detect_timestamp_column(columns: list[str]) -> str:
    priority = ["timestamp_epoch", "timestamp", "time", "t"]
    for name in priority:
        if name in columns:
            return name

    for column in columns:
        if "time" in column.lower():
            return column

    raise ValueError("Could not detect timestamp column in samples CSV.")


def to_float(value: str, column: str, index: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Non-numeric value in samples CSV at row {index + 1}, column '{column}': {value!r}"
        ) from exc


def configure_plot_style() -> None:
    plt.style.use("default")
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#B0B0B0",
            "axes.grid": True,
            "grid.color": "#E6E6E6",
            "grid.linestyle": "-",
            "grid.linewidth": 0.7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.labelsize": 10,
            "axes.titlesize": 12,
            "legend.frameon": False,
            "lines.linewidth": 1.8,
        }
    )


def pretty_metric_label(column: str) -> str:
    label = column.replace("_", " ").strip()
    label = " ".join(word.capitalize() for word in label.split())
    return label


def convert_units(column: str, values: list[float]) -> tuple[list[float], str]:
    lower = column.lower()
    if "bytes" in lower:
        return [v / (1024.0 * 1024.0) for v in values], "MiB"
    if "per_sec" in lower or "per_second" in lower:
        return values, "/s"
    return values, ""


def infer_axis_limits(metric_name: str, values: list[float]) -> tuple[float, float]:
    """Return per-run axis limits with light padding for readability."""
    if not values:
        return 0.0, 1.0

    lower_name = metric_name.lower()
    min_v = min(values)
    max_v = max(values)

    if math.isclose(min_v, max_v):
        if math.isclose(max_v, 0.0):
            return 0.0, 1.0
        pad = abs(max_v) * 0.10
        return min_v - pad, max_v + pad

    span = max_v - min_v
    pad = span * 0.08

    if "slot" in lower_name and "used" in lower_name:
        # Keep integer-friendly slot ticks, but avoid forcing a zero baseline
        # so small changes around high slot counts are still visible.
        slot_pad = max(0.5, pad)
        lower = max(0.0, math.floor(min_v - slot_pad))
        upper = math.ceil(max_v + slot_pad)
        return lower, max(lower + 1.0, upper)

    return min_v - pad, max_v + pad


def build_series(samples: list[dict[str, str]]) -> tuple[list[float], dict[str, list[float]]]:
    if not samples:
        raise ValueError("Sample CSV is empty.")

    columns = list(samples[0].keys())
    timestamp_column = detect_timestamp_column(columns)
    metric_columns = [c for c in columns if c != timestamp_column]
    if not metric_columns:
        raise ValueError("No metric columns found in samples CSV.")

    timestamps = [to_float(row[timestamp_column], timestamp_column, i) for i, row in enumerate(samples)]
    t0 = timestamps[0]
    elapsed_seconds = [ts - t0 for ts in timestamps]

    series: dict[str, list[float]] = {}
    for column in metric_columns:
        series[column] = [to_float(row[column], column, i) for i, row in enumerate(samples)]

    return elapsed_seconds, series


def build_metric_panels(series: dict[str, list[float]]) -> list[tuple[str, list[str]]]:
    """Build plot panels as (primary_metric, overlay_metrics)."""
    panels: list[tuple[str, list[str]]] = []
    for metric_name in series.keys():
        if metric_name == MEMORY_TOTAL_COLUMN and MEMORY_USED_COLUMN in series:
            # Overlay managed total on the existing managed used panel.
            continue
        overlays: list[str] = []
        if metric_name == MEMORY_USED_COLUMN and MEMORY_TOTAL_COLUMN in series:
            overlays.append(MEMORY_TOTAL_COLUMN)
        panels.append((metric_name, overlays))
    return panels


def plot_run(
    query: str,
    run_row: dict[str, str],
    elapsed_seconds: list[float],
    series: dict[str, list[float]],
    output_path: Path,
) -> None:
    configure_plot_style()

    metric_panels = build_metric_panels(series)
    figure, axes = plt.subplots(
        nrows=len(metric_panels),
        ncols=1,
        figsize=(12, max(3.8 * len(metric_panels), 6.0)),
        sharex=True,
        constrained_layout=False,
    )
    if len(metric_panels) == 1:
        axes = [axes]

    colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]

    for i, (ax, (metric_name, overlay_metrics)) in enumerate(zip(axes, metric_panels)):
        raw_values = series[metric_name]
        values, unit = convert_units(metric_name, raw_values)
        label = pretty_metric_label(metric_name)
        if unit:
            label = f"{label} ({unit})"

        ax.plot(
            elapsed_seconds,
            values,
            color=colors[i % len(colors)],
            marker="o",
            markersize=3.5,
            label=pretty_metric_label(metric_name),
        )
        all_values = list(values)
        for offset, overlay_metric in enumerate(overlay_metrics, start=1):
            overlay_values, _ = convert_units(overlay_metric, series[overlay_metric])
            all_values.extend(overlay_values)
            ax.plot(
                elapsed_seconds,
                overlay_values,
                color=colors[(i + offset) % len(colors)],
                marker="o",
                markersize=3.5,
                linestyle="--",
                label=pretty_metric_label(overlay_metric),
            )

        ax.set_ylabel(label)
        ymin, ymax = infer_axis_limits(metric_name, all_values)
        ax.set_ylim(ymin, ymax)

        if overlay_metrics:
            ax.legend(loc="best")

        if "slot" in metric_name.lower() and "used" in metric_name.lower():
            ax.yaxis.set_major_locator(MultipleLocator(1.0))

    axes[-1].set_xlabel("Elapsed time (s)")

    run_id = run_row.get("run_id", "unknown-run")
    autoscaler = run_row.get("autoscaler", "unknown")
    run_commit = run_row.get("run_commit", "not-captured")
    sample_count = str(len(elapsed_seconds))
    title = f"{query.upper()} - {run_id}"
    subtitle = f"Autoscaler: {autoscaler} | Commit: {run_commit} | Samples: {sample_count}"
    figure.suptitle(f"{title}\n{subtitle}", y=0.97)
    figure.subplots_adjust(top=0.84, hspace=0.35)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    results_root = Path(args.results_root).resolve()
    query_dir = results_root / "nexmark" / args.query
    runs_csv = query_dir / "runs.csv"

    run_rows = read_csv_rows(runs_csv)
    run_row = select_run_row(run_rows, args.run_id, args.latest)
    run_id = run_row.get("run_id")
    if not run_id:
        raise ValueError("Selected runs.csv row has no run_id.")

    run_name = run_name_from_row(run_row)
    run_dir = query_dir / run_name
    samples_path = run_dir / "samples.csv"
    if not samples_path.exists():
        for suffix in ("_ssd", "_hdd"):
            alt_dir = query_dir / f"{run_name}{suffix}"
            alt_samples = alt_dir / "samples.csv"
            if alt_samples.exists():
                run_dir = alt_dir
                samples_path = alt_samples
                break
    if not samples_path.exists():
        raise FileNotFoundError(f"Missing samples CSV for run: {samples_path}")
    samples = read_csv_rows(samples_path)
    elapsed_seconds, series = build_series(samples)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = run_dir / "plot.png"

    plot_run(args.query, run_row, elapsed_seconds, series, output_path)
    LOGGER.info("Saved plot: %s", output_path)


if __name__ == "__main__":
    main()
