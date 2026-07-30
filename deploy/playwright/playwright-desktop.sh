#!/usr/bin/env bash
set -Eeuo pipefail

display="${DISPLAY:-:99}"
geometry="${PLAYWRIGHT_DESKTOP_GEOMETRY:-1920x1080x24}"
web_host="${PLAYWRIGHT_DESKTOP_HOST:-0.0.0.0}"
web_port="${PLAYWRIGHT_DESKTOP_PORT:-6080}"
vnc_port="${PLAYWRIGHT_VNC_PORT:-5900}"
password_file="${PLAYWRIGHT_VNC_PASSWORD_FILE:-}"
runtime_dir="${XDG_RUNTIME_DIR:-/tmp/playwright-runtime-$(id -u)}"
log_dir="${PLAYWRIGHT_DESKTOP_LOG_DIR:-/tmp/playwright-desktop-$(id -u)}"

validate_port() {
    local name="$1"
    local value="$2"
    if [[ ! "${value}" =~ ^[0-9]+$ ]] || ((value < 1 || value > 65535)); then
        echo "${name} must be an integer between 1 and 65535" >&2
        exit 2
    fi
}

validate_port PLAYWRIGHT_DESKTOP_PORT "${web_port}"
validate_port PLAYWRIGHT_VNC_PORT "${vnc_port}"

if [[ ! "${display}" =~ ^:[0-9]+$ ]]; then
    echo "DISPLAY must use the local numeric form, for example :99" >&2
    exit 2
fi
if [[ ! "${geometry}" =~ ^[0-9]+x[0-9]+x(16|24|32)$ ]]; then
    echo "PLAYWRIGHT_DESKTOP_GEOMETRY must look like 1920x1080x24" >&2
    exit 2
fi
if [[ -n "${password_file}" && ! -r "${password_file}" ]]; then
    echo "PLAYWRIGHT_VNC_PASSWORD_FILE is not readable: ${password_file}" >&2
    exit 2
fi

mkdir -p "${runtime_dir}" "${log_dir}"
chmod 0700 "${runtime_dir}"
export DISPLAY="${display}"
export XDG_RUNTIME_DIR="${runtime_dir}"

declare -a child_pids=()

cleanup() {
    local pid
    for pid in "${child_pids[@]:-}"; do
        if kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait_for_path() {
    local path="$1"
    local attempt
    for attempt in {1..100}; do
        [[ -e "${path}" ]] && return 0
        sleep 0.05
    done
    echo "Timed out waiting for ${path}" >&2
    return 1
}

wait_for_tcp() {
    local host="$1"
    local port="$2"
    local name="$3"
    local attempt
    for attempt in {1..100}; do
        nc -z "${host}" "${port}" >/dev/null 2>&1 && return 0
        sleep 0.05
    done
    echo "Timed out waiting for ${name} on ${host}:${port}" >&2
    return 1
}

display_number="${display#:}"
Xvfb "${display}" \
    -screen 0 "${geometry}" \
    -nolisten tcp \
    -ac \
    +extension RANDR \
    >"${log_dir}/xvfb.log" 2>&1 &
child_pids+=("$!")
wait_for_path "/tmp/.X11-unix/X${display_number}"

fluxbox -display "${display}" >"${log_dir}/fluxbox.log" 2>&1 &
child_pids+=("$!")

vnc_auth=(-nopw)
if [[ -n "${password_file}" ]]; then
    vnc_auth=(-rfbauth "${password_file}")
fi
x11vnc \
    -display "${display}" \
    -localhost \
    -rfbport "${vnc_port}" \
    -forever \
    -shared \
    -repeat \
    -xkb \
    "${vnc_auth[@]}" \
    >"${log_dir}/x11vnc.log" 2>&1 &
child_pids+=("$!")
wait_for_tcp 127.0.0.1 "${vnc_port}" x11vnc

websockify \
    --web=/usr/share/novnc \
    "${web_host}:${web_port}" \
    "127.0.0.1:${vnc_port}" \
    >"${log_dir}/websockify.log" 2>&1 &
child_pids+=("$!")
wait_for_tcp 127.0.0.1 "${web_port}" noVNC

echo "Playwright desktop is ready at http://127.0.0.1:${web_port}/vnc.html?autoconnect=1&resize=remote"
echo "Desktop logs: ${log_dir}"

if (($# > 0)); then
    "$@" &
    command_pid="$!"
    child_pids+=("${command_pid}")
    wait "${command_pid}"
else
    xterm -display "${display}" -geometry 160x48 -e /bin/bash -l &
    terminal_pid="$!"
    child_pids+=("${terminal_pid}")
    wait "${terminal_pid}"
fi
