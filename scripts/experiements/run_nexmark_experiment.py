#!/usr/bin/env python3
"""Run one Nexmark query experiment and persist comparable results.

This script:
1) applies a FlinkDeployment manifest
2) invokes sampler.py to collect samples (throughput, slots, managed memory used/total)
3) deletes the deployment
4) appends a normalized summary row to runs.csv
5) optionally generates a plot via plot_run.py
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import subprocess
import sys
import threading
import time
from pathlib import Path


RUNS_HEADER = ["run_id", "environment", "run_commit", "autoscaler"]
LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    workspace_root_default = Path(__file__).resolve().parents[2]
    results_root_default = workspace_root_default / "results"

    parser = argparse.ArgumentParser(
        description="Run one Nexmark query benchmark and save samples, summary, and plot."
    )
    parser.add_argument("--query", required=True, help="Query directory name, e.g. q1, q2, q11.")
    parser.add_argument(
        "--manifest",
        help=(
            "Path to FlinkDeployment YAML "
            "(default: flink-justin/notebooks/nexmark/<query>/query<num>.<policy>.yaml)."
        ),
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
        "--environment",
        default="kind",
        help="Environment tag used in run_id and runs.csv (default: kind).",
    )
    parser.add_argument(
        "--policy",
        choices=["ds2", "justin", "a4s"],
        default="ds2",
        help="Autoscaling policy and manifest suffix (default: ds2).",
    )
    parser.add_argument(
        "--results-root",
        default=str(results_root_default),
        help="Path to results root (default: <workspace-root>/results).",
    )
    parser.add_argument(
        "--workspace-root",
        default=str(workspace_root_default),
        help=(
            "Path to workspace root containing flink-justin/ and results/ "
            "(default: repository root)."
        ),
    )
    parser.add_argument(
        "--cleanup-timeout-sec",
        type=int,
        default=240,
        help="Timeout waiting for FlinkDeployment deletion (default: 240).",
    )
    parser.add_argument(
        "--plot",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate plot after run (default: true).",
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


def default_manifest_for_query(workspace_root: Path, query: str, policy: str) -> Path:
    match = re.fullmatch(r"q(\d+)", query)
    if not match:
        raise ValueError(f"Cannot infer manifest for query '{query}'. Provide --manifest.")
    qnum = match.group(1)
    return workspace_root / f"flink-justin/notebooks/nexmark/{query}/query{qnum}.{policy}.yaml"


def wait_no_deployment(workspace_root: Path, timeout_sec: int) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        out, code = shell("kubectl get flinkdeployment flink -o name", workspace_root, check=False)
        if code != 0 or "NotFound" in out or out == "":
            return
        time.sleep(2)
    raise TimeoutError("Timed out waiting for flinkdeployment cleanup.")


def run_sampler(
    workspace_root: Path,
    samples_csv: Path,
    duration_sec: int,
    sampling_interval_sec: int,
) -> None:
    scripts_dir = Path(__file__).resolve().parent
    sampler_script = scripts_dir / "sampler.py"
    if not sampler_script.exists():
        raise FileNotFoundError(f"Sampler script not found: {sampler_script}")
    command = [
        sys.executable,
        str(sampler_script),
        "--duration-sec",
        str(duration_sec),
        "--sampling-interval-sec",
        str(sampling_interval_sec),
        "--output-csv",
        str(samples_csv),
        "--workspace-root",
        str(workspace_root),
    ]
    proc = subprocess.run(
        command,
        cwd=workspace_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout:
        LOGGER.info("sampler output:\n%s", proc.stdout.strip())
    if proc.returncode != 0:
        raise RuntimeError("sampler.py failed")


def start_a4s_decision_collector(
    workspace_root: Path,
    run_dir: Path,
) -> tuple[Path, subprocess.Popen[str] | None, threading.Thread | None]:
    """Stream operator logs and persist A4S decision lines while the run is active."""
    decisions_log = run_dir / "a4s_decisions.log"
    decisions_log.write_text("", encoding="utf-8")

    cmd = [
        "kubectl",
        "logs",
        "deployment/flink-kubernetes-operator",
        "--all-containers",
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


def append_run_row(runs_csv: Path, row: dict[str, str]) -> None:
    exists = runs_csv.exists()
    existing_rows: list[dict[str, str]] = []
    if exists:
        with runs_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != RUNS_HEADER:
                raise ValueError(
                    f"Unsupported runs.csv header in {runs_csv}. "
                    "Expected header: run_id,environment,run_commit,autoscaler."
                )
            existing_rows = list(reader)
        if any(r.get("run_id") == row["run_id"] for r in existing_rows):
            return

    with runs_csv.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUNS_HEADER)
        if not exists:
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
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if args.duration_sec <= 0:
        raise ValueError("--duration-sec must be > 0")
    if args.sampling_interval_sec <= 0:
        raise ValueError("--sampling-interval-sec must be > 0")

    workspace_root = Path(args.workspace_root).resolve()
    if not workspace_root.exists():
        raise FileNotFoundError(f"Workspace root does not exist: {workspace_root}")
    flink_root = workspace_root / "flink-justin"
    if not flink_root.exists():
        raise FileNotFoundError(f"Expected flink root missing: {flink_root}")
    results_root = Path(args.results_root).resolve()
    query = slugify(args.query)
    policy = slugify(args.policy)
    manifest = (
        Path(args.manifest).resolve()
        if args.manifest
        else default_manifest_for_query(workspace_root, query, policy)
    )
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest}")

    run_id = str(int(time.time() * 1000))
    autoscaler = policy
    run_name = f"{run_id}_{slugify(args.environment)}_{slugify(autoscaler)}"
    query_dir = results_root / "nexmark" / query
    query_dir.mkdir(parents=True, exist_ok=True)
    runs_csv = query_dir / "runs.csv"
    run_dir = query_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    samples_csv = run_dir / "samples.csv"

    LOGGER.info("Starting run_id: %s", run_id)
    LOGGER.info("Run folder: %s", run_dir)
    LOGGER.info("Manifest: %s", manifest)
    LOGGER.info(
        "Sampling duration: %ss at %ss interval",
        args.duration_sec,
        args.sampling_interval_sec,
    )

    shell("kubectl delete flinkdeployment flink --ignore-not-found=true", workspace_root, check=False)
    wait_no_deployment(workspace_root, args.cleanup_timeout_sec)

    decisions_log, collector_proc, collector_thread = start_a4s_decision_collector(
        workspace_root=workspace_root,
        run_dir=run_dir,
    )
    LOGGER.info("Streaming A4S decisions to: %s", decisions_log)

    try:
        shell(f"kubectl apply -f '{manifest}'", workspace_root)
        run_sampler(
            workspace_root=workspace_root,
            samples_csv=samples_csv,
            duration_sec=args.duration_sec,
            sampling_interval_sec=args.sampling_interval_sec,
        )
    finally:
        shell(f"kubectl delete -f '{manifest}'", workspace_root, check=False)
        wait_no_deployment(workspace_root, args.cleanup_timeout_sec)
        stop_a4s_decision_collector(collector_proc, collector_thread)

    if not samples_csv.exists():
        raise FileNotFoundError(f"Sampler did not create expected samples CSV: {samples_csv}")

    commit_out, commit_rc = shell("git rev-parse --short HEAD", workspace_root, check=False)
    run_commit = commit_out if commit_rc == 0 and commit_out else "not-captured"
    run_row = build_run_row(args, run_id, run_commit)
    append_run_row(runs_csv, run_row)

    if args.plot:
        plot_cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "plot_run.py"),
            "--query",
            query,
            "--run-id",
            run_id,
            "--results-root",
            str(results_root),
        ]
        proc = subprocess.run(plot_cmd, cwd=workspace_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            LOGGER.error("Plot generation failed:")
            LOGGER.error("%s", proc.stdout)
            raise RuntimeError("plot_run.py failed")
        LOGGER.info("%s", proc.stdout.strip())

    if decisions_log.read_text(encoding="utf-8").strip() == "":
        decisions_log.write_text(
            "No A4S [Decision]: lines captured during the run.\n",
            encoding="utf-8",
        )
    LOGGER.info("Saved A4S decisions: %s", decisions_log)

    LOGGER.info("Saved samples: %s", samples_csv)
    LOGGER.info("Updated runs: %s", runs_csv)
    LOGGER.info("Run complete.")


if __name__ == "__main__":
    main()
