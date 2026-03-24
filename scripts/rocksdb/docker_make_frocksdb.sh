#!/usr/bin/env bash
# Run `make` in frocksdb/ inside the Ubuntu 22.04 image (see Dockerfile.ubuntu-jammy).
# Build artifacts are written to the host repo under frocksdb/ via a bind mount.
#
# Usage:
#   ./scripts/rocksdb/docker_make_frocksdb.sh [ --no-build ] [ make args... ]
#
# Examples:
#   ./scripts/rocksdb/docker_make_frocksdb.sh static_lib
#   ./scripts/rocksdb/docker_make_frocksdb.sh -j"$(nproc)" shared_lib
#   FROCKSDB_DOCKER_RUN_EXTRA="-e PORTABLE=1" ./scripts/rocksdb/docker_make_frocksdb.sh static_lib
#
# Optional:
#   --no-build          Skip `docker build` (reuse existing rocksdb-builder-jammy image)
#   FROCKSDB_DOCKER_RUN_EXTRA   Extra args for docker run (word-split; e.g. -e VAR=value)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE_TAG="rocksdb-builder-jammy"

NO_BUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build)
      NO_BUILD=1
      shift
      ;;
    *)
      break
      ;;
  esac
done

cd "$REPO_ROOT"

if [[ "$NO_BUILD" -eq 0 ]]; then
  docker build -t "$IMAGE_TAG" -f "$SCRIPT_DIR/Dockerfile.ubuntu-jammy" .
fi

docker_run_extra=()
if [[ -n "${FROCKSDB_DOCKER_RUN_EXTRA:-}" ]]; then
  read -r -a docker_run_extra <<< "$FROCKSDB_DOCKER_RUN_EXTRA"
fi

docker run --rm \
  --user "$(id -u):$(id -g)" \
  "${docker_run_extra[@]}" \
  -v "$REPO_ROOT/frocksdb:/rocksdb" \
  -w /rocksdb \
  "$IMAGE_TAG" \
  make "$@"
