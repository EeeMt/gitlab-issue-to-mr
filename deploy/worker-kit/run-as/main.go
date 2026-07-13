package main

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"syscall"
)

func envID(name string, fallback int) int {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	id, err := strconv.Atoi(value)
	if err != nil || id < 0 {
		fmt.Fprintf(os.Stderr, "codify-run-as: invalid %s=%q\n", name, value)
		os.Exit(125)
	}
	return id
}

func main() {
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "--" {
		args = args[1:]
	}
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "usage: codify-run-as -- command [args...]")
		os.Exit(125)
	}
	uid := envID("CODIFY_RUN_UID", 1000)
	gid := envID("CODIFY_RUN_GID", 1000)
	path, err := exec.LookPath(args[0])
	if err != nil {
		fmt.Fprintf(os.Stderr, "codify-run-as: %v\n", err)
		os.Exit(127)
	}
	if err := syscall.Setgroups([]int{gid}); err != nil {
		fmt.Fprintf(os.Stderr, "codify-run-as: setgroups: %v\n", err)
		os.Exit(126)
	}
	if err := syscall.Setgid(gid); err != nil {
		fmt.Fprintf(os.Stderr, "codify-run-as: setgid: %v\n", err)
		os.Exit(126)
	}
	if err := syscall.Setuid(uid); err != nil {
		fmt.Fprintf(os.Stderr, "codify-run-as: setuid: %v\n", err)
		os.Exit(126)
	}
	if err := syscall.Exec(path, args, os.Environ()); err != nil {
		fmt.Fprintf(os.Stderr, "codify-run-as: exec: %v\n", err)
		os.Exit(126)
	}
}
