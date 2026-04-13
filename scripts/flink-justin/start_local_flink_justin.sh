#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FLINK_DIST_TARGET="${REPO_ROOT}/flink-justin/flink/build-target/bin"

export FLINK_CONF_DIR=./configs/

"${FLINK_DIST_TARGET}/start-cluster.sh"