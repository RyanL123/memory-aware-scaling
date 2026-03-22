#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${REPO_ROOT}/scripts/env.sh"

echo "Installing Flink Kubernetes Operator on cluster..."
helm install flink-kubernetes-operator \
    "${HELM_CHART}" \
    --set "image.pullPolicy=Always" \
    --set "image.repository=${REGISTRY}/${OPERATOR_IMAGE_NAME}" \
    --set "image.tag=${OPERATOR_IMAGE_TAG}" \
    -f "${AUTOSCALER_VALUES}"