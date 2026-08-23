#!/bin/sh
set -eu

cli="${1:?bridge self-check requires a CLI path}"
case "${cli}" in
    /*) ;;
    *) echo "bridge self-check CLI path must be absolute" >&2; exit 2 ;;
esac
test -x "${cli}"
"${cli}" --version >/dev/null
