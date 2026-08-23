# Open-Harness V2 probe scripts

These scripts consolidate the local WP0 experiments into a small, repeatable
surface. They are evidence helpers, not a second Harness implementation: all
full-chain execution delegates initialization and adapter selection to the
frozen `worker-entrypoint/harness/runner.sh`.

Credentials must be injected by the caller. No script reads Codify's database,
`deploy/.env.test`, a credential file, or a key dump; no script prints model
output, request bodies, response bodies, or environment values.

## Commands

```bash
python3 scripts/harness-probes/v2/provider-matrix.py --base-url https://provider.example --model example --dry-run
PROBE_API_KEY="${PROBE_API_KEY:?inject from a protected environment}" python3 scripts/harness-probes/v2/provider-matrix.py --base-url https://provider.example --model example
scripts/harness-probes/v2/full-chain-driver.sh --harness pi --prompt /tmp/prompt.md
scripts/harness-probes/v2/pi-rpc-sequence.sh --pi-bin /opt/codify-pi/bin/pi
scripts/harness-probes/v2/resume.sh --harness pi --output-dir /tmp/v2-resume
scripts/harness-probes/v2/recall.sh --harness pi --output-dir /tmp/v2-recall
scripts/harness-probes/v2/benchmark.sh --harness pi --output-dir /tmp/v2-benchmark --count 20
python3 scripts/harness-probes/v2/secret-scan.py
python3 scripts/harness-probes/v2/secret-scan.py --staged
```

`resume.sh` verifies protocol-level continuation. `recall.sh` separately asks
the model to recall a turn-one marker; passing the former does not establish the
latter. `benchmark.sh` records only index and process status in `summary.tsv`.

## Safety and evidence rules

- Never put real credentials in shell history, command arguments, prompts,
  fixtures, logs, reports, or `--base-url` user-info/query fields.
- Do not commit a run archive. Preserve a formal canary only after redaction in
  `docs/harness-probes/v2/acceptance/` with Bundle/image/Kit digests and task IDs.
- `provider-matrix.py` establishes endpoint behaviour only. It does **not**
  prove Harness protocol support, configuration selection, or acceptance.
- The direct Pi RPC probe is diagnostic. Release evidence remains the
  common-runner full chain and later real-Host/canary checks.
