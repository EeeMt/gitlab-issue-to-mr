"""Protocol-specific worker environment construction regressions."""

from types import SimpleNamespace

import pytest

from app.core.worker_runtime import build_container_env


def _settings():
    return SimpleNamespace(
        gitlab_url="https://gitlab.example",
        gitlab_bot_token="token",
        anthropic_base_url="https://legacy.example",
        anthropic_api_key="legacy-key",
        anthropic_model="legacy-model",
        claude_max_turns=10,
        task_timeout=60,
        custom_ca_bundle="",
    )


def _task_issue_provider(protocol: str):
    task = SimpleNamespace(
        id=1,
        project_id=2,
        user_prompt="test",
        initiator_username="tester",
        initiator_display_name=None,
        initiator_email=None,
        worker_profile_id=None,
        task_mode="execute",
        session_mode="fresh",
        input_session_id=None,
        require_changes=True,
    )
    issue = SimpleNamespace(id=3, branch_name="task-3", title="Test", base_branch=None)
    provider = SimpleNamespace(
        id=4,
        model_protocol=protocol,
        api_key="fake-key",
        base_url="https://snapshot.example/v1",
        model="snapshot-model",
        max_turns=11,
        system_prompt=None,
    )
    return task, issue, provider


def test_anthropic_snapshot_emits_no_openai_credentials():
    task, issue, provider = _task_issue_provider("anthropic_messages")
    env = build_container_env(task, issue, None, None, provider, settings=_settings())
    assert env["CODIFY_MODEL_PROTOCOL"] == "anthropic_messages"
    assert env["ANTHROPIC_MODEL"] == "snapshot-model"
    assert not any(key.startswith("OPENAI_") for key in env)


def test_openai_snapshot_emits_no_anthropic_credentials():
    task, issue, provider = _task_issue_provider("openai_responses")
    env = build_container_env(task, issue, None, None, provider, settings=_settings())
    assert env["CODIFY_MODEL_PROTOCOL"] == "openai_responses"
    assert env["OPENAI_MODEL"] == "snapshot-model"
    assert not any(key.startswith("ANTHROPIC_") for key in env)


@pytest.mark.parametrize(
    "protocol,custom_key",
    [
        ("anthropic_messages", "CODIFY_MODEL_PROTOCOL"),
        ("anthropic_messages", "ANTHROPIC_API_KEY"),
        ("anthropic_messages", "OPENAI_MODEL"),
        ("openai_responses", "ANTHROPIC_MODEL"),
        ("openai_responses", "OPENAI_BASE_URL"),
        ("anthropic_messages", "PI_MODEL"),
        ("anthropic_messages", "PI_BASE_URL"),
        ("anthropic_messages", "PI_API_KEY"),
        ("anthropic_messages", "OPENCODE_MODEL"),
        ("anthropic_messages", "OPENCODE_BASE_URL"),
        ("anthropic_messages", "OPENCODE_API_KEY"),
        ("anthropic_messages", "CODIFY_HARNESS_KEY"),
        ("anthropic_messages", "CODIFY_RUNTIME_BUNDLE_DIGEST"),
        ("anthropic_messages", "CODIFY_RUNTIME_CONTRACT_VERSION"),
        ("anthropic_messages", "CODIFY_RUNTIME_EVENT_SCHEMA"),
        ("anthropic_messages", "CODIFY_HARNESS_MODEL_PROTOCOLS"),
        ("anthropic_messages", "CODIFY_HARNESS_CONTROL_TRANSPORT_KIND"),
        ("anthropic_messages", "CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL"),
        ("anthropic_messages", "CODIFY_EVENT_SCHEMA"),
        ("anthropic_messages", "CODIFY_ADAPTER_VERSION"),
        ("anthropic_messages", "CODIFY_ATTEMPT_ID"),
        # The profile/shared environment overlay is merged after the frozen
        # Provider values.  It must also be unable to redirect the selected
        # adapter runner or substitute a CLI/bundle transport input.
        ("anthropic_messages", "CODIFY_HARNESS_COMMAND"),
        ("anthropic_messages", "CODIFY_HARNESS_CLI_BIN"),
        ("anthropic_messages", "CODIFY_HARNESS_MODEL_PROTOCOL"),
        ("anthropic_messages", "CODIFY_CLI_VERSION"),
        ("anthropic_messages", "CODIFY_RUNTIME_PATH"),
        ("anthropic_messages", "CODIFY_PI_BIN"),
        ("anthropic_messages", "CODIFY_OPENCODE_BIN"),
        ("anthropic_messages", "OPENCODE_PROVIDER_NPM"),
        ("anthropic_messages", "PI_HOME"),
        ("anthropic_messages", "CODEX_HOME"),
        ("anthropic_messages", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"),
    ],
)
def test_custom_environment_cannot_override_or_mix_frozen_provider_values(protocol, custom_key):
    task, issue, provider = _task_issue_provider(protocol)
    with pytest.raises(ValueError, match="reserved"):
        build_container_env(
            task,
            issue,
            None,
            None,
            provider,
            custom_environment={custom_key: "custom-value"},
            settings=_settings(),
        )


def test_custom_environment_preserves_uncontrolled_keys():
    task, issue, provider = _task_issue_provider("anthropic_messages")
    env = build_container_env(
        task,
        issue,
        None,
        None,
        provider,
        custom_environment={"CUSTOM_FEATURE_FLAG": "enabled"},
        settings=_settings(),
    )
    assert env["CUSTOM_FEATURE_FLAG"] == "enabled"
