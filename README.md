# Memory Aware Scaling

This repository contains artifacts used to implement the A4S autoscaler as described in the paper "A4S: Co-designing Scaling and Placement in Stream Processing Systems with Memory-parallelism Curves" by Kexiang Wang.

The A4S logic is currently implemented on top of artifacts from Flink Justin, as described in the paper "Justin: Hybrid CPU/Memory Elastic Scaling for Distributed Stream Processing" by Donatien Schmitz et al.

Quickmrc for sampling stack distance histograms is implemented in a custom fork of RocksDB 6.23.0. This was done from scratch and does not rely on Flink Justin.

Benchmarking is done through the use of Nexmark queries. Some Nexmark binaries are taken from those used in Flink Justin while others are newly built and wrappers on top of Flink SQL queries within the official Nexmark repository.

## Scripts

This folder contains various Python and Shell scripts to conveniently interact with the cluster.This includes building images, running experiments, and collecting results. All shell scripts rely on `env.sh` for variable definitions. 

> When running the Python scripts, make sure they're ran in a shell after sourcing `env.sh` so the Kubernetes control plane can be correctly located.

The scripts folder is laid out as such:
- **cluster/**: Interacting with the K8s cluster.
- **experiements/**: Run Nexmark queries, sample metrics, plotting results.
- **flink-justin/**: Build flink/operator images from `flink-justin/` and pushing them to the local registry.
- **rocksdb/**: Building rocksdb runtime and generating JNIs.

## Queries 

The queries folder contains resource definitions for various Nexmark queries. These use the custom flink runtime that has the custom Nexmark jar embedded into it and a custom query loader that generates queries via Flink's Table API from the SQL queries

Queries with `ssd` in the name mounts the SSD drive on the machine as a volume for the RocksDB state backend. Otherwise, RocksDB will use whatever drive the container is running on.

## Results

The `scripts/experiments/run_nexmark_experiment.py` script stores run results here. Runs are grouped by their queries and sorted monotonically increasing by when they're started (via unix epoch time).

Each run keeps track of the following data:
- **samples.csv**: Ground truth data of metrics scraped directly from the Flink's Metrics API
- **plot.png**: Plot of ground truth data in `samples.csv`.
- **a4s_decisions.log**: A4S logs fetched from the operator during the run. This is done by grepping all logs since the start of the run with "A4S:" in the prefix. This file will be empty if A4S is not enabled.
- **`<manifest>.yaml`**: Snapshot of theResource Definition used to run the experiment. 
