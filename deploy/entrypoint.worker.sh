#!/bin/bash
set -e

# Keep the image entrypoint stable and load implementation modules in lifecycle order.
ENTRYPOINT_LIB_DIR="/opt/codify/worker-entrypoint"

for module in \
    bootstrap \
    gitlab \
    delivery \
    task-environment \
    codegraph \
    runtime \
    main
do
    module_path="${ENTRYPOINT_LIB_DIR}/${module}.sh"
    if [ ! -r "${module_path}" ]; then
        echo "Worker entrypoint module is missing or unreadable: ${module_path}" >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    source "${module_path}"
done
