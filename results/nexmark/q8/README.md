# Nexmark Query 8 Results Ledger

This directory stores comparable, append-only benchmark records for Nexmark Query 8 runs in this repository.

## Purpose

Use this ledger to compare Query 8 behavior across code changes, image versions, and autoscaler policy updates (Justin/A4S).

The structure combines:
- `runs.csv`: one row per run with normalized summary fields
- `<date>-<env>-samples.csv`: raw time-series samples collected during the run

## Run: 2026-02-24 (kind baseline)

### Run ID

- `2026-02-24-kind-q8-a4s-justin-baseline`

### Scope and setup

- Cluster: `kind` (`kind-kind` context), 1 control-plane + 3 workers
- Flink runtime image: `flink-justin:dais` (prebuilt, loaded to all kind nodes)
- Flink operator image: `flink-kubernetes-operator:dais` (rebuilt and loaded to all kind nodes)
- Operator deployment: Helm chart `flink-kubernetes-operator` with `examples/autoscaling/values.yaml`
- Query manifest: `notebooks/nexmark/q8/query8.yaml`
- Flink job name: `Nexmark Query8`
- Flink job id: `ce92d5e36d1e4bad99036a9fab380a30`

### Autoscaling signals observed

- Job reached `RUNNING`
- FlinkDeployment events included:
  - `In-place scaling triggered`
  - scaling report with vertex `11ffd1a2...` recommendation (`Parallelism 1 -> 3`)
  - configuration recommendation for memory tuning

### Data collection method

Primary intent was to read the three canonical metrics:
1. Source throughput
2. Total managed memory used
3. Total task slots used

Prometheus endpoint was reachable, but it had no Flink scrape targets in this run, so equivalent values were collected from Flink REST:
- Throughput: summed source vertex `numRecordsOutPerSecond` subtask metrics from both source vertices
- Managed memory: sum of `Status.Flink.Memory.Managed.Used` across both taskmanagers
- Slots used: `slots-total - slots-available` from `/overview`

Sampling interval was 20 seconds for 9 samples (~3 minutes).

### Summary statistics

- Throughput (all samples): `18631.90 records/s` average
- Throughput (steady-state, last 5 samples): `23708.14 records/s` average
- Throughput steady-state range: `22127.33` to `24223.13 records/s`
- Managed memory (steady-state): `158.00 MiB` total
- Slots used (steady-state): `3` total

### Raw sample file

- `2026-02-24-kind-q8-a4s-justin-baseline-samples.csv`

## How to add future runs

1. Keep one row per run in `runs.csv`.
2. Keep a raw sample CSV next to this README.
3. Use a stable run ID format:
   - `<YYYY-MM-DD>-<env>-q8-<policy>-<note>`
4. Always fill `metric_source` and `notes` so readers can compare apples-to-apples.

## Known comparison caveats

- If Prometheus scrape targets differ between runs, metrics source may differ (`prometheus` vs `flink-rest`).
- Steady-state windows must be compared consistently (this run uses last 5 of 9 samples).
- Autoscaler events can precede or lag metric stabilization; use both event logs and sample series.
