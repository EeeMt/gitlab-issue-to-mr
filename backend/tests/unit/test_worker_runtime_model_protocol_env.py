"""Protocol-specific worker environment construction regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.model_credentials import CredentialError
from app.core.model_endpoints import normalize_endpoint
from app.core.worker_runtime import build_container_env, resolve_provider


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
        endpoint_fingerprint="v2:test-endpoint",
        max_turns=11,
        system_prompt=None,
    )
    return task, issue, provider


def test_anthropic_snapshot_emits_no_openai_credentials():
    task, issue, provider = _task_issue_provider("anthropic_messages")
    env = build_container_env(task, issue, None, None, provider, settings=_settings())
    assert env["CODIFY_MODEL_PROTOCOL"] == "anthropic_messages"
    assert env["CODIFY_MODEL_ENDPOINT_FINGERPRINT"] == "v2:test-endpoint"
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
        ("anthropic_messages", "CODIFY_MODEL_ENDPOINT_FINGERPRINT"),
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


def _endpoint_provider(**overrides):
    values = {
        "id": 4,
        "name": "frozen-provider",
        "base_url": "https://snapshot.example/v1",
        "model": "snapshot-model",
        "provider_kind": "openai_compatible",
        "model_protocol": "openai_responses",
        "compat_profile": None,
        "provider_options": {},
        "credential_ref": "cred-frozen",
        "api_key": "live-key",
        "max_turns": 32,
        "system_prompt": "snapshot prompt",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _task_with_endpoint_snapshot(provider):
    endpoint = normalize_endpoint(provider).as_snapshot()
    return SimpleNamespace(
        id=19,
        provider_id=provider.id,
        worker_profile_snapshot=SimpleNamespace(
            runtime_contract_version="codify.worker.harness/v2",
            model_endpoint_snapshot=endpoint,
            credential_ref=provider.credential_ref,
        ),
    )


@pytest.mark.asyncio
async def test_resolve_provider_uses_frozen_endpoint_after_live_endpoint_drift(monkeypatch):
    frozen_provider = _endpoint_provider()
    live_provider = _endpoint_provider(
        base_url="https://changed.example/v1",
        model="changed-model",
        model_protocol="openai_chat_completions",
    )
    task = _task_with_endpoint_snapshot(frozen_provider)
    db = SimpleNamespace(get=AsyncMock(return_value=live_provider))
    credential = AsyncMock(return_value={"secret": "frozen-key", "status": "active"})
    monkeypatch.setattr("app.core.worker_runtime.resolve_task_credential", credential)

    resolved = await resolve_provider(db, task)

    assert resolved.base_url == "https://snapshot.example/v1"
    assert resolved.model == "snapshot-model"
    assert resolved.model_protocol == "openai_responses"
    assert resolved.endpoint_fingerprint == normalize_endpoint(frozen_provider).fingerprint
    assert resolved.api_key == "frozen-key"
    credential.assert_awaited_once_with(db, "cred-frozen", allow_retired=True)


@pytest.mark.asyncio
async def test_resolve_provider_does_not_acquire_credential_added_after_null_snapshot():
    frozen_provider = _endpoint_provider(credential_ref=None, api_key=None)
    live_provider = _endpoint_provider(credential_ref="cred-added-later", api_key="late-key")
    task = _task_with_endpoint_snapshot(frozen_provider)
    db = SimpleNamespace(get=AsyncMock(return_value=live_provider))

    resolved = await resolve_provider(db, task)

    assert resolved.api_key == ""
    assert resolved.credential_ref is None


@pytest.mark.asyncio
async def test_resolve_provider_uses_frozen_endpoint_and_task_credential(monkeypatch):
    frozen_provider = _endpoint_provider(id=None)
    task = _task_with_endpoint_snapshot(frozen_provider)
    task.provider_id = None
    db = SimpleNamespace(get=AsyncMock())
    credential = AsyncMock(
        return_value={"secret": "frozen-key", "status": "retired"}
    )
    monkeypatch.setattr("app.core.worker_runtime.resolve_task_credential", credential)
    monkeypatch.setattr(
        "app.core.worker_runtime.get_settings",
        lambda: SimpleNamespace(claude_max_turns=20),
    )

    resolved = await resolve_provider(db, task)

    assert resolved.id is None
    assert resolved.base_url == "https://snapshot.example/v1"
    assert resolved.model == "snapshot-model"
    assert resolved.model_protocol == "openai_responses"
    assert resolved.api_key == "frozen-key"
    assert resolved.credential_ref == "cred-frozen"
    credential.assert_awaited_once_with(db, "cred-frozen", allow_retired=True)


@pytest.mark.asyncio
async def test_resolve_provider_freezes_max_turns_and_system_prompt(monkeypatch):
    frozen_provider = _endpoint_provider(max_turns=32, system_prompt="frozen prompt")
    live_provider = _endpoint_provider(max_turns=3, system_prompt="changed prompt")
    task, issue, _ = _task_issue_provider("openai_responses")
    task.provider_id = frozen_provider.id
    task.worker_profile_snapshot = _task_with_endpoint_snapshot(
        frozen_provider
    ).worker_profile_snapshot
    db = SimpleNamespace(get=AsyncMock(return_value=live_provider))
    monkeypatch.setattr(
        "app.core.worker_runtime.resolve_task_credential",
        AsyncMock(return_value={"secret": "frozen-key", "status": "active"}),
    )
    monkeypatch.setattr(
        "app.core.worker_runtime.get_settings",
        lambda: SimpleNamespace(claude_max_turns=20),
    )

    resolved = await resolve_provider(db, task)
    env = build_container_env(task, issue, None, None, resolved, settings=_settings())

    assert resolved.max_turns == 32
    assert resolved.system_prompt == "frozen prompt"
    assert env["CLAUDE_MAX_TURNS"] == "32"
    assert env["APPEND_SYSTEM_PROMPT"] == "frozen prompt"


@pytest.mark.asyncio
async def test_resolve_provider_fails_closed_when_frozen_credential_is_revoked(monkeypatch):
    frozen_provider = _endpoint_provider(id=None)
    task = _task_with_endpoint_snapshot(frozen_provider)
    task.provider_id = None
    db = SimpleNamespace(get=AsyncMock())
    monkeypatch.setattr(
        "app.core.worker_runtime.resolve_task_credential",
        AsyncMock(
            side_effect=CredentialError("revoked")
        ),
    )

    with pytest.raises(RuntimeError, match="credential resolution failed"):
        await resolve_provider(db, task)
