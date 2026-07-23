# Profile-driven CodeGraph lifecycle.

configure_codegraph() {
    if ! command -v codegraph >/dev/null 2>&1; then
        echo "ERROR: CodeGraph is enabled but the codegraph CLI is not available"
        return 1
    fi

    codify_run_shell 'cd /workspace && export PATH="${CODIFY_RUNTIME_PATH}" && codegraph install --target=claude --location=global --yes'
}

disable_codegraph() {
    if ! command -v codegraph >/dev/null 2>&1; then
        echo "Warning: codegraph CLI is unavailable; skipping Claude config cleanup"
        return 0
    fi

    if ! codify_run_shell 'cd /workspace && export PATH="${CODIFY_RUNTIME_PATH}" && codegraph uninstall --target=claude --location=global --yes'; then
        echo "Warning: could not remove CodeGraph from Claude configuration"
    fi
}

run_codegraph_index() {
    local action="$1"
    local action_label="$2"
    local codegraph_command

    case "${action}" in
        init)
            # CodeGraph 1.1.1's default shimmer renderer writes a new carriage-return
            # frame every 50ms even when stdout is not a TTY. --verbose switches init
            # to its throttled plain-text reporter (phase changes and 5% increments).
            codegraph_command="codegraph init /workspace --verbose"
            ;;
        sync)
            # sync exposes a true non-interactive mode and does not need live detail.
            # CodeGraph 1.1.1 also suppresses its catch-path error under --quiet, so
            # the failure branch below runs a bounded JSON status diagnostic.
            codegraph_command="codegraph sync /workspace --quiet"
            ;;
        *)
            echo "ERROR: unsupported CodeGraph index action: ${action}"
            return 2
            ;;
    esac

    # init --verbose is deliberately visible: unlike the default shimmer animation,
    # it emits bounded phase/percentage updates that are useful in the raw task log.
    # sync --quiet emits no tool progress, leaving only these lifecycle markers.
    if codify_run_shell "cd /workspace && export PATH=\"\${CODIFY_RUNTIME_PATH}\" && ${codegraph_command}"; then
        echo "CodeGraph ${action_label} completed"
        return 0
    else
        local result=$?
        echo "CodeGraph ${action_label} failed with exit code ${result}"
        if [ "${action}" = "sync" ]; then
            echo "CodeGraph sync diagnostic status:"
            if ! codify_run_shell 'cd /workspace && export PATH="${CODIFY_RUNTIME_PATH}" && timeout 15 codegraph status /workspace --json'; then
                echo "Warning: CodeGraph status diagnostic also failed"
            fi
        fi
        return "${result}"
    fi
}

prepare_codegraph() {
    if [ "${CODIFY_CODEGRAPH_ENABLED:-false}" != "true" ]; then
        echo "CodeGraph disabled for this worker profile"
        disable_codegraph
        return 0
    fi

    echo "CodeGraph enabled for this worker profile"
    configure_codegraph

    if [ -d /workspace/.git ]; then
        touch /workspace/.git/info/exclude
        grep -qxF ".codegraph/" /workspace/.git/info/exclude || \
            printf '.codegraph/\n' >> /workspace/.git/info/exclude
        codify_chown /workspace/.git/info/exclude
    fi

    if [ -d /workspace/.codegraph ]; then
        echo "Syncing existing CodeGraph index..."
        run_codegraph_index "sync" "sync"
    else
        echo "Initializing CodeGraph index..."
        run_codegraph_index "init" "initialization"
    fi
}
