package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"syscall"
)

type manifest struct {
	SchemaVersion int    `json:"schema_version"`
	KitVersion    string `json:"kit_version"`
	Platform      string `json:"platform"`
	RuntimeBin    string `json:"runtime_bin"`
	Bash          string `json:"bash"`
	Entrypoint    string `json:"entrypoint"`
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
	if m.SchemaVersion != 1 || m.KitVersion == "" || m.RuntimeBin == "" || m.Bash == "" {
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

	argv := []string{m.Bash, m.Entrypoint}
	argv = append(argv, os.Args[1:]...)
	if err := syscall.Exec(m.Bash, argv, os.Environ()); err != nil {
		fail("exec entrypoint: %v", err)
	}
}
