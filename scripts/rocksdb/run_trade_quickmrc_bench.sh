#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run trade-like db_bench workload and evaluate QuickMRC.

Usage:
  run_trade_quickmrc_bench.sh [options]

Options:
  --db-path PATH                     DB path (default: /tmp/dbbench-trade)
  --output-dir PATH                  Output directory (default: /tmp/traces)
  --prefix STR                       Output file prefix (default: trade_qmrc)
  --threads N                        db_bench threads (default: 16)
  --duration-sec N                   Mixed workload duration seconds (default: 600)
  --num N                            Number of keys for fill phase (default: 8000000)
  --readwritepercent N               Read ratio for mixed phase [0..100] (default: 80)
  --key-size N                       Key size bytes (default: 24)
  --value-size N                     Value size bytes (default: 128)
  --cache-size-bytes N               RocksDB block cache size bytes (default: 2147483648)
  --trace-max-size-bytes N           Max trace file size bytes (default: 68719476736)
  --trace-sampling-frequency N       Block cache trace sampling frequency (default: 1)
  --trace-max-accesses N             Max accesses loaded by quickmrc_benchmark (default: 5000000)
  --trace-data-blocks-only 0|1       Use only data-block accesses (default: 1)
  --quick-mrc-sampling-rate F        QuickMRC sampling rate [0,1] (default: 0.5)
  --quick-mrc-histogram-bin-size N   QuickMRC histogram bin size (default: 1)
  --quick-mrc-max-bucket-size N      QuickMRC max bucket size (default: 60)
  --quick-mrc-ghost-multiplier N     QuickMRC ghost cache multiplier (default: 64)
  --db-bench-bin PATH                db_bench binary path (default: <repo>/frocksdb/db_bench)
  --quickmrc-bin PATH                quickmrc_benchmark binary path (default: <repo>/frocksdb/quickmrc_benchmark)
  --keep-db                          Keep existing DB directory (default: disabled)
  -h, --help                         Show this help

Examples:
  scripts/rocksdb/run_trade_quickmrc_bench.sh
  scripts/rocksdb/run_trade_quickmrc_bench.sh --duration-sec 900 --readwritepercent 70
EOF
}

ROOT_DIR="$(git rev-parse --show-toplevel)"
FROCKSDB_DIR="${ROOT_DIR}/frocksdb"

DB_PATH="/tmp/dbbench-trade"
OUTPUT_DIR="/tmp/traces"
PREFIX="trade_qmrc"
THREADS=1
DURATION_SEC=300
NUM=8000000
READWRITEPERCENT=80
KEY_SIZE=24
VALUE_SIZE=128
CACHE_SIZE_BYTES=$((2 * 1024 * 1024 * 1024)) # 2GB
TRACE_MAX_SIZE_BYTES=$((1 * 1024 * 1024 * 1024)) # 1GB
TRACE_SAMPLING_FREQUENCY=1
TRACE_MAX_ACCESSES=5000000
TRACE_DATA_BLOCKS_ONLY=1
QUICK_MRC_SAMPLING_RATE="0.02"
QUICK_MRC_HISTOGRAM_BIN_SIZE=1024
QUICK_MRC_MAX_BUCKET_SIZE=5
QUICK_MRC_GHOST_MULTIPLIER=64
DB_BENCH_BIN="${FROCKSDB_DIR}/db_bench"
QUICKMRC_BIN="${FROCKSDB_DIR}/quickmrc_benchmark"
KEEP_DB=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db-path) DB_PATH="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --threads) THREADS="$2"; shift 2 ;;
    --duration-sec) DURATION_SEC="$2"; shift 2 ;;
    --num) NUM="$2"; shift 2 ;;
    --readwritepercent) READWRITEPERCENT="$2"; shift 2 ;;
    --key-size) KEY_SIZE="$2"; shift 2 ;;
    --value-size) VALUE_SIZE="$2"; shift 2 ;;
    --cache-size-bytes) CACHE_SIZE_BYTES="$2"; shift 2 ;;
    --trace-max-size-bytes) TRACE_MAX_SIZE_BYTES="$2"; shift 2 ;;
    --trace-sampling-frequency) TRACE_SAMPLING_FREQUENCY="$2"; shift 2 ;;
    --trace-max-accesses) TRACE_MAX_ACCESSES="$2"; shift 2 ;;
    --trace-data-blocks-only) TRACE_DATA_BLOCKS_ONLY="$2"; shift 2 ;;
    --quick-mrc-sampling-rate) QUICK_MRC_SAMPLING_RATE="$2"; shift 2 ;;
    --quick-mrc-histogram-bin-size) QUICK_MRC_HISTOGRAM_BIN_SIZE="$2"; shift 2 ;;
    --quick-mrc-max-bucket-size) QUICK_MRC_MAX_BUCKET_SIZE="$2"; shift 2 ;;
    --quick-mrc-ghost-multiplier) QUICK_MRC_GHOST_MULTIPLIER="$2"; shift 2 ;;
    --db-bench-bin) DB_BENCH_BIN="$2"; shift 2 ;;
    --quickmrc-bin) QUICKMRC_BIN="$2"; shift 2 ;;
    --keep-db) KEEP_DB=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ ! -x "$DB_BENCH_BIN" ]]; then
  echo "db_bench binary not found/executable: $DB_BENCH_BIN" >&2
  exit 1
fi
if [[ ! -x "$QUICKMRC_BIN" ]]; then
  echo "quickmrc_benchmark binary not found/executable: $QUICKMRC_BIN" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
RUN_ID="$(date +%s)"
TRACE_FILE="${OUTPUT_DIR}/${PREFIX}_${RUN_ID}.trace"
FINAL_PREFIX="${PREFIX}_${RUN_ID}"

echo "== Trade-like db_bench + QuickMRC run =="
echo "db_bench:         $DB_BENCH_BIN"
echo "quickmrc_bench:   $QUICKMRC_BIN"
echo "db_path:          $DB_PATH"
echo "output_dir:       $OUTPUT_DIR"
echo "trace_file:       $TRACE_FILE"
echo "run_prefix:       $FINAL_PREFIX"

if [[ "$KEEP_DB" -eq 0 ]]; then
  rm -rf "$DB_PATH"
fi

echo
echo "Step 1/2: Generating block cache trace via db_bench..."
"$DB_BENCH_BIN" \
  --benchmarks=fillrandom,readrandomwriterandom \
  --db="$DB_PATH" \
  --use_existing_db=0 \
  --num="$NUM" \
  --threads="$THREADS" \
  --duration="$DURATION_SEC" \
  --key_size="$KEY_SIZE" \
  --value_size="$VALUE_SIZE" \
  --value_size_distribution_type=fixed \
  --readwritepercent="$READWRITEPERCENT" \
  --block_size=4096 \
  --cache_size="$CACHE_SIZE_BYTES" \
  --cache_index_and_filter_blocks=1 \
  --partition_index_and_filters=1 \
  --pin_l0_filter_and_index_blocks_in_cache=1 \
  --bloom_bits=10 \
  --statistics=1 \
  --stats_level=3 \
  --block_cache_trace_file="$TRACE_FILE" \
  --block_cache_trace_sampling_frequency="$TRACE_SAMPLING_FREQUENCY" \
  --block_cache_trace_max_trace_file_size_in_bytes="$TRACE_MAX_SIZE_BYTES"

echo
echo "Step 2/2: Running quickmrc_benchmark on trace..."
"$QUICKMRC_BIN" \
  --block_cache_trace_file="$TRACE_FILE" \
  --trace_data_blocks_only="$TRACE_DATA_BLOCKS_ONLY" \
  --block_cache_trace_max_accesses="$TRACE_MAX_ACCESSES" \
  --quick_mrc_sampling_rate="$QUICK_MRC_SAMPLING_RATE" \
  --quick_mrc_histogram_bin_size="$QUICK_MRC_HISTOGRAM_BIN_SIZE" \
  --quick_mrc_max_bucket_size="$QUICK_MRC_MAX_BUCKET_SIZE" \
  --quick_mrc_ghost_cache_multiplier="$QUICK_MRC_GHOST_MULTIPLIER" \
  --output_dir="$OUTPUT_DIR" \
  --output_prefix="$FINAL_PREFIX"

echo
echo "Done."
echo "Trace file:"
echo "  $TRACE_FILE"
echo "QuickMRC outputs:"
echo "  ${OUTPUT_DIR}/${  }_mrc_comparison.csv"
echo "  ${OUTPUT_DIR}/${FINAL_PREFIX}_quickmrc_histogram.csv"
echo "  ${OUTPUT_DIR}/${FINAL_PREFIX}_run_config.json"
