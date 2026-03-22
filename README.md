## Scripts

This folder contains various Python and Shell scripts to conveniently interact with the cluster.This includes building images, running experiments, and collecting results. All shell scripts rely on `env.sh` for variable definitions. 

When running the Python scripts, make sure they're ran in a shell after sourcing `env.sh` so the Kubernetes control plane can be correctly located.

## Queries

The queries folder contains resource definitions for various Nexmark queries. These use the custom flink runtime that has the custom Nexmark jar embedded into it and a custom query loader that generates queries via Flink's Table API from the SQL queries

Queries with `ssd` in the name mounts the SSD drive on the machine as a volume for the RocksDB state backend. Otherwise, RocksDB will use whatever drive the container is running on.

## Results

The `scripts/experiments/run_nexmark_experiment.py` script stores run results here. Runs are grouped by their queries and sorted monotonically increasing by when they're started (via unix epoch time).

Each run has ground-truth data in the form of `samples.csv`. A plot may be generated from this data via `scripts/experiments/plot_run.py`.