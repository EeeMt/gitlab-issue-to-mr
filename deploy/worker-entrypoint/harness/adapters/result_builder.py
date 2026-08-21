"""Shared ``codify.worker.result`` envelope helpers for all Harness adapters.

The result envelope and the canonical event envelope must agree on the harness
identity (``key``/``adapter_version``/``cli_version`` and, under V2, the control
transport and model protocols): events.py rejects any identity change inside a
single canonical attempt, so the archived result block is built from exactly the
same exported variables events.py reads. Kept here so every adapter writer
produces a byte-identical harness block without duplicating the logic.
"""

from __future__ import annotations

import os

V2_CONTRACT = "codify.worker.harness/v2"
RESULT_SCHEMA_V1 = "codify.worker.result/v1"
RESULT_SCHEMA_V2 = "codify.worker.result/v2"


def is_v2_contract() -> bool:
    return os.environ.get("CODIFY_RUNTIME_CONTRACT_VERSION", "") == V2_CONTRACT


def result_schema() -> str:
    """Result schema matches the active runtime contract (v1 default, v2 once flipped)."""
    return RESULT_SCHEMA_V2 if is_v2_contract() else RESULT_SCHEMA_V1


def harness_identity() -> dict:
    """The harness block carried by the result envelope.

    Under V2 the block is nested (``key``/``adapter_version``/``cli_version`` plus
    ``control_transport``/``model_protocols``), mirroring the event envelope so
    ``validate_result_v2`` accepts it. Under V1 the caller serializes the three
    base fields flat (V1 has no nested harness block), matching the historical
    shape ``validate_result`` expects.
    """
    return {
        "key": os.environ.get("CODIFY_HARNESS_KEY", ""),
        "adapter_version": os.environ.get("CODIFY_ADAPTER_VERSION", "1.0.0"),
        "cli_version": os.environ.get("CODIFY_CLI_VERSION", "unknown"),
    }


def v2_harness_block() -> dict:
    """Full nested V2 harness block, byte-identical to the event envelope's."""
    block = harness_identity()
    block["control_transport"] = {
        "kind": os.environ.get("CODIFY_HARNESS_CONTROL_TRANSPORT_KIND", "rpc_stdio"),
        "protocol": os.environ.get("CODIFY_HARNESS_CONTROL_TRANSPORT_PROTOCOL"),
    }
    protocols = os.environ.get("CODIFY_HARNESS_MODEL_PROTOCOLS", "")
    block["model_protocols"] = [p for p in protocols.split(",") if p.strip()] or [
        os.environ.get("CODIFY_HARNESS_MODEL_PROTOCOL", "anthropic_messages")
    ]
    return block
