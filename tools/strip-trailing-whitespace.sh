#!/bin/bash
#
# Strip trailing whitespace from tracked files with specific extensions.
# Usage: ./tools/strip-trailing-whitespace.sh
# Works on macOS (BSD sed) or Linux (GNU sed), but not both at once.

set -euo pipefail

# Extensions to include
EXT_REGEX='\.(py|js|ts|sh|md|txt|html|css|bash)$'

# Detect sed flavor
if sed --version >/dev/null 2>&1; then
    SED_CMD=(sed -i -e 's/[[:space:]]\+$//')
elif sed -i '' testfile 2>/dev/null; then
    SED_CMD=(sed -i '' -e 's/[[:space:]]\+$//')
else
    echo "Unsupported sed version. Must be GNU sed or BSD sed (macOS)." >&2
    exit 1
fi

git ls-files -z | while IFS= read -r -d '' file; do
    [[ -f "$file" ]] || continue
    [[ "$file" =~ $EXT_REGEX ]] || continue

    if grep -qE '[[:space:]]+$' "$file"; then
        echo "Fixing: $file"
        "${SED_CMD[@]}" "$file"
    fi
done
