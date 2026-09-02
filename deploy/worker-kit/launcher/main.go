package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
)

type runtimeCompatibility struct {
	HarnessContracts []string `json:"harness_contracts"`
	EventSchemas     []string `json:"event_schemas"`
}

type manifest struct {
	SchemaVersion        int                  `json:"schema_version"`
	ManifestKind         string               `json:"manifest_kind"`
	KitVersion           string               `json:"kit_version"`
	Platform             string               `json:"platform"`
	RuntimeBin           string               `json:"runtime_bin"`
	Bash                 string               `json:"bash"`
	Entrypoint           string               `json:"entrypoint"`
	RuntimeCompatibility runtimeCompatibility `json:"runtime_compatibility"`
	ContentInventory    json.RawMessage       `json:"content_inventory"`
}

type runtimeFile struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

type runtimeAdapter struct {
	Version string `json:"version"`
	Digest  string `json:"digest"`
}

type runtimeManifest struct {
	Schema           string                    `json:"schema"`
	ContractVersion string                    `json:"contract_version"`
	EventSchema     string                    `json:"event_schema"`
	BundleDigest    string                    `json:"bundle_digest"`
	Adapters        map[string]runtimeAdapter `json:"adapters"`
	Files           []runtimeFile             `json:"files"`
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "codify worker-kit launcher: "+format+"\n", args...)
	os.Exit(127)
}

func resolveRuntimePath() string {
	path := os.Getenv("PATH")
	if path == "" {
		return "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
	}
	return path
}

func contains(values []string, wanted string) bool {
	for _, value := range values {
		if value == wanted {
			return true
		}
	}
	return false
}

func fileDigest(path string) (string, int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	hash := sha256.New()
	size, err := io.Copy(hash, file)
	if err != nil {
		return "", 0, err
	}
	return fmt.Sprintf("%x", hash.Sum(nil)), size, nil
}

func verifyKitContent(kitHome, runtimeBin string) {
	verifier := filepath.Join(kitHome, "verify-kit-content.py")
	if _, err := os.Stat(verifier); err != nil {
		fail("Worker Kit content verifier is unavailable: %v", err)
	}
	python, err := exec.LookPath("python3")
	if err != nil {
		python = filepath.Join(runtimeBin, "python3")
	}
	command := exec.Command(python, verifier, "--root", kitHome)
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	if err := command.Run(); err != nil {
		fail("Worker Kit content inventory verification failed")
	}
}

func verifySelectedCLI(kitHome string) {
	path := os.Getenv("CODIFY_HARNESS_CLI_BIN")
	expectedDigest := os.Getenv("CODIFY_CLI_BINARY_DIGEST")
	source := os.Getenv("CODIFY_CLI_SOURCE")
	if path == "" || expectedDigest == "" || source == "" {
		fail("selected Harness CLI identity binding is missing")
	}
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		fail("selected Harness CLI path is not an absolute canonical path")
	}
	info, err := os.Lstat(path)
	if err != nil {
		fail("selected Harness CLI is unavailable: %v", err)
	}
	if source == "worker_kit" {
		relative, err := filepath.Rel(filepath.Clean(kitHome), path)
		if err != nil || relative == "." || filepath.IsAbs(relative) ||
			strings.HasPrefix(relative, ".."+string(os.PathSeparator)) ||
			relative == ".." || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			fail("selected Worker Kit CLI is outside the mounted Kit or is not a regular file")
		}
	} else if source != "host_mount" {
		fail("selected Harness CLI source is unsupported: %s", source)
	}
	if info.Mode()&0111 == 0 {
		fail("selected Harness CLI is not executable")
	}
	actualDigest, _, err := fileDigest(path)
	if err != nil || actualDigest != expectedDigest {
		fail("selected Harness CLI digest mismatch")
	}
}

func verifyRuntimeBundle(kit manifest, allowMissing bool) string {
	runtimeRoot := "/tmp/codify-runtime/orchestration"
	manifestPath := filepath.Join(runtimeRoot, "manifest.json")
	if _, err := os.Stat(manifestPath); os.IsNotExist(err) {
		if allowMissing {
			return kit.Entrypoint
		}
		fail("Task Runtime Bundle manifest is required; legacy Kit fallback is disabled")
	} else if err != nil {
		fail("stat Runtime Bundle manifest: %v", err)
	}
	expectedManifestDigest := os.Getenv("CODIFY_RUNTIME_MANIFEST_DIGEST")
	if expectedManifestDigest == "" || os.Getenv("CODIFY_RUNTIME_BUNDLE_DIGEST") == "" {
		fail("Runtime Bundle digest binding is missing")
	}
	actualManifestDigest, _, err := fileDigest(manifestPath)
	if err != nil || actualManifestDigest != expectedManifestDigest {
		fail("Runtime Bundle manifest digest mismatch")
	}
	raw, err := os.ReadFile(manifestPath)
	if err != nil {
		fail("read Runtime Bundle manifest: %v", err)
	}
	var runtime runtimeManifest
	if err := json.Unmarshal(raw, &runtime); err != nil {
		fail("parse Runtime Bundle manifest: %v", err)
	}
	if !contains(kit.RuntimeCompatibility.HarnessContracts, runtime.ContractVersion) ||
		!contains(kit.RuntimeCompatibility.EventSchemas, runtime.EventSchema) {
		fail("Runtime Bundle contract/event schema is incompatible with this Kit")
	}
	if runtime.Schema != "codify.worker.runtime-bundle/v2" {
		fail("Runtime Bundle manifest is not a codify.worker.runtime-bundle/v2 manifest")
	}
	if runtime.BundleDigest == "" || runtime.BundleDigest != os.Getenv("CODIFY_RUNTIME_BUNDLE_DIGEST") {
		fail("Runtime Bundle digest does not match the Task binding")
	}
	if frozen := os.Getenv("CODIFY_RUNTIME_CONTRACT_VERSION"); frozen != runtime.ContractVersion {
		fail("Runtime Bundle contract mismatch: task=%s bundle=%s", frozen, runtime.ContractVersion)
	}
	harnessKey := os.Getenv("CODIFY_HARNESS_KEY")
	adapter, ok := runtime.Adapters[harnessKey]
	if !ok || adapter.Version == "" || adapter.Digest == "" ||
		adapter.Version != os.Getenv("CODIFY_ADAPTER_VERSION") {
		fail("Runtime Bundle Adapter does not match the Task binding")
	}
	for _, entry := range runtime.Files {
		clean := filepath.Clean(filepath.FromSlash(entry.Path))
		if clean == "." || filepath.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, ".."+string(os.PathSeparator)) {
			fail("unsafe Runtime Bundle path: %s", entry.Path)
		}
		path := filepath.Join(runtimeRoot, clean)
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsRegular() {
			fail("Runtime Bundle file is missing or unsafe: %s", entry.Path)
		}
		digest, size, err := fileDigest(path)
		if err != nil || digest != entry.SHA256 || size != entry.Size {
			fail("Runtime Bundle file digest mismatch: %s", entry.Path)
		}
	}
	entrypoint := filepath.Join(runtimeRoot, "entrypoint.sh")
	if _, err := os.Stat(entrypoint); err != nil {
		fail("Runtime Bundle entrypoint is unavailable: %v", err)
	}
	return entrypoint
}

func main() {
	kitHome := os.Getenv("CODIFY_KIT_HOME")
	if kitHome == "" {
		kitHome = "/opt/codify-kit"
	}
	raw, err := os.ReadFile(filepath.Join(kitHome, "manifest.json"))
	if err != nil {
		fail("read manifest: %v", err)
	}
	var m manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		fail("parse manifest: %v", err)
	}
	if m.SchemaVersion != 2 || m.ManifestKind != "codify.worker.kit-manifest/v1" ||
		m.KitVersion == "" || m.Platform == "" || m.RuntimeBin == "" || m.Bash == "" || m.Entrypoint == "" {
		fail("unsupported or incomplete manifest")
	}
	requestedVersion := os.Getenv("CODIFY_KIT_VERSION")
	if requestedVersion != "" && requestedVersion != m.KitVersion {
		fail("version mismatch: requested %s, mounted %s", requestedVersion, m.KitVersion)
	}
	if m.Platform != runtime.GOOS+"/"+runtime.GOARCH {
		fail("platform mismatch: Kit declares %s, launcher is %s/%s", m.Platform, runtime.GOOS, runtime.GOARCH)
	}
	for _, path := range []string{m.RuntimeBin, m.Bash, m.Entrypoint} {
		if _, err := os.Stat(path); err != nil {
			fail("required path %s is unavailable: %v", path, err)
		}
	}

	runtimePath := resolveRuntimePath()
	os.Setenv("CODIFY_KIT_HOME", kitHome)
	os.Setenv("CODIFY_KIT_VERSION", m.KitVersion)
	os.Setenv("CODIFY_KIT_BIN", m.RuntimeBin)
	os.Setenv("CODIFY_BASH", m.Bash)
	os.Setenv("CODIFY_RUNTIME_PATH", runtimePath+":"+m.RuntimeBin)
	os.Setenv("PATH", m.RuntimeBin+":"+runtimePath)
	os.Setenv("LC_ALL", "C.UTF-8")
	os.Setenv("LANG", "C.UTF-8")
	os.Unsetenv("LANGUAGE")

	verifyOnly := len(os.Args) > 1 && os.Args[1] == "--verify"
	expectedKitManifestDigest := os.Getenv("CODIFY_KIT_MANIFEST_SHA256")
	if expectedKitManifestDigest != "" {
		actualKitManifestDigest, _, err := fileDigest(filepath.Join(kitHome, "manifest.json"))
		if err != nil || actualKitManifestDigest != expectedKitManifestDigest {
			fail("Worker Kit manifest digest mismatch")
		}
	}
	if verifyOnly {
		verifyKitContent(kitHome, m.RuntimeBin)
	} else if expectedKitManifestDigest != "" {
		// Normal V2 execution checks only the selected CLI bytes. The full Kit
		// inventory/Nix closure scan belongs to install-time and --verify admin
		// operations, not the Task startup hot path.
		verifySelectedCLI(kitHome)
	}

	if len(os.Args) > 1 && os.Args[1] == "--maintenance-shell" {
		if len(os.Args) != 3 {
			fail("--maintenance-shell requires exactly one command")
		}
		if err := syscall.Exec(m.Bash, []string{m.Bash, "-c", os.Args[2]}, os.Environ()); err != nil {
			fail("exec maintenance shell: %v", err)
		}
	}

	entrypoint := verifyRuntimeBundle(m, verifyOnly)
	argv := []string{m.Bash, entrypoint}
	argv = append(argv, os.Args[1:]...)
	if err := syscall.Exec(m.Bash, argv, os.Environ()); err != nil {
		fail("exec entrypoint: %v", err)
	}
}
