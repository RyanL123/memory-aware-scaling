#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FLINK_DIST_TARGET="${REPO_ROOT}/flink-justin/flink/build-target/bin"

export FLINK_CONF_DIR=./configs/

"${FLINK_DIST_TARGET}/flink" run \
    --target local \
    -c com.github.nexmark.flink.sql.SqlQueryJob \
    -p 1 \
    ./flink-justin/nexmark-flink-0.3-SNAPSHOT.jar \
    --query q20_unique \
    --tps 50000 \
    --events 12500000 \
    --max-emit-speed false \
    --job-name q20_unique-sql-ssd-ds2