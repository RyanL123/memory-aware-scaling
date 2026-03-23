#!/usr/bin/env python3
"""Run one Nexmark query experiment and persist comparable results.

This script:
1) applies a FlinkDeployment manifest
2) waits for the run duration
3) deletes the deployment
4) fetches Prometheus metrics via data_retriever.py and saves as samples.csv
5) appends a normalized summary row to runs.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

WORKSPACE_ROOT_DEFAULT = Path(__file__).resolve().parents[2]
RESULTS_ROOT_DEFAULT = WORKSPACE_ROOT_DEFAULT / "results"


RUNS_HEADER = ["run_id", "environment", "run_commit", "autoscaler", "storage", "run_time_est"]
LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one Nexmark query benchmark and save samples and summary."
    )
    parser.add_argument("--query", required=True, help="Query directory name, e.g. q1, q2, q11.")
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to FlinkDeployment YAML.",
    )
    parser.add_argument(
        "--duration-sec",
        type=int,
        default=1800,
        help="Run duration in seconds (default: 1800).",
    )
    parser.add_argument(
        "--environment",
        default="k8s",
        help="Environment tag used in run_id and runs.csv (default: k8s).",
    )
    parser.add_argument(
        "--policy",
        required=True,
        choices=["ds2", "justin", "a4s"],
        help="Autoscaling policy and manifest suffix.",
    )
    parser.add_argument(
        "--storage",
        choices=["ssd", "hdd"],
        default="ssd",
        help="Storage type (default: ssd).",
    )
    parser.add_argument(
        "--cleanup-timeout-sec",
        type=int,
        default=240,
        help="Timeout waiting for FlinkDeployment deletion (default: 240).",
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


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower() or "run"


def wait_no_deployment(workspace_root: Path, timeout_sec: int) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        out, code = shell("kubectl get flinkdeployment flink -o name", workspace_root, check=False)
        if code != 0 or "NotFound" in out or out == "":
            return
        time.sleep(2)
    raise TimeoutError("Timed out waiting for flinkdeployment cleanup.")


def run_data_retriever(
    workspace_root: Path,
    samples_csv: Path,
    start_unix_sec: float,
    duration_sec: int,
) -> None:
    """Fetch Prometheus metrics for the run time range and save as CSV."""
    scripts_dir = Path(__file__).resolve().parents[1]
    data_retriever_script = scripts_dir / "prometheus" / "data_retriever.py"
    if not data_retriever_script.exists():
        raise FileNotFoundError(f"data_retriever script not found: {data_retriever_script}")
    command = [
        sys.executable,
        str(data_retriever_script),
        "--start",
        str(start_unix_sec),
        "--seconds",
        str(duration_sec),
        "--output",
        str(samples_csv),
    ]
    proc = subprocess.run(
        command,
        cwd=workspace_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout:
        LOGGER.info("data_retriever output:\n%s", proc.stdout.strip())
    if proc.returncode != 0:
        raise RuntimeError("data_retriever.py failed")


def start_a4s_decision_collector(
    workspace_root: Path,
    run_dir: Path,
    since_time: datetime.datetime,
) -> tuple[Path, subprocess.Popen[str] | None, threading.Thread | None]:
    """Stream operator logs and persist A4S decision lines since run start."""
    decisions_log = run_dir / "a4s_decisions.log"
    decisions_log.write_text("", encoding="utf-8")

    since_rfc3339 = since_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    cmd = [
        "kubectl",
        "logs",
        "deployment/flink-kubernetes-operator",
        "--all-containers",
        "--since-time",
        since_rfc3339,
        "-f",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=workspace_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("Unable to start A4S decision collector: %s", exc)
        decisions_log.write_text(
            "Failed to start live operator log collection.\n",
            encoding="utf-8",
        )
        return decisions_log, None, None

    def _consume() -> None:
        assert proc.stdout is not None
        with decisions_log.open("a", encoding="utf-8") as handle:
            for line in proc.stdout:
                if "A4S:" in line:
                    handle.write(line)
                    handle.flush()

    thread = threading.Thread(target=_consume, name="a4s-decision-collector", daemon=True)
    thread.start()
    return decisions_log, proc, thread


def stop_a4s_decision_collector(
    proc: subprocess.Popen[str] | None,
    thread: threading.Thread | None,
) -> None:
    """Stop the background A4S decision collector."""
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    if thread is not None:
        thread.join(timeout=5)


def _run_time_est_from_run_id(run_id: str) -> str:
    """Convert run_id (epoch ms) to Eastern Time string for tracking."""
    try:
        ts_ms = int(run_id)
        utc = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)
        try:
            from zoneinfo import ZoneInfo

            et = utc.astimezone(ZoneInfo("America/New_York"))
        except ImportError:
            et = utc.astimezone(datetime.timezone(datetime.timedelta(hours=-5)))
        return et.strftime("%Y-%m-%d %H:%M:%S %Z")
    except (ValueError, OSError):
        return ""


def append_run_row(runs_csv: Path, row: dict[str, str]) -> None:
    exists = runs_csv.exists()
    existing_rows: list[dict[str, str]] = []
    if exists:
        with runs_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = list(reader.fieldnames or [])
            if header == RUNS_HEADER:
                existing_rows = list(reader)
            elif header + ["run_time_est"] == RUNS_HEADER:
                for r in reader:
                    r["run_time_est"] = ""
                    existing_rows.append(r)
                with runs_csv.open("w", encoding="utf-8", newline="") as wh:
                    writer = csv.DictWriter(wh, fieldnames=RUNS_HEADER, extrasaction="ignore")
                    writer.writeheader()
                    for r in existing_rows:
                        writer.writerow({k: r.get(k, "") for k in RUNS_HEADER})
            else:
                raise ValueError(
                    f"Unsupported runs.csv header in {runs_csv}. "
                    f"Expected header: {','.join(RUNS_HEADER)}."
                )
        if any(r.get("run_id") == row["run_id"] for r in existing_rows):
            return
        with runs_csv.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RUNS_HEADER, extrasaction="ignore")
            writer.writerow(row)
        return

    with runs_csv.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUNS_HEADER, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)


def build_run_row(
    args: argparse.Namespace,
    run_id: str,
    run_commit: str,
) -> dict[str, str]:
    return {
        "run_id": run_id,
        "environment": args.environment,
        "run_commit": run_commit,
        "autoscaler": slugify(args.policy),
        "storage": slugify(args.storage),
        "run_time_est": _run_time_est_from_run_id(run_id),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if args.duration_sec <= 0:
        raise ValueError("--duration-sec must be > 0")

    workspace_root = WORKSPACE_ROOT_DEFAULT.resolve()
    if not workspace_root.exists():
        raise FileNotFoundError(f"Workspace root does not exist: {workspace_root}")
    flink_root = workspace_root / "flink-justin"
    if not flink_root.exists():
        raise FileNotFoundError(f"Expected flink root missing: {flink_root}")
    results_root = RESULTS_ROOT_DEFAULT.resolve()
    query = slugify(args.query)
    policy = slugify(args.policy)
    manifest = Path(args.manifest).resolve()
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest}")

    run_id = str(int(time.time() * 1000))
    autoscaler = policy
    run_name = f"{run_id}_{slugify(args.environment)}_{slugify(autoscaler)}_{slugify(args.storage)}"
    query_dir = results_root / "nexmark" / query
    query_dir.mkdir(parents=True, exist_ok=True)
    runs_csv = query_dir / "runs.csv"
    run_dir = query_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    samples_csv = run_dir / "samples.csv"

    manifest_copy = run_dir / manifest.name
    shutil.copy2(manifest, manifest_copy)
    LOGGER.info("Copied manifest to: %s", manifest_copy)

    LOGGER.info("Starting run_id: %s", run_id)
    LOGGER.info("Run folder: %s", run_dir)
    LOGGER.info("Manifest: %s", manifest)
    LOGGER.info("Run duration: %ss", args.duration_sec)

    shell("kubectl delete flinkdeployment flink --ignore-not-found=true", workspace_root, check=False)
    wait_no_deployment(workspace_root, args.cleanup_timeout_sec)

    run_start_time = datetime.datetime.now(datetime.timezone.utc)
    decisions_log, collector_proc, collector_thread = start_a4s_decision_collector(
        workspace_root=workspace_root,
        run_dir=run_dir,
        since_time=run_start_time,
    )
    LOGGER.info("Streaming A4S decisions to: %s (since %s)", decisions_log, run_start_time.isoformat())

    interrupted = False
    run_start_unix_sec = time.time()
    try:
        try:
            shell(f"kubectl apply -f '{manifest}'", workspace_root)
            LOGGER.info("Waiting %ss for run...", args.duration_sec)
            time.sleep(args.duration_sec)
        finally:
            shell(f"kubectl delete -f '{manifest}'", workspace_root, check=False)
            wait_no_deployment(workspace_root, args.cleanup_timeout_sec)
            stop_a4s_decision_collector(collector_proc, collector_thread)

        run_data_retriever(
            workspace_root=workspace_root,
            samples_csv=samples_csv,
            start_unix_sec=run_start_unix_sec,
            duration_sec=args.duration_sec,
        )

        if not samples_csv.exists():
            raise FileNotFoundError(f"data_retriever did not create expected samples CSV: {samples_csv}")

        commit_out, commit_rc = shell("git rev-parse --short HEAD", workspace_root, check=False)
        run_commit = commit_out if commit_rc == 0 and commit_out else "not-captured"
        run_row = build_run_row(args, run_id, run_commit)
        append_run_row(runs_csv, run_row)
    except KeyboardInterrupt:
        interrupted = True
        LOGGER.info("Interrupted by user")
        if samples_csv.exists():
            commit_out, commit_rc = shell("git rev-parse --short HEAD", workspace_root, check=False)
            run_commit = commit_out if commit_rc == 0 and commit_out else "not-captured"
            run_row = build_run_row(args, run_id, run_commit)
            append_run_row(runs_csv, run_row)
            LOGGER.info("Saved partial run to %s", runs_csv)

    if decisions_log.read_text(encoding="utf-8").strip() == "":
        decisions_log.write_text(
            "No A4S [Decision]: lines captured during the run.\n",
            encoding="utf-8",
        )
    LOGGER.info("Saved A4S decisions: %s", decisions_log)

    if samples_csv.exists():
        LOGGER.info("Saved samples: %s", samples_csv)
    if runs_csv.exists():
        LOGGER.info("Updated runs: %s", runs_csv)
    LOGGER.info("Run complete." if not interrupted else "Run interrupted.")


if __name__ == "__main__":
    main()
