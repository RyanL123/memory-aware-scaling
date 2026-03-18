#!/usr/bin/env python3
"""Periodically sample Flink metrics from the REST API via kubectl.

This script does not create or delete deployments. It can run independently
while an existing experiment is running.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
import subprocess
import time
import urllib.parse
from pathlib import Path


LOGGER = logging.getLogger(__name__)
REST_PROXY_BASE_PATH = "/api/v1/namespaces/default/services/http:flink-rest:8081/proxy"
WAIT_RUNNING_TIMEOUT_SEC = 600


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample canonical Flink metrics from a running job via kubectl."
    )
    parser.add_argument(
        "--duration-sec",
        type=int,
        default=600,
        help="Total sampling duration in seconds (default: 600).",
    )
    parser.add_argument(
        "--sampling-interval-sec",
        type=int,
        default=5,
        help="Sampling interval in seconds (default: 5).",
    )
    parser.add_argument(
        "--output-csv",
        required=True,
        help="Output path for samples CSV.",
    )
    parser.add_argument(
        "--workspace-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Path to workspace root used as kubectl command cwd.",
    )
    return parser.parse_args()


def shell(command: str, cwd: Path, check: bool = True) -> tuple[str, int]:
    proc = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {command}\n{proc.stdout}")
    return proc.stdout.strip(), proc.returncode


def get_json_via_kubectl_raw(workspace_root: Path, path: str, retries: int = 4) -> dict:
    raw_path = f"{REST_PROXY_BASE_PATH}{path}"
    last_output = ""
    for i in range(retries):
        proc = subprocess.run(
            f"kubectl get --raw '{raw_path}'",
            shell=True,
            cwd=workspace_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode == 0:
            return json.loads(proc.stdout)
        last_output = (proc.stderr or proc.stdout).strip()
        time.sleep(1 + i)
    raise RuntimeError(f"kubectl get --raw failed for {path}: {last_output}")


def wait_job_running(workspace_root: Path) -> str:
    start = time.time()
    while time.time() - start < WAIT_RUNNING_TIMEOUT_SEC:
        state, _ = shell(
            "kubectl get flinkdeployment flink -o jsonpath='{.status.jobStatus.state}'",
            workspace_root,
            check=False,
        )
        job_id, _ = shell(
            "kubectl get flinkdeployment flink -o jsonpath='{.status.jobStatus.jobId}'",
            workspace_root,
            check=False,
        )
        if state == "RUNNING" and job_id:
            return job_id
        time.sleep(3)
    raise TimeoutError("Timed out waiting for RUNNING job.")


def wait_rest_ready(workspace_root: Path, timeout_sec: int = 180) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            overview = get_json_via_kubectl_raw(workspace_root, "/overview", retries=1)
            if "flink-version" in overview:
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError("Timed out waiting for Flink REST readiness.")


def get_source_vertex_ids(workspace_root: Path, job_id: str) -> tuple[list[str], dict[str, str]]:
    job = get_json_via_kubectl_raw(workspace_root, f"/jobs/{job_id}")
    vertices = job.get("vertices", [])
    source_vertices = [v for v in vertices if "Source:" in v.get("name", "")]
    if not source_vertices:
        source_vertices = [v for v in vertices if "source" in v.get("name", "").lower()]

    source_ids = [v["id"] for v in source_vertices]
    source_names = {v["id"]: v.get("name", "<unknown>") for v in source_vertices}

    LOGGER.info("Detected source vertices:")
    for v in source_vertices:
        LOGGER.info(
            "  - id=%s name=%s parallelism=%s",
            v.get("id"),
            v.get("name", "<unknown>"),
            v.get("parallelism", "<unknown>"),
        )
    if not source_vertices:
        LOGGER.info("  - none detected")

    return source_ids, source_names


def sample_once(
    workspace_root: Path,
    job_id: str,
    source_vids: list[str],
    source_names: dict[str, str],
) -> tuple[int, float, float, float, float]:
    ts = int(time.time())
    overview = get_json_via_kubectl_raw(workspace_root, "/overview")
    slots_used = float(int(overview.get("slots-total", 0)) - int(overview.get("slots-available", 0)))

    mem_used = 0.0
    mem_total = 0.0
    for tm in get_json_via_kubectl_raw(workspace_root, "/taskmanagers").get("taskmanagers", []):
        tm_id = tm["id"]
        vals = get_json_via_kubectl_raw(
            workspace_root,
            f"/taskmanagers/{tm_id}/metrics?get=Status.Flink.Memory.Managed.Used",
            retries=2,
        )
        if vals:
            try:
                mem_used += float(vals[0]["value"])
            except Exception:
                pass
        vals = get_json_via_kubectl_raw(
            workspace_root,
            f"/taskmanagers/{tm_id}/metrics?get=Status.Flink.Memory.Managed.Total",
            retries=2,
        )
        if vals:
            try:
                mem_total += float(vals[0]["value"])
            except Exception:
                pass

    throughput = 0.0
    for vid in source_vids:
        source_name = source_names.get(vid, "<unknown>")
        metrics = get_json_via_kubectl_raw(workspace_root, f"/jobs/{job_id}/vertices/{vid}/metrics", retries=2)
        metric_ids = sorted(
            {
                m["id"]
                for m in metrics
                if re.fullmatch(r"\d+\.numRecordsOutPerSecond", m.get("id", ""))
            },
            key=lambda mid: int(mid.split(".", 1)[0]),
        )
        if not metric_ids:
            LOGGER.info(
                "[metrics] ts=%s source=%s (%s) numRecordsOutPerSecond metrics=none",
                ts,
                source_name,
                vid,
            )
            continue
        LOGGER.info(
            "[metrics] ts=%s source=%s (%s) numRecordsOutPerSecond metric_ids=%s",
            ts,
            source_name,
            vid,
            ",".join(metric_ids),
        )
        encoded = urllib.parse.quote(",".join(metric_ids), safe=",")
        vals = get_json_via_kubectl_raw(
            workspace_root,
            f"/jobs/{job_id}/vertices/{vid}/metrics?get={encoded}",
            retries=2,
        )
        for item in vals:
            try:
                metric_value = float(item["value"])
                throughput += metric_value
                LOGGER.info(
                    "[metrics] ts=%s source=%s (%s) metric=%s value=%s",
                    ts,
                    source_name,
                    vid,
                    item.get("id", "<unknown>"),
                    metric_value,
                )
            except Exception:
                pass

    LOGGER.info(
        "[metrics] ts=%s totals source_throughput_records_per_sec=%s "
        "total_managed_memory_used_bytes=%s total_managed_memory_total_bytes=%s total_slots_used=%s",
        ts,
        throughput,
        mem_used,
        mem_total,
        slots_used,
    )
    return ts, throughput, mem_used, mem_total, slots_used


def write_samples_csv(path: Path, rows: list[tuple[int, float, float, float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp_epoch",
                "source_throughput_records_per_sec",
                "total_managed_memory_used_bytes",
                "total_managed_memory_total_bytes",
                "total_slots_used",
            ]
        )
        writer.writerows(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if args.duration_sec <= 0:
        raise ValueError("--duration-sec must be > 0")
    if args.sampling_interval_sec <= 0:
        raise ValueError("--sampling-interval-sec must be > 0")

    workspace_root = Path(args.workspace_root).resolve()
    output_csv = Path(args.output_csv).resolve()
    sample_count = max(1, math.ceil(args.duration_sec / args.sampling_interval_sec))

    LOGGER.info("Waiting for running flinkdeployment/flink job.")
    job_id = wait_job_running(workspace_root)
    LOGGER.info("Sampling job_id: %s", job_id)
    LOGGER.info("Output CSV: %s", output_csv)
    LOGGER.info("Sampling: %s samples at %ss interval", sample_count, args.sampling_interval_sec)

    wait_rest_ready(workspace_root)
    vids, source_names = get_source_vertex_ids(workspace_root, job_id)

    rows: list[tuple[int, float, float, float, float]] = []
    for i in range(sample_count):
        t0 = time.time()
        rows.append(sample_once(workspace_root, job_id, vids, source_names))
        if i % max(1, math.ceil(60 / args.sampling_interval_sec)) == 0:
            LOGGER.info("Progress: sample %s/%s", i + 1, sample_count)
        elapsed = time.time() - t0
        time.sleep(max(0.0, args.sampling_interval_sec - elapsed))

    write_samples_csv(output_csv, rows)
    LOGGER.info("Saved samples: %s", output_csv)


if __name__ == "__main__":
    main()
