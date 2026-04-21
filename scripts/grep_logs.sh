#!/bin/bash
# 按 Trace ID 查询日志

TRACE_ID=$1
LOG_DIR="logs"
DATE=${2:-$(date +%Y-%m-%d)}

if [ -z "$TRACE_ID" ]; then
    echo "用法: $0 <trace_id> [日期]"
    echo "示例: $0 a1b2c3d4 2026-04-01"
    exit 1
fi

LOG_FILE="${LOG_DIR}/app_${DATE}.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "日志文件不存在: $LOG_FILE"
    exit 1
fi

echo "=== Trace ID: $TRACE_ID | 日期: $DATE ==="
grep "$TRACE_ID" "$LOG_FILE" | jq '.' 2>/dev/null || grep "$TRACE_ID" "$LOG_FILE"
