#!/bin/sh
set -eu
cd "$1"
files=$(find . -type f \( -name '*.py' -o -name '*.sql' \)) || {
    printf 'Cannot enumerate API source files.\n' >&2
    exit 1
}
[ -n "$files" ] || { printf 'API source manifest is empty.\n' >&2; exit 1; }
printf '%s\n' "$files" | while IFS= read -r file; do
    case "$2" in
        shasum) shasum -a 256 "$file" || exit 1;;
        sha256sum) sha256sum "$file" || exit 1;;
        *) printf 'Unsupported hash command.\n' >&2; exit 1;;
    esac
done
