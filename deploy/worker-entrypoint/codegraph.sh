# Profile-driven CodeGraph lifecycle.

configure_codegraph() {
    if ! command -v codegraph >/dev/null 2>&1; then
        echo "ERROR: CodeGraph is enabled but the codegraph CLI is not available"
        return 1
    fi

    env HOME=/home/codify su -m -s /bin/bash codify -c \
        'cd /workspace && codegraph install --target=claude --location=global --yes'
}

disable_codegraph() {
    if ! command -v codegraph >/dev/null 2>&1; then
        echo "Warning: codegraph CLI is unavailable; skipping Claude config cleanup"
        return 0
    fi

    if ! env HOME=/home/codify su -m -s /bin/bash codify -c \
        'cd /workspace && codegraph uninstall --target=claude --location=global --yes'; then
        echo "Warning: could not remove CodeGraph from Claude configuration"
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
        chown codify:codify /workspace/.git/info/exclude
    fi

    if [ -d /workspace/.codegraph ]; then
        echo "Syncing existing CodeGraph index..."
        env HOME=/home/codify su -m -s /bin/bash codify -c \
            'cd /workspace && codegraph sync /workspace'
    else
        echo "Initializing CodeGraph index..."
        env HOME=/home/codify su -m -s /bin/bash codify -c \
            'cd /workspace && codegraph init /workspace'
    fi
}
