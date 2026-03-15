# Memory-Aware Scaling

This document describes the **memory-aware scaling** features in this repository: how the autoscaler adjusts memory and parallelism based on workload and state backend behavior, and how **RocksDB** was extended to support configurable memory, shared caches, and stack distance histograms for A4S.

See the main [README.md](./README.md) for overall repo layout, Justin, A4S, and benchmark instructions.

---

## 1. Autoscaler memory scaling (operator)

The Flink Kubernetes Operator autoscaler can scale **memory** in addition to parallelism so that total cluster memory stays stable when adding or removing TaskManagers.

### 1.1 Memory scaling behavior

- **Scale down**: Removing TaskManagers reduces available memory. Memory scaling keeps **total cluster memory** roughly constant by increasing memory per remaining TaskManager until the workload’s actual usage is observed.
- **Scale up**: When adding TaskManagers, memory is not reduced, so the job does not become memory-constrained. Later, **MemoryTuning** can lower the per–TaskManager memory baseline if appropriate.

### 1.2 Where it lives

| Component | Path | Role |
|-----------|------|------|
| **MemoryScaling** | `flink-kubernetes-operator/flink-autoscaler/.../tuning/MemoryScaling.java` | Computes a memory scaling factor from current parallelism and scaling summaries; applies it to the TaskManager memory size. |
| **MemoryTuning** | `flink-kubernetes-operator/flink-autoscaler/.../tuning/MemoryTuning.java` | Uses scaling decisions and metrics to tune memory (calls `MemoryScaling.applyMemoryScaling` when enabled). |
| **AutoScalerOptions** | `flink-kubernetes-operator/flink-autoscaler/.../config/AutoScalerOptions.java` | `MEMORY_SCALING_ENABLED` and related options (e.g. balance between memory vs parallelism scaling). |

### 1.3 Configuration

- **`MEMORY_SCALING_ENABLED`** (default: config-dependent): turn memory scaling on/off.
- Other options in `AutoScalerOptions` control how aggressively the autoscaler favors memory scaling vs parallelism scaling.

### 1.4 Tests

- **MemoryScalingTest**: `flink-kubernetes-operator/flink-autoscaler/.../tuning/MemoryScalingTest.java`  
  - Downscaling, upscaling, and disabled memory scaling.
- **MemoryTuningTest**: `flink-kubernetes-operator/flink-autoscaler/.../tuning/MemoryTuningTest.java`  
  - Integration with memory scaling and tuning logic.

---

## 2. A4S and memory–parallelism curves (MPC)

Memory-aware scaling is extended by **A4S**, which uses **stack distance histograms** and **miss rate curves (MRCs)** to build **memory–parallelism curves (MPCs)** and choose (parallelism, memory) points.

- Stack distance histograms come from **RocksDB** (see Section 3).
- Histograms are merged and turned into MRCs (unscaled and horizontally scaled by number of tasks).
- MRCs are used to derive MPCs; the A4S policy picks a point on the MPC for scaling.

Details are in the main README under “A4S autoscaling pipeline” and “Stack distance histograms & A4S runtime metrics.”

---

## 3. RocksDB changes

All RocksDB-related code lives under **`flink/flink-state-backends/flink-statebackend-rocksdb/`**. The following extensions support memory-aware scaling and A4S.

### 3.1 Memory configuration and taskmanager-wide sharing

**Goal:** Control how much memory RocksDB uses and allow sharing of caches across operators/tasks on a TaskManager.

| File | Purpose |
|------|--------|
| **RocksDBMemoryConfiguration** | Holds settings for RocksDB memory: managed vs fixed budget, write buffer ratio, high-priority pool ratio, **LRU cache shard count**, partitioned index/filters, etc. |
| **RocksDBMemoryControllerUtils** | Applies `RocksDBMemoryConfiguration`: computes and sets memory budgets and cache sizes for RocksDB instances (including shard-aware and taskmanager-wide sharing). |
| **RocksDBResourceContainer** | Manages shared RocksDB resources (e.g. shared block cache) used by multiple backends. |
| **RocksDBSharedResourcesFactory** | Creates shared resources (caches, etc.) so that RocksDB state backends can share memory at the TaskManager level. |

**Configuration (RocksDBOptions and related):**

- Number of **LRU cache shards** is configurable (e.g. `state.backend.rocksdb.lru.num-shards` or similar), so cache can be tuned for concurrency and memory behavior.
- Memory can be allocated per slot or as a shared pool; see `RocksDBMemoryConfiguration` and `RocksDBOptions` for options.

**Restore operations** (so that restores respect the new memory configuration):

- **RocksDBFullRestoreOperation**
- **RocksDBHeapTimersFullRestoreOperation**
- **RocksDBIncrementalRestoreOperation**
- **RocksDBNoneRestoreOperation**
- **RocksDBHandle**

These were updated to use the shared resource factory and memory controller so that after restore, RocksDB uses the same memory and sharding configuration.

**Tests:**

- **RocksDBMemoryControllerUtilsTest** – budget and cache size computation.
- **RocksDBStateBackendConfigTest** – configuration loading and application.
- **TaskManagerWideRocksDbMemorySharingITCase** – end-to-end taskmanager-wide RocksDB memory sharing.

### 3.2 RocksDB native metrics and stack distance histograms

**Goal:** Expose RocksDB internals as Flink metrics and, in particular, **stack distance histograms** for A4S.

| File | Purpose |
|------|--------|
| **RocksDBNativeMetricOptions** | Config options for which RocksDB metrics to report (tickers, histograms, column-family properties). Extended to support **stack distance histogram** metrics. |
| **RocksDBNativeMetricMonitor** | Periodically reads RocksDB statistics and properties and reports them as Flink metrics. Updated to collect and report **stack distance histogram** data (bucket counts) from RocksDB. |

**Stack distance histograms:**

- Produced inside RocksDB (e.g. via a custom build with histogram instrumentation or JNI).
- Reported through `RocksDBNativeMetricMonitor` and then exposed to the Flink runtime metric system.
- The runtime’s **StackDistanceHistogramProvider** / **StackDistanceHistogramResult** and the JobManager’s **A4SAggregatingVertexMetricsHandler** aggregate these per task and expose them for A4S.

**Tests:**

- **RocksDBNativeMetricMonitorTest** – ensures native metrics (including histogram-related) are updated as expected.

### 3.3 Custom RocksDB build and JNI

**Goal:** Use a RocksDB build that exposes stack distance histograms and wire it into Flink via JNI.

| Artifact / change | Purpose |
|-------------------|--------|
| **custom-libs/rocksdbjni-6.20.3-linux64.jar** | Custom RocksDB JNI library that includes the APIs needed to retrieve stack distance histograms from the RocksDB cache/LRU layer. |
| **flink-statebackend-rocksdb/pom.xml** | Updated to depend on this custom RocksDB JNI artifact instead of (or in addition to) the default RocksDB JNI. |
| **JNI calls in RocksDB backend** | Code paths that call into RocksDB JNI to **retrieve histograms** (e.g. from the native monitor or a dedicated histogram provider) and feed them into `RocksDBNativeMetricMonitor` / Flink metrics. |

**Configuration:**

- **RocksDBOptions** (and related options in `RocksDBKeyedStateBackendBuilder`, etc.) may expose options for:
  - Enabling histogram collection.
  - Number of histogram buckets or step size (e.g. constant 32-step buckets).
  - LRU/cache options that the custom RocksDB build uses for stack distance tracking.

### 3.4 Summary of RocksDB-related files (main and test)

**Main:**

- `RocksDBMemoryConfiguration.java`
- `RocksDBMemoryControllerUtils.java`
- `RocksDBOptions.java`
- `RocksDBKeyedStateBackendBuilder.java`
- `RocksDBResourceContainer.java`
- `RocksDBSharedResourcesFactory.java`
- `RocksDBNativeMetricOptions.java`
- `RocksDBNativeMetricMonitor.java`
- Restore: `RocksDBFullRestoreOperation.java`, `RocksDBHeapTimersFullRestoreOperation.java`, `RocksDBIncrementalRestoreOperation.java`, `RocksDBNoneRestoreOperation.java`, `RocksDBHandle.java`

**Tests:**

- `RocksDBMemoryControllerUtilsTest.java`
- `RocksDBStateBackendConfigTest.java`
- `RocksDBNativeMetricMonitorTest.java`
- `TaskManagerWideRocksDbMemorySharingITCase.java`
- `RocksDBSharedResourcesFactoryTest.java`, `RocksDBResourceContainerTest.java` (if present)

---

## 4. How it fits together

1. **RocksDB** (custom build + JNI) produces **stack distance histograms** and exposes them via **RocksDBNativeMetricMonitor** and Flink metrics.
2. The **runtime** collects these histograms per task and the **JobManager** aggregates them (e.g. **A4SAggregatingVertexMetricsHandler**).
3. **A4S** uses aggregated histograms to build **MRCs**, then **MPCs**, and chooses a (parallelism, memory) target.
4. The **autoscaler** applies parallelism scaling and, when **memory scaling** is enabled, uses **MemoryScaling** and **MemoryTuning** to adjust TaskManager memory so that the cluster remains memory-aware and stable across scale-up/scale-down.

For end-to-end instructions (Kind, Grid5000, benchmarks), see the main [README.md](./README.md) and [Benchmarks.md](./Benchmarks.md).
