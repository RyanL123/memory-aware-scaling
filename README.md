# Memory Aware Scaling

## Overview

This repository contains artifacts and code used to evaluate **memory-aware scaling** for stateful stream processing, centered around the **A4S** autoscaling policy and an experimental harness based on **Nexmark** workloads.

At a high level, this codebase combines:
- A research autoscaler stack built on top of the **Justin** artifacts (“Justin: Hybrid CPU/Memory Elastic Scaling for Distributed Stream Processing”, Donatien Schmitz et al.).
- The A4S scaling algorithm (“A4S: Co-designing Scaling and Placement in Stream Processing Systems with Memory-parallelism Curves”, Kexiang Wang).
- A custom RocksDB fork used for cache/miss-rate-curve and histogram-related support needed for A4S.

## Repository map

- `scripts/`: helper scripts for building images, interacting with clusters, running experiments, and collecting/plotting results.
- `queries/`: Kubernetes resource definitions for running Nexmark queries against the custom runtime.
- `results/`: experiment outputs produced by the harness scripts. Includes ground truth data and generated plots.
- `flink-justin/`: the main forked stack (Flink runtime + operator + benchmark harness) from the Justin paper. A4S is implemented on top of this fork at the moment.
- `frocksdb/`: the RocksDB fork used by this project (version 6.20.3)

## Dependencies
- **Environment**: This project was developed on the `fs.csl.utoronto.ca` servers on Ubuntu 24.04.3 LTS.
- **flink-justin**: Forks Flink Kubernetes Operator 1.13 and Flink Runtime 1.18. Both require Java 11.
- **frocksdb**: Forks version 6.20.3. Requires GCC >= 4.8 and C++11.
- Docker
- Kubernetes

## Workflow
### 1. Set up a Kubernetes Cluster

See https://kubernetes.io/docs/setup/ to set up a cluster. Alternatively, set up a cluster via Kind.

After setting up the cluster, update relevant variables in `scripts/env.sh` to point to the control plane.

### 2. Build the RocksDB

```bash
./scripts/rocksdb/build_rocks_java.sh
```

The resulting JAR will be copied into `flink-justin/custom-libs/`

### 3. Build the Flink Kubernetes Operator and Flink Runtime

**Build the Flink Kubernetes Operator:**
```bash
./scripts/flink-justin/build_flink_k8s_operator.sh
```
Expect this to take around 4-5 minutes. The image size should be a few hundred MB.

**Build the Flink Runtime:**
```bash
./scripts/flink-justin/build_flink_justin.sh
```
Expect this to take at least 15-20 minutes. The image size should be around 4 GB.

### 4. Deploy the Flink Kubernetes Operator
Ensure `scripts/env.sh` is pointing to the correct cluster.
```bash
./scripts/cluster/install_operator.sh
```

### 5. Submit workloads
Manually submitting workloads:
```bash
kubectl apply -f queries/<query>.yaml
```
Note this will not automatically capture results

Via Python Script:
```bash
python scripts/run_nexmark_experiment.py --query=q8 --manifest=queries/<query>.yaml --policy=a4s --duration-sec=1800
```
This will:
- Automatically run the query for the specified duration and tear it down after
- Collect Operator and Job Manager logs during the run 
- After the run finishes, query the Prometheus server for metrics and save it to the run
- Record the run in `results/`


### 6. Getting results
If step 5 was ran via the Python script, results should automatically be available under `results/nexmark/`. 

## Related Documentation
- [`scripts/README.md`](scripts/README.md)
- [`results/README.md`](results/README.md)