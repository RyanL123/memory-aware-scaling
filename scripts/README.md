# Scripts

This directory contains various Python and Bash scripts used to control the cluster, run experiements,
compile code, or any other workflow that is to be repeated. 

The core philosophy of the scripts is to keep them small and re-usable, with higher level scripts that
orchestrate through using lower-level ones. This way we may execute each script
individually if needed to run a specific part of the workflow.

## Layout

Below is a short summary of how scripts are roughly grouped. For more information,
read the scripts themselves.

- `env.sh`: Contains environmental variables that other scripts rely upon. Scripts should
always source this before beginning execution.
- `cluster/`: Interacting with the Kubernetes Cluster.
- `experiements/`: Running Nexmark experiements, collecting metrics, logging results.
- `flink-justin/`: Compiling the Flink Justin codebase, deploying, submitting jobs.
- `prometheus/`: Interacting with the Prometheus server, metrics extraction.
- `rocksdb/`: Compiling and running the custom RocksDB binary.