package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

type runtimeCompatibility struct {
	HarnessContracts []string `json:"harness_contracts"`
	EventSchemas     []string `json:"event_schemas"`
}

type manifest struct {
	SchemaVersion        int                  `json:"schema_version"`
	KitVersion           string               `json:"kit_version"`
	Platform             string               `json:"platform"`
	RuntimeBin           string               `json:"runtime_bin"`
	Bash                 string               `json:"bash"`
	Entrypoint           string               `json:"entrypoint"`
	RuntimeCompatibility runtimeCompatibility `json:"runtime_compatibility"`
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
	ContractVersion string                    `json:"contract_version"`
	EventSchema     string                    `json:"event_schema"`
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
	if m.SchemaVersion != 2 || m.KitVersion == "" || m.RuntimeBin == "" || m.Bash == "" || m.Entrypoint == "" {
		fail("unsupported or incomplete manifest")
	}
	requestedVersion := os.Getenv("CODIFY_KIT_VERSION")
	if requestedVersion != "" && requestedVersion != m.KitVersion {
		fail("version mismatch: requested %s, mounted %s", requestedVersion, m.KitVersion)
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

	if len(os.Args) > 1 && os.Args[1] == "--maintenance-shell" {
		if len(os.Args) != 3 {
			fail("--maintenance-shell requires exactly one command")
		}
		if err := syscall.Exec(m.Bash, []string{m.Bash, "-c", os.Args[2]}, os.Environ()); err != nil {
			fail("exec maintenance shell: %v", err)
		}
	}

	verifyOnly := len(os.Args) > 1 && os.Args[1] == "--verify"
	entrypoint := verifyRuntimeBundle(m, verifyOnly)
	argv := []string{m.Bash, entrypoint}
	argv = append(argv, os.Args[1:]...)
	if err := syscall.Exec(m.Bash, argv, os.Environ()); err != nil {
		fail("exec entrypoint: %v", err)
	}
}
