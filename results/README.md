# Results

This folder contains results from running Nexmark experiments. The raw metrics
extracted from the job is stored under `nexmark/` in CSV form.

## Nexmark

### Structure

The `results/nexmark/` directory is grouped by queries. Under each query each 
run is grouped under its own unique folder name that has:

- The unix milisecond timestamp it started running
- The cluster it ran on (Kubernetes, Kind)
- The autoscaler used (A4S, DS2, Justin)
- The storage device used (HDD vs SSD)

This way each run can be uniquely identified. This information is also stored 
under the corresponding `runs.csv` under each folder.

### Content
Each run folder contains:

1. The raw metrics collected from Prometheus.
2. Logs collected from the Job Manager and Flink K8s Operator (these can be large, ~tens of mb and are by default gitignored).
3. Copy of the K8s Resource Definition used to run the job.

The metrics logged here is dependent on the script that is used to execute and
monitor the workload. The important thing is that each run has a predictable
format that can be accessed by scripts.

## Nexmark Graphs

The `results/nexmark_graphs/` directory is also grouped by queries and contains
visualizations based on the raw metrics collected from the Nexmark runs. This is
purely used as a target directory for scripts that generate graphs and otherwise
has no structure.