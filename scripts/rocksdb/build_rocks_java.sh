#!/usr/bin/env bash
set -e

docker build -t rocksdb-builder-jammy -f ./scripts/rocksdb/Dockerfile.ubuntu-jammy .

docker run --rm \
    -v ./frocksdb:/rocksdb-host:ro \
    -v ./frocksdb/java/target:/rocksdb-java-target \
    -e DEBUG_LEVEL=0 \
    rocksdb-builder-jammy \
    /rocksdb-host/java/crossbuild/docker-build-linux-ubuntu.sh

cp ./frocksdb/java/target/rocksdbjni-*-linux*.jar ./flink-justin/custom-libs/