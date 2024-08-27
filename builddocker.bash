#!/bin/bash
set -e

WHEEL_FILE=$(ls dist/ -1atr | grep bugsink | grep whl | tail -n1)
echo "Building docker image with wheel file: $WHEEL_FILE"

# example: bugsink-0.1.8.dev5+g200ea5e.d20240827-py3-none-any.whl

# if this a non-dev version, we tag the image with the full version number, major.minor, major, and latest
# otherwise no tags are added

TAGS=""
if [[ $WHEEL_FILE == *"dev"* ]]; then
    echo "This is a dev version, no tags will be added"
else
    VERSION=$(echo $WHEEL_FILE | cut -d'-' -f2)
    TAGS="-t bugsink:$VERSION -t bugsink:$(echo $VERSION | awk -F. '{print $1"."$2}') -t bugsink:$(echo $VERSION | awk -F. '{print $1}') -t bugsink:latest"
    echo "This is a non-dev version, tags will be added: $TAGS"
fi


docker build --build-arg WHEEL_FILE=$WHEEL_FILE $TAGS .
