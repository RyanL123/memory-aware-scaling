#!/usr/bin/env python3
"""Fetch Prometheus metrics over a time range and save as CSV.

Queries the Prometheus API at localhost:30090 and writes a CSV with canonical
metric column headers.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOGGER = logging.getLogger(__name__)

PROMETHEUS_BASE_URL = "http://localhost:30090"
PROMETHEUS_QUERY_RANGE_PATH = "/api/v1/query_range"
DEFAULT_STEP_SECONDS = 5

SOURCE_THROUGHPUT_PER_SEC = "source_throughput_records_per_sec"
TOTAL_MANAGED_MEMORY_USED_BYTES = "total_managed_memory_used_bytes"
NUM_TASK_SLOTS_USED = "num_task_slots_used"
AVG_ROCKSDB_BLOCK_CACHE_HIT_RATE = "avg_rocksdb_block_cache_hit_rate"


# List of (canonical_name, promql_query) - canonical names become CSV headers
PROMETHEUS_METRICS = [
    (
        SOURCE_THROUGHPUT_PER_SEC,
        'sum(flink_taskmanager_job_task_operator_numRecordsOutPerSecond{operator_name=~"Source.*"})',
    ),
    (
        TOTAL_MANAGED_MEMORY_USED_BYTES,
        "sum(flink_taskmanager_Status_Flink_Memory_Managed_Used)",
    ),
    (
        NUM_TASK_SLOTS_USED,
        "flink_taskmanager_taskSlotsTotal - flink_taskmanager_taskSlotsAvailable",
    ),
    (
        AVG_ROCKSDB_BLOCK_CACHE_HIT_RATE,
        "avg(rate(flink_taskmanager_job_task_operator_rocksdb_block_cache_hit[1m]) / (rate(flink_taskmanager_job_task_operator_rocksdb_block_cache_hit[1m]) + rate(flink_taskmanager_job_task_operator_rocksdb_block_cache_miss[1m])))",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Prometheus metrics over a time range and save as CSV.",
    )
    parser.add_argument(
        "--start",
        required=True,
        type=float,
        help="Start timestamp (Unix epoch in seconds).",
    )
    parser.add_argument(
        "--seconds",
        required=True,
        type=int,
        help="Number of seconds after start (end = start + seconds).",
    )
    parser.add_argument(
        "--output",
        help="Output CSV path (default: metrics_<start>_<end>.csv in current directory).",
    )
    return parser.parse_args()


def fetch_query_range(
    base_url: str,
    query: str,
    start: str,
    end: str,
    step_sec: int,
) -> list[tuple[float, str]]:
    """Query Prometheus query_range API and return [(timestamp, value), ...]."""
    url = (
        f"{base_url.rstrip('/')}{PROMETHEUS_QUERY_RANGE_PATH}"
        f"?query={urllib.parse.quote(query)}"
        f"&start={urllib.parse.quote(str(start))}"
        f"&end={urllib.parse.quote(str(end))}"
        f"&step={step_sec}s"
    )
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Prometheus request failed: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from Prometheus: {e}") from e

    if data.get("status") == "error":
        raise RuntimeError(
            f"Prometheus query error: {data.get('error', 'unknown')}"
        )

    result_data = data.get("data", {})
    results = result_data.get("result", [])
    values: list[tuple[float, str]] = []

    for series in results:
        for ts_str, val_str in series.get("values", []):
            ts = float(ts_str)
            val = str(val_str)
            values.append((ts, val))

    # Sort by timestamp and dedupe by keeping last value per timestamp
    if values:
        values.sort(key=lambda x: x[0])
        seen: dict[float, str] = {}
        for ts, val in values:
            seen[ts] = val
        values = sorted(seen.items())

    return values


def write_csv(
    path: Path,
    all_data: dict[float, dict[str, str | float]],
    canonical_names: list[str],
) -> None:
    """Write merged metric data to CSV with headers matching canonical names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["timestamp_epoch"] + canonical_names
    sorted_timestamps = sorted(all_data.keys())

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for ts in sorted_timestamps:
            row = all_data[ts].copy()
            row["timestamp_epoch"] = int(ts) if ts == int(ts) else ts
            writer.writerow(row)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = parse_args()
    end = args.start + args.seconds

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        start_safe = str(args.start).replace(":", "-").replace(".", "_")
        end_safe = str(end).replace(":", "-").replace(".", "_")
        output_path = Path.cwd() / f"metrics_{start_safe}_{end_safe}.csv"

    all_data: dict[float, dict[str, str | float]] = {}
    canonical_names = [name for name, _ in PROMETHEUS_METRICS]

    for name, query in PROMETHEUS_METRICS:
        LOGGER.info("Fetching metric: %s", name)
        values = fetch_query_range(
            PROMETHEUS_BASE_URL,
            query,
            str(args.start),
            str(end),
            DEFAULT_STEP_SECONDS,
        )
        for ts, val in values:
            row = all_data.setdefault(ts, {"timestamp_epoch": ts})
            row[name] = val

    if not all_data:
        LOGGER.warning("No data retrieved from Prometheus")
        # Write empty CSV with headers
        write_csv(output_path, {}, canonical_names)
    else:
        write_csv(output_path, all_data, canonical_names)
        LOGGER.info("Saved %d rows to %s", len(all_data), output_path)


if __name__ == "__main__":
    main()
