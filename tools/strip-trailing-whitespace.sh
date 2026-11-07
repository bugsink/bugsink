#!/bin/bash
#
# Strip trailing whitespace from tracked files with specific extensions.
# Usage: ./tools/strip-trailing-whitespace.sh
# Works on macOS (BSD sed) or Linux (GNU sed), but not both at once.

set -euo pipefail

# Extensions to include
EXT_REGEX='\.(py|js|ts|sh|md|txt|html|css|bash|template)$'

# Detect sed flavor
if sed --version >/dev/null 2>&1; then
    SED_CMD=(sed -i -E -e 's/[[:space:]]+$//')
else
    SED_CMD=(sed -i '' -E -e 's/[[:space:]]+$//')
fi

git ls-files -z | while IFS= read -r -d '' file; do
    [[ -f "$file" ]] || continue
    [[ "$file" =~ $EXT_REGEX ]] || continue

    if grep -qE '[[:space:]]+$' "$file"; then
        echo "Fixing: $file"
        "${SED_CMD[@]}" "$file"
    fi
done
