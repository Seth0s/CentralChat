// Package solo — policy enforcement for SOLO mode.
package solo

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"gopkg.in/yaml.v3"
)

// ── Policy ─────────────────────────────────────────────────────

type Policy struct {
	// DenyPaths are glob patterns that tools cannot access.
	DenyPaths []string `yaml:"deny_paths"`

	// AllowWritePaths are glob patterns where writes are allowed without confirmation.
	AllowWritePaths []string `yaml:"allow_write_paths"`

	// DenyCommands are regex patterns for shell commands that are blocked.
	DenyCommands []string `yaml:"deny_commands"`

	// RequireConfirmationFor lists tool names that need user approval.
	RequireConfirmationFor []string `yaml:"require_confirmation_for"`

	// MaxFileSizeBytes is the max bytes for read_file.
	MaxFileSizeBytes int64 `yaml:"max_file_size_bytes"`

	// MaxShellTimeoutSec is the max seconds for terminal.
	MaxShellTimeoutSec int `yaml:"max_shell_timeout_sec"`
}

// DefaultPolicy returns sensible safe defaults.
func DefaultPolicy() *Policy {
	return &Policy{
		DenyPaths: []string{
			"**/.env",
			"**/.env.*",
			"**/credentials*",
			"**/secrets*",
			"**/*.pem",
			"**/*.key",
			"**/.git/**",
			"**/node_modules/**",
			"**/__pycache__/**",
			"**/.central/**",
		},
		AllowWritePaths: []string{
			"src/**",
			"lib/**",
			"*.go",
			"*.py",
			"*.ts",
			"*.tsx",
			"*.js",
			"*.md",
			"*.yaml",
			"*.yml",
			"*.toml",
			"*.json",
			"*.css",
			"*.html",
		},
		DenyCommands: []string{
			`sudo\b`, `su\b`, `runuser\b`, `pkexec\b`,
			`rm\s+-rf\s+/`, `:(){ :|:& };:`, `mkfs\.`,
			`dd\s+if=`, `>/\dev/sd`,
		},
		RequireConfirmationFor: []string{
			"write_file",
			"patch",
			"terminal",
		},
		MaxFileSizeBytes:  1_000_000, // 1MB
		MaxShellTimeoutSec: 120,
	}
}

// LoadPolicy reads policy.yaml from the config directory.
func LoadPolicy() (*Policy, error) {
	dir, err := configDir()
	if err != nil {
		return DefaultPolicy(), nil
	}
	path := filepath.Join(dir, "policy.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return DefaultPolicy(), nil
		}
		return nil, err
	}
	var p Policy
	if err := yaml.Unmarshal(data, &p); err != nil {
		return nil, fmt.Errorf("policy.yaml: %w", err)
	}
	// Merge with defaults: user config adds to / overrides defaults
	defaults := DefaultPolicy()
	if len(p.DenyPaths) == 0 {
		p.DenyPaths = defaults.DenyPaths
	}
	if len(p.DenyCommands) == 0 {
		p.DenyCommands = defaults.DenyCommands
	}
	if len(p.RequireConfirmationFor) == 0 {
		p.RequireConfirmationFor = defaults.RequireConfirmationFor
	}
	if p.MaxFileSizeBytes == 0 {
		p.MaxFileSizeBytes = defaults.MaxFileSizeBytes
	}
	if p.MaxShellTimeoutSec == 0 {
		p.MaxShellTimeoutSec = defaults.MaxShellTimeoutSec
	}
	return &p, nil
}

// configDir is the internal helper (avoids import cycle with config package).
func configDir() (string, error) {
	base, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(base, "central"), nil
}

// ── Enforcement ─────────────────────────────────────────────────

// PolicyResult is the outcome of a policy check.
type PolicyResult struct {
	Allowed           bool
	RequiresApproval  bool
	Reason            string
}

// CheckReadPolicy verifies that reading a path is allowed.
func (p *Policy) CheckReadPath(absPath, workspace string) *PolicyResult {
	// Resolve relative path
	rel, err := filepath.Rel(workspace, absPath)
	if err != nil || strings.HasPrefix(rel, "..") {
		return &PolicyResult{Allowed: false, Reason: "path outside workspace"}
	}

	// Check deny patterns
	for _, pattern := range p.DenyPaths {
		matched, _ := filepath.Match(pattern, rel)
		if !matched {
			// Try with ** prefix
			matched, _ = filepath.Match(pattern, filepath.Base(rel))
		}
		if matched {
			return &PolicyResult{Allowed: false, Reason: fmt.Sprintf("path denied by policy: %s", pattern)}
		}
	}

	// Check file size
	if p.MaxFileSizeBytes > 0 {
		info, err := os.Stat(absPath)
		if err == nil && info.Size() > p.MaxFileSizeBytes {
			return &PolicyResult{Allowed: false, Reason: fmt.Sprintf("file too large (%d > %d bytes)", info.Size(), p.MaxFileSizeBytes)}
		}
	}

	return &PolicyResult{Allowed: true}
}

// CheckWritePolicy verifies that writing to a path is allowed.
func (p *Policy) CheckWritePath(absPath, workspace string) *PolicyResult {
	// Same deny check as read
	result := p.CheckReadPath(absPath, workspace)
	if !result.Allowed {
		return result
	}

	rel, _ := filepath.Rel(workspace, absPath)

	// Check if write needs confirmation
	needsConfirm := true
	for _, pattern := range p.AllowWritePaths {
		matched, _ := filepath.Match(pattern, rel)
		if !matched {
			matched, _ = filepath.Match(pattern, filepath.Base(rel))
		}
		if matched {
			needsConfirm = false
			break
		}
	}

	requiresApproval := false
	for _, tool := range p.RequireConfirmationFor {
		if tool == "write_file" || tool == "patch" {
			requiresApproval = needsConfirm
		}
	}

	return &PolicyResult{Allowed: true, RequiresApproval: requiresApproval}
}

// CheckShellCommand verifies a shell command against the deny list.
func (p *Policy) CheckShellCommand(command string) *PolicyResult {
	for _, pattern := range p.DenyCommands {
		re, err := regexp.Compile(pattern)
		if err != nil {
			continue
		}
		if re.MatchString(command) {
			return &PolicyResult{Allowed: false, Reason: fmt.Sprintf("command denied by policy: %s", pattern)}
		}
	}

	// Check if terminal needs confirmation
	requiresApproval := false
	for _, tool := range p.RequireConfirmationFor {
		if tool == "terminal" {
			requiresApproval = true
			break
		}
	}

	return &PolicyResult{Allowed: true, RequiresApproval: requiresApproval}
}

// CheckToolPolicy checks if a tool requires confirmation.
func (p *Policy) CheckToolPolicy(toolName string) *PolicyResult {
	for _, t := range p.RequireConfirmationFor {
		if t == toolName {
			return &PolicyResult{Allowed: true, RequiresApproval: true,
				Reason: fmt.Sprintf("%s requires confirmation", toolName)}
		}
	}
	return &PolicyResult{Allowed: true}
}
