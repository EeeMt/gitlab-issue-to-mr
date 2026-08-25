> **RETIRED — 2026-08-25.** This report describes the retired image-owned CLI era.
> Harness CLIs are now owned by the content-addressed Worker Kit (0.4.0+); the
> `make worker-cli-artifact-export` target and `CODIFY_WORKER_CLI_ARTIFACT_MANIFEST`
> binding no longer exist, and this inventory is **not** Kit-owned release evidence
> (see the Open-Harness V2 tracker §4). Kept as historical/audit reference only.
> The image digest below may still be reused as a Project Runtime Image identity
> (toolchain-only) after independent verification, under the new
> `image_identity + kit_identity + bundle_digest` combination.

This is a read-only inventory of the already-present remote-Docker image
`codify-worker/java21-maven:2026.08`. It records no credentials or endpoint
configuration.

It is a **build-input candidate only**, not a release lock and not L3/L4
evidence: this older image does not contain
`/etc/codify-worker-cli-artifacts.json`, predates the current Kit/Runtime
verification implementation, and was not used to run a new Profile or Task.

This is a read-only inventory of the already-present remote-Docker image
`codify-worker/java21-maven:2026.08`. It records no credentials or endpoint
configuration.

It is a **build-input candidate only**, not a release lock and not L3/L4
evidence: this older image does not contain
`/etc/codify-worker-cli-artifacts.json`, predates the current Kit/Runtime
verification implementation, and was not used to run a new Profile or Task.

| Image identity | Platform | Harness | Executable | Version observed | SHA-256 |
|---|---|---|---|---|---|
| `sha256:6a90543639f6f4b2108fb416d1fe3e9e91de368d417b27ce433f5cd6bcb93bc6` | `linux/amd64` | Pi | `/opt/codify-pi/bin/pi` | `0.84.2` | `9a2d20fab3caacbe3517d91e59d495ccc49fd4b51a1a72dcec6e8c1f4b7d6ab2` |
| same | `linux/amd64` | OpenCode | `/opt/codify-opencode/bin/opencode` | `1.18.19` | `fd4cfd76ca65a706d0138886dd23094dd07e35460080024b1467baaf32dcee2e` |
| same | `linux/amd64` | Claude | `/usr/local/bin/claude` | `2.1.153` | `214f603f31942162dac9a65f18d43b3ac646ae215240fad481c4aad6c60f2e38` |
| same | `linux/amd64` | Codex | `/opt/codify-codex/bin/codex` | `0.146.0` | `2e863156ed35ecc5253b1e2f907a9143077b9f7cb51942070c61996471ff6e04` |

To reuse a candidate, the release operator must independently inspect the
staged payload, pass all four SHA values to `make worker-runtime-image-build`,
export a new image-owned lock using `make worker-cli-artifact-export`, and
then set `CODIFY_WORKER_CLI_ARTIFACT_MANIFEST` for both Backend and Scheduler.
The generated lock, not this report, is the only file that may be used by V2
Runtime Bundle binding.
