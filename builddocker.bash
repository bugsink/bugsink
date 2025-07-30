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

    REPO="bugsink/bugsink"

    # numeric tags for this build
    TAG_LIST=(
      "$REPO:$VERSION"
      "$REPO:$(echo "$VERSION" | awk -F. '{print $1"."$2}')"
      "$REPO:$(echo "$VERSION" | awk -F. '{print $1}')"
    )

    # Find highest published semver on Docker Hub (public repo; no auth needed)
    HIGHEST_PUBLISHED=$(
      curl -fsSL "https://hub.docker.com/v2/repositories/${REPO}/tags?page_size=100" \
      | grep -o '"name":"[^"]*"' \
      | cut -d'"' -f4 \
      | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' \
      | sort -V \
      | tail -n1
    )

    # Decide whether we’re allowed to move :latest forward
    ADD_LATEST=true
    if [[ -n "$HIGHEST_PUBLISHED" ]]; then
      # if VERSION < HIGHEST_PUBLISHED, do NOT set :latest
      top=$(printf '%s\n%s\n' "$HIGHEST_PUBLISHED" "$VERSION" | sort -V | tail -n1)
      if [[ "$top" != "$VERSION" ]]; then
        ADD_LATEST=false
        echo "Not tagging :latest: $VERSION < already published $HIGHEST_PUBLISHED"
      fi
    fi

    # Build TAGS string
    TAGS=""
    for t in "${TAG_LIST[@]}"; do TAGS+=" -t $t"; done
    if $ADD_LATEST; then
      TAGS+=" -t $REPO:latest -t $REPO"
      echo "Tagging as latest: $VERSION ≥ ${HIGHEST_PUBLISHED:-<none>}"
    fi
fi

docker build -f Dockerfile.fromwheel --build-arg WHEEL_FILE=$WHEEL_FILE $TAGS .
