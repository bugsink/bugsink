#!/bin/bash
set -e

WHEEL_FILE=$(ls dist/ -1atr | grep bugsink | grep whl | tail -n1)

echo "Building docker image with wheel file: $WHEEL_FILE"

docker build --build-arg WHEEL_FILE=$WHEEL_FILE -t bugsink .
