# Delivery-summary validation, prompts, metadata, and MR-description helpers.

sanitize_summary_content() {
    local summary_text="$1"

    printf '%s\n' "${summary_text}" | awk '
        BEGIN { skip = 0 }
        /^## 执行摘要[[:space:]]*$/ { next }
        /^### 修改的文件[[:space:]]*$/ { skip = 1; next }
        /^### / {
            if (skip == 1) {
                skip = 0
            }
        }
        skip == 1 { next }
        /未跟踪/ { next }
        /可按需提交/ { next }
        { print }
    '
}

normalize_delivery_summary_response() {
    local raw_summary="$1"

    printf '%s' "${raw_summary}" | python3 -c 'import re, sys; text = sys.stdin.read(); text = re.sub(r"\r$", "", text, flags=re.MULTILINE); text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL); text = re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE); text = re.sub(r"^```(?:markdown)?\s*", "", text.strip(), flags=re.IGNORECASE); text = re.sub(r"\s*```$", "", text).strip(); print(text, end="")'
}

annotate_delivery_summary_validation() {
    local attempts="$1"
    local repaired="$2"

    if [ ! -f "${DELIVERY_SUMMARY_VALIDATION_FILE}" ]; then
        return 0
    fi

    local tmp_file="${DELIVERY_SUMMARY_VALIDATION_FILE}.tmp"
    jq \
        --argjson attempts "${attempts}" \
        --argjson repaired "${repaired}" \
        '. + {repairAttempts: $attempts, repaired: $repaired}' \
        "${DELIVERY_SUMMARY_VALIDATION_FILE}" > "${tmp_file}" 2>/dev/null && mv "${tmp_file}" "${DELIVERY_SUMMARY_VALIDATION_FILE}" || rm -f "${tmp_file}"
}

run_mermaid_summary_validation() {
    local summary_file="$1"
    local output_file="$2"
    local validator="${CODIFY_MERMAID_VALIDATOR}"

    if [ "${MERMAID_SUMMARY_VALIDATE}" != "true" ]; then
        jq -nc '{ok: true, diagramCount: 0, errors: [], skipped: true, reason: "disabled"}' > "${output_file}"
        return 0
    fi

    if [ ! -x "${validator}" ]; then
        jq -nc '{ok: false, diagramCount: 0, errors: [{index: null, message: "Mermaid validator unavailable", source: ""}], skipped: true, reason: "validator_unavailable"}' > "${output_file}"
        return 1
    fi

    local tmp_file="${output_file}.tmp"
    local err_file="${output_file}.stderr"
    set +e
    "${validator}" "${summary_file}" > "${tmp_file}" 2> "${err_file}"
    local validation_status=$?
    set -e

    if [ ${validation_status} -ne 0 ]; then
        local validator_error
        validator_error="$(cat "${err_file}" 2>/dev/null || true)"
        jq -nc \
            --arg message "${validator_error:-Mermaid validator failed}" \
            '{ok: false, diagramCount: 0, errors: [{index: null, message: $message, source: ""}], validatorError: $message}' \
            > "${output_file}"
        rm -f "${tmp_file}" "${err_file}"
        return 1
    fi

    mv "${tmp_file}" "${output_file}"
    rm -f "${err_file}"
    jq -e '.ok == true' "${output_file}" >/dev/null 2>&1
}

build_mermaid_repair_prompt() {
    local summary_file="$1"
    local validation_file="$2"
    local prompt_file="$3"

    {
        printf '%s\n' '下面是一段 Codify 最终交付摘要，其中 Mermaid 图表无法渲染。'
        printf '%s\n' '请只修复 Markdown 中的 mermaid fenced code block，保留其它文字和业务结论。'
        printf '%s\n' '不要调用工具，不要修改文件，不要添加解释、标题或前后缀；只输出修复后的完整 Markdown 摘要。'
        printf '\n%s\n' 'Mermaid 校验错误 JSON：'
        cat "${validation_file}"
        printf '\n%s\n' '原始交付摘要：'
        cat "${summary_file}"
    } > "${prompt_file}"
}

prepare_delivery_summary() {
    local raw_summary="$1"
    local current_summary
    current_summary="$(normalize_delivery_summary_response "${raw_summary}")"

    local summary_check_file="/tmp/delivery-summary-check.md"
    local repair_prompt_file="/tmp/delivery-summary-repair-prompt.md"
    local attempts=0
    local repaired=false

    printf '%s' "${current_summary}" > "${summary_check_file}"
    if run_mermaid_summary_validation "${summary_check_file}" "${DELIVERY_SUMMARY_VALIDATION_FILE}"; then
        echo "Delivery summary Mermaid validation passed" >&2
        annotate_delivery_summary_validation "${attempts}" "${repaired}"
        printf '%s' "${current_summary}"
        return 0
    fi

    local diagram_count error_count
    diagram_count="$(jq -r '.diagramCount // 0' "${DELIVERY_SUMMARY_VALIDATION_FILE}" 2>/dev/null || echo 0)"
    error_count="$(jq -r '(.errors // []) | length' "${DELIVERY_SUMMARY_VALIDATION_FILE}" 2>/dev/null || echo 0)"
    echo "Delivery summary Mermaid validation failed (diagrams=${diagram_count}, errors=${error_count})" >&2

    while [ "${attempts}" -lt "${MERMAID_SUMMARY_REPAIR_ATTEMPTS}" ]; do
        attempts=$((attempts + 1))
        echo "Repairing delivery summary Mermaid diagrams (attempt ${attempts}/${MERMAID_SUMMARY_REPAIR_ATTEMPTS})" >&2
        build_mermaid_repair_prompt "${summary_check_file}" "${DELIVERY_SUMMARY_VALIDATION_FILE}" "${repair_prompt_file}"

        set +e
        local repaired_summary
        repaired_summary=$(codify_harness_run_text /tmp/delivery-summary-repair-prompt.md 60 2>/dev/null)
        local repair_status=$?
        set -e

        if [ ${repair_status} -ne 0 ]; then
            echo "Delivery summary Mermaid repair failed with exit code ${repair_status}" >&2
            continue
        fi

        repaired_summary="$(normalize_delivery_summary_response "${repaired_summary}")"
        if [ -z "${repaired_summary}" ]; then
            echo "Delivery summary Mermaid repair returned empty output" >&2
            continue
        fi

        current_summary="${repaired_summary}"
        printf '%s' "${current_summary}" > "${summary_check_file}"
        if run_mermaid_summary_validation "${summary_check_file}" "${DELIVERY_SUMMARY_VALIDATION_FILE}"; then
            echo "Delivery summary Mermaid repair succeeded" >&2
            repaired=true
            annotate_delivery_summary_validation "${attempts}" "${repaired}"
            printf '%s' "${current_summary}"
            return 0
        fi
    done

    echo "Delivery summary Mermaid validation still failed after ${attempts} repair attempt(s)" >&2
    annotate_delivery_summary_validation "${attempts}" "${repaired}"
    if [ "${MERMAID_SUMMARY_STRICT}" = "true" ]; then
        return 1
    fi

    printf '%s' "${current_summary}"
}

write_delivery_summary_artifacts() {
    local summary_text="$1"

    printf '%s\n' "${summary_text}" > "${DELIVERY_SUMMARY_FILE}"
    chmod 644 "${DELIVERY_SUMMARY_FILE}" "${DELIVERY_SUMMARY_VALIDATION_FILE}" 2>/dev/null || true
    codify_chown "${DELIVERY_SUMMARY_FILE}" "${DELIVERY_SUMMARY_VALIDATION_FILE}" 2>/dev/null || true
    echo "Delivery summary written to ${DELIVERY_SUMMARY_FILE} (${#summary_text} chars)"
}

write_plan_task_metadata() {
    local summary_text="$1"
    local summary_truncated="${summary_text:0:3000}"
    local task_metadata

    task_metadata=$(jq -nc \
        --argjson task_id "${TASK_ID:-0}" \
        --arg prompt "${USER_PROMPT:-}" \
        --arg execution_summary "${summary_truncated}" \
        --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{
            task_id: $task_id,
            prompt: $prompt,
            commit_sha: "",
            commit_message: "",
            overall_summary: "",
            execution_summary: $execution_summary,
            new_files: [],
            modified_files: [],
            deleted_files: [],
            additions: 0,
            deletions: 0,
            timestamp: $timestamp
        }')
    printf '%s\n' "${task_metadata}" > "${CODIFY_RUNTIME_DIR}/task-metadata.json"
    chmod 644 "${CODIFY_RUNTIME_DIR}/task-metadata.json" 2>/dev/null || true
    codify_chown "${CODIFY_RUNTIME_DIR}/task-metadata.json" 2>/dev/null || true
    echo "Plan task metadata written to ${CODIFY_RUNTIME_DIR}/task-metadata.json"
}

describe_file_path() {
    local filepath="$1"

    case "${filepath}" in
        .gitignore)
            printf '%s' "Git 忽略规则配置"
            ;;
        pom.xml)
            printf '%s' "Maven 项目配置"
            ;;
        src/main/java/*.java)
            printf '%s' "Java 示例或业务源码"
            ;;
        src/main/resources/*)
            printf '%s' "项目运行资源配置"
            ;;
        src/test/*)
            printf '%s' "测试代码"
            ;;
        *.md)
            printf '%s' "文档说明"
            ;;
        *)
            printf '%s' "本次改动涉及的文件"
            ;;
    esac
}

extract_file_description_from_summary() {
    local filepath="$1"
    local summary_text="$2"
    local line=""

    line=$(printf '%s\n' "${summary_text}" | grep -F "**${filepath}** -" | head -1 || true)
    if [ -n "${line}" ]; then
        printf '%s\n' "${line}" | sed -E 's/^[0-9]+[.)]?[[:space:]]*\*\*[^*]+\*\*[[:space:]]*-[[:space:]]*//'
        return 0
    fi

    describe_file_path "${filepath}"
}

append_changed_file_rows() {
    local change_type="$1"
    local csv_files="$2"
    local summary_text="$3"

    if [ -z "${csv_files}" ]; then
        return 0
    fi

    local old_ifs="${IFS}"
    IFS=','
    read -ra files <<< "${csv_files}"
    IFS="${old_ifs}"

    local filepath=""
    for filepath in "${files[@]}"; do
        [ -z "${filepath}" ] && continue
        printf '| %s | `%s` | %s |\n' \
            "${change_type}" \
            "${filepath}" \
            "$(extract_file_description_from_summary "${filepath}" "${summary_text}")"
    done
}

build_changed_files_table() {
    local new_files="$1"
    local modified_files="$2"
    local deleted_files="$3"
    local summary_text="$4"
    local rows=""

    rows+=$(append_changed_file_rows "新增" "${new_files}" "${summary_text}")
    rows+=$(append_changed_file_rows "修改" "${modified_files}" "${summary_text}")
    rows+=$(append_changed_file_rows "删除" "${deleted_files}" "${summary_text}")

    if [ -z "${rows}" ]; then
        rows='| 无 | 无 | 无 |'
    fi

    cat <<EOF
| 类型 | 文件 | 说明 |
| --- | --- | --- |
${rows}
EOF
}

build_completed_mr_description() {
    local summary_text="$1"
    local changed_files_text="$2"
    cat <<EOF
## ✅ AI 执行完成

### 需求
${USER_PROMPT}

### 涉及文件
${changed_files_text}

### 执行摘要
${summary_text}
$(build_issue_reference_block)
EOF
}

build_commit_message_prompt() {
    local changed_files_text="$1"
    local diff_stats_text="$2"
    local summary_text="$3"
    cat <<EOF
根据下面的信息，直接输出一条 Conventional Commits 规范的 git commit message。

重要：直接输出 commit message 本身，第一个字符必须是 type（如 feat:、fix: 等），不要有任何前言、解释或说明文字。

格式：
1. 使用中文。
2. 第一行格式：<type>: <description>
3. type 从 feat、fix、refactor、docs、test、build、chore、ci 中选择。
4. description 简洁明确，控制在 50 字符内。
5. 如需正文，subject 后空一行，用 1-3 行简短说明。
6. 最后添加 footer：AI-Generated: true
7. 不要使用 markdown、代码块、引号，不要包含 Co-authored-by。

用户需求：
${USER_PROMPT}

改动文件：
${changed_files_text}

Diff 统计：
${diff_stats_text}

执行摘要：
${summary_text}
EOF
}

normalize_model_commit_message() {
    local raw_message="$1"

    printf '%s' "${raw_message}" | python3 -c 'import re, sys; text = sys.stdin.read(); text = re.sub(r"\r$", "", text, flags=re.MULTILINE); text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL); text = re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE); print(text.strip(), end="")'
}

build_overall_summary_prompt() {
    local previous_summary_file="$1"
    local current_summary_text="$2"
    local commit_message_text="$3"
    local diff_stats_text="$4"
    local current_user_prompt="$5"
    local previous_summary_text="暂无前序任务摘要。"

    if [ -f "${previous_summary_file}" ]; then
        previous_summary_text="$(cat "${previous_summary_file}")"
    fi

    cat <<EOF
请基于同一个 GitLab MR 下的前序任务摘要和当前任务执行结果，生成一个真正的跨任务总体总结。

要求：
1. 使用中文。
2. 只总结整体目标、最终完成的核心结果、当前状态和验证情况。
3. 不要逐个复述每个 Task，不要输出文件清单，不要重复 MR Changes 页可看到的 diff 信息。
4. 控制在 3-6 条要点，使用 Markdown bullet list。
5. 不要添加标题、前言、结束语或代码块。

前序任务摘要：
${previous_summary_text}

当前任务需求：
${current_user_prompt}

当前任务提交说明：
${commit_message_text}

当前任务 Diff 统计：
${diff_stats_text}

当前任务执行摘要：
${current_summary_text}
EOF
}

normalize_model_overall_summary() {
    local raw_summary="$1"

    printf '%s' "${raw_summary}" | python3 -c 'import re, sys; text = sys.stdin.read(); text = re.sub(r"\r$", "", text, flags=re.MULTILINE); text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL); text = re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE); text = re.sub(r"^```(?:markdown)?\s*", "", text.strip(), flags=re.IGNORECASE); text = re.sub(r"\s*```$", "", text).strip(); text = text.replace("</details>", "&lt;/details&gt;"); print((text[:2000].rstrip() + "...") if len(text) > 2000 else text, end="")'
}
