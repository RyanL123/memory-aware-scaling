FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    clang-format \
    cmake \
    curl \
    libbz2-dev \
    libgflags-dev \
    liblz4-dev \
    libsnappy-dev \
    libzstd-dev \
    openjdk-11-jdk-headless \
    openssl \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64