#!/bin/bash
set -e

WHEEL_FILE=$(ls dist/ -1atr | grep bugsink | grep whl | tail -n1)
echo "Building docker image with wheel file: $WHEEL_FILE"

echo "Is this the correct wheel file? [y/n]"
read -r response
if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo "Please run the script again with the correct wheel file in the dist/ directory"
    exit 1
fi

# example: bugsink-0.1.8.dev5+g200ea5e.d20240827-py3-none-any.whl

# if this a non-dev version, we tag the image with the full version number, major.minor, major, and latest
# otherwise no tags are added

if [[ $WHEEL_FILE == *"dev"* ]]; then
    echo "This is a dev version, no (numbered) tags will be added, just a :dev tag"
    TAGS="-t bugsink/bugsink:dev"
else
    VERSION=$(echo $WHEEL_FILE | cut -d'-' -f2)
    TAGS="-t bugsink/bugsink:$VERSION -t bugsink/bugsink:$(echo $VERSION | awk -F. '{print $1"."$2}') -t bugsink/bugsink:$(echo $VERSION | awk -F. '{print $1}') -t bugsink/bugsink:latest -t bugsink/bugsink"
    echo "This is a non-dev version, tags will be added: $TAGS"
fi


docker buildx  build --platform linux/amd64,linux/arm64  --build-arg WHEEL_FILE=$WHEEL_FILE $TAGS . --push
