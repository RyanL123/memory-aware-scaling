#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FLINK_ROOT="${REPO_ROOT}/flink-justin/flink"
CUSTOM_JAR="${REPO_ROOT}/flink-justin/custom-libs/rocksdbjni-6.20.3-linux64.jar"

if ! command -v java >/dev/null 2>&1; then
  echo "java not found in PATH"
  exit 1
fi

if ! command -v mvn >/dev/null 2>&1; then
  echo "mvn not found in PATH"
  exit 1
fi

JAVA_VERSION_RAW="$(java -version 2>&1 | sed -n '1s/.*version "\(.*\)".*/\1/p')"
JAVA_MAJOR="$(printf '%s' "${JAVA_VERSION_RAW}" | cut -d. -f1)"
if [[ "${JAVA_MAJOR}" != "11" ]]; then
  echo "expected JDK 11, found: ${JAVA_MAJOR:-unknown}"
  exit 1
fi

if [[ ! -f "${CUSTOM_JAR}" ]]; then
  echo "missing custom RocksDB jar: ${CUSTOM_JAR}"
  exit 1
fi

echo "Installing custom RocksDB JNI artifact into local Maven repository..."
mvn install:install-file \
  -Dfile="${CUSTOM_JAR}" \
  -DgroupId=org.rocksdb \
  -DartifactId=frocksdbjni \
  -Dversion=6.20.3-custom \
  -Dpackaging=jar

echo "Building flink-justin/flink with build-only flags (no tests/checks)..."
(
  cd "${FLINK_ROOT}"
  ./mvnw \
    clean install \
    -T 8 \
    -DskipTests \
    -Drat.skip=true \
    -Dcheckstyle.skip=true \
    -Dspotless.check.skip=true \
)

echo "Build completed. Distribution is under ${FLINK_ROOT}/flink-dist/target/."
