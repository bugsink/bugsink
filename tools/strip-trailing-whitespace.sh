#!/bin/bash
#
# Strip trailing whitespace from tracked files with specific extensions.
# Usage: ./tools/strip-trailing-whitespace.sh

set -euo pipefail

# Extensions to include
EXT_REGEX='\.(py|js|ts|sh|md|txt|html|css|bash|template)$'

whitespace_tmp=$(mktemp)
trap 'rm -f "$whitespace_tmp"' EXIT

git ls-files -z | while IFS= read -r -d '' file; do
    [[ -f "$file" ]] || continue
    [[ "$file" =~ $EXT_REGEX ]] || continue

    if grep -qE '[[:space:]]+$' "$file"; then
        echo "Fixing: $file"
        sed 's/[[:space:]]*$//' "$file" > "$whitespace_tmp"
        cat "$whitespace_tmp" > "$file"
    fi
done
