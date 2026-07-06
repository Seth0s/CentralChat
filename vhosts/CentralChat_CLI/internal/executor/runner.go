package executor

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var shellDenyRe = regexp.MustCompile(`(?i)\b(sudo|su\s|runuser|pkexec|curl|wget|ssh|scp|nc\s|netcat|telnet)\b`)

func resolvePath(workspace, path string) (string, error) {
	if strings.Contains(path, "\x00") {
		return "", os.ErrPermission
	}
	root, err := filepath.Abs(workspace)
	if err != nil {
		return "", err
	}
	rootEval, err := filepath.EvalSymlinks(root)
	if err == nil {
		root = rootEval
	}
	p := path
	if !filepath.IsAbs(p) {
		p = filepath.Join(root, p)
	}
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", err
	}
	absEval, err := filepath.EvalSymlinks(abs)
	if err == nil {
		abs = absEval
	}
	rel, err := filepath.Rel(root, abs)
	if err != nil || strings.HasPrefix(rel, "..") {
		return "", os.ErrPermission
	}
	return abs, nil
}

func validateShellCommand(mode string, payload map[string]any) error {
	switch mode {
	case "argv":
		argvRaw, ok := payload["argv"].([]any)
		if !ok || len(argvRaw) == 0 {
			return errors.New("invalid_argv")
		}
		for _, item := range argvRaw {
			s, ok := item.(string)
			if !ok || strings.TrimSpace(s) == "" {
				return errors.New("invalid_argv")
			}
			if shellDenyRe.MatchString(s) {
				return errors.New("shell_command_denied")
			}
		}
	default:
		shC, _ := payload["sh_c"].(string)
		if strings.TrimSpace(shC) == "" {
			return errors.New("empty_sh_c")
		}
		if shellDenyRe.MatchString(shC) {
			return errors.New("shell_command_denied")
		}
	}
	return nil
}

func Execute(actionID string, payload map[string]any, workspace string) (map[string]any, string) {
	switch actionID {
	case "file.read":
		return execRead(payload, workspace)
	case "file.write", "file.patch":
		return execWrite(payload, workspace)
	case "shell.exec":
		return execShell(payload, workspace)
	default:
		return map[string]any{"ok": false, "error": "unsupported_action"}, "failed"
	}
}

func execRead(payload map[string]any, workspace string) (map[string]any, string) {
	path, _ := payload["path"].(string)
	maxBytes := 32768
	if mb, ok := payload["max_bytes"].(float64); ok {
		maxBytes = int(mb)
	}
	abs, err := resolvePath(workspace, path)
	if err != nil {
		return map[string]any{"ok": false, "error": "path_outside_workspace"}, "failed"
	}
	data, err := os.ReadFile(abs)
	if err != nil {
		return map[string]any{"ok": false, "error": err.Error()}, "failed"
	}
	if len(data) > maxBytes {
		data = data[:maxBytes]
	}
	return map[string]any{
		"ok":      true,
		"path":    abs,
		"content": string(data),
	}, "succeeded"
}

func execWrite(payload map[string]any, workspace string) (map[string]any, string) {
	path, _ := payload["path"].(string)
	content, _ := payload["content"].(string)
	if content == "" {
		if nc, ok := payload["new_content"].(string); ok {
			content = nc
		}
	}
	abs, err := resolvePath(workspace, path)
	if err != nil {
		return map[string]any{"ok": false, "error": "path_outside_workspace"}, "failed"
	}
	if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil && !os.IsExist(err) {
		return map[string]any{"ok": false, "error": err.Error()}, "failed"
	}
	if err := os.WriteFile(abs, []byte(content), 0o644); err != nil {
		return map[string]any{"ok": false, "error": err.Error()}, "failed"
	}
	return map[string]any{"ok": true, "path": abs, "bytes_written": len(content)}, "succeeded"
}

func execShell(payload map[string]any, workspace string) (map[string]any, string) {
	mode, _ := payload["mode"].(string)
	if mode == "" {
		mode = "sh_c"
	}

	timeoutSec := 120
	if t, ok := payload["timeout_sec"].(float64); ok {
		timeoutSec = int(t)
	}
	if timeoutSec < 1 {
		timeoutSec = 1
	}
	if timeoutSec > 600 {
		timeoutSec = 600
	}

	cwd, _ := payload["cwd"].(string)
	if strings.TrimSpace(cwd) == "" {
		cwd = workspace
	}
	absCwd, err := resolvePath(workspace, cwd)
	if err != nil {
		return map[string]any{"ok": false, "error": "cwd_outside_workspace"}, "failed"
	}

	if err := validateShellCommand(mode, payload); err != nil {
		return map[string]any{"ok": false, "error": err.Error()}, "failed"
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeoutSec)*time.Second)
	defer cancel()

	var cmd *exec.Cmd
	switch mode {
	case "argv":
		argvRaw, ok := payload["argv"].([]any)
		if !ok || len(argvRaw) == 0 {
			return map[string]any{"ok": false, "error": "invalid_argv"}, "failed"
		}
		parts := make([]string, 0, len(argvRaw))
		for _, item := range argvRaw {
			s, ok := item.(string)
			if !ok || strings.TrimSpace(s) == "" {
				return map[string]any{"ok": false, "error": "invalid_argv"}, "failed"
			}
			parts = append(parts, s)
		}
		cmd = exec.CommandContext(ctx, parts[0], parts[1:]...)
	default:
		shC, _ := payload["sh_c"].(string)
		if strings.TrimSpace(shC) == "" {
			return map[string]any{"ok": false, "error": "empty_sh_c"}, "failed"
		}
		cmd = exec.CommandContext(ctx, "sh", "-c", shC)
	}

	cmd.Dir = absCwd
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	runErr := cmd.Run()
	exitCode := 0
	if runErr != nil {
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			exitCode = exitErr.ExitCode()
		} else if ctx.Err() == context.DeadlineExceeded {
			return map[string]any{
				"ok":          false,
				"error":       "timeout",
				"timeout_sec": timeoutSec,
				"cwd":         absCwd,
			}, "failed"
		} else {
			return map[string]any{"ok": false, "error": runErr.Error(), "cwd": absCwd}, "failed"
		}
	}

	out := map[string]any{
		"ok":        exitCode == 0,
		"exit_code": exitCode,
		"stdout":    truncate(stdout.String(), 50000),
		"stderr":    truncate(stderr.String(), 20000),
		"cwd":       absCwd,
		"command":   commandPreview(mode, payload),
	}
	if exitCode != 0 {
		out["error"] = fmt.Sprintf("exit_code_%d", exitCode)
	}
	return out, "succeeded"
}

func truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max]
}

func commandPreview(mode string, payload map[string]any) string {
	if mode == "argv" {
		argvRaw, _ := payload["argv"].([]any)
		parts := make([]string, 0, len(argvRaw))
		for _, item := range argvRaw {
			if s, ok := item.(string); ok {
				parts = append(parts, s)
			}
		}
		return strings.Join(parts, " ")
	}
	shC, _ := payload["sh_c"].(string)
	return strings.TrimSpace(shC)
}
