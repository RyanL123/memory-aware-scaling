# Changes Overview

Overview of the custom changes in this FRocksDB fork.

---

## Block Cache Tracing

- Added `startBlockCacheTrace()` and `endBlockCacheTrace()` to the RocksDB Java API and JNI layer.
- Allows tracing block cache access during a workload for analysis and tuning.
- Includes tests to verify tracing behavior.

---

## Raw Stats API (Miss-Rate Curve)

- Extended `LRUCache` in C++ and RocksJava with APIs for miss-rate curve generation.
- New Java classes: `BucketStatistics` (per-bucket hit/miss counts for merging across tasks) and `MissRateCurveResult` (cache size vs miss rate).
- Supports distributed workloads where stats from multiple tasks are merged (section 3.4.2 of the MRC paper).
- Optional ghost cache mode for LRUCache to estimate miss rates at different cache sizes.

---

## Cache Tests

- Added `LRUCacheTest` for the new LRUCache APIs and miss-rate curve behavior.
- Added `BlockCacheTraceTest` for block cache tracing.

---

## Build on Ubuntu 22.04

- Added `Dockerfile.ubuntu-jammy` for cross-building on Ubuntu 22.04 (Jammy).
- Updated `docker-build-linux-ubuntu.sh` to support the Jammy build target.
- Uses OpenJDK 11 for the Jammy build.

---

## Ghost Cache and QuickMRC (quickmrc branch)

- **QuickMRC implementation:** Implemented the quick Miss-Rate Curve (MRC) algorithm in the LRUCache, with C++ and Java bindings. Enables efficient miss-rate curve generation for cache sizing.
- **Do not sample for ghost cache:** Adjusted ghost cache behavior so it does not sample, improving correctness or performance of the MRC computation.

---

## Summary

The changes add **block cache tracing**, a **raw stats / miss-rate curve API** for cache analysis and sizing, **tests** for these features, **Ubuntu 22.04 build support**, and on the `quickmrc` branch, **quickMRC and ghost cache** improvements for miss-rate curve generation.
