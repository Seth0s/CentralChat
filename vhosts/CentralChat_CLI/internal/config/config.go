package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/BurntSushi/toml"
	"github.com/centralchurch/central-cli/internal/auth"
)

const defaultAPIURL = "http://127.0.0.1:8004"

// ── Runtime mode ───────────────────────────────────────────────

type RuntimeMode string

const (
	ModeSolo RuntimeMode = "solo"
	ModeTeam RuntimeMode = "team"
)

// ── Provider types ─────────────────────────────────────────────

type ProviderKind string

const (
	ProviderOpenRouter       ProviderKind = "openrouter"
	ProviderLlamaCpp         ProviderKind = "llamacpp"
	ProviderOpenAI           ProviderKind = "openai"
	ProviderAnthropic        ProviderKind = "anthropic"
	ProviderDeepSeek         ProviderKind = "deepseek"
	ProviderOpenAICompatible ProviderKind = "openai_compatible"
)

// ProviderConfig defines one LLM provider.
type ProviderConfig struct {
	Kind    ProviderKind `toml:"kind"`
	APIKey  string       `toml:"api_key,omitempty"`
	BaseURL string       `toml:"base_url,omitempty"`
	Model   string       `toml:"model,omitempty"`
}

// ResolveEnv replaces $VAR and ${VAR} references with environment values.
func (p *ProviderConfig) ResolveEnv() {
	p.APIKey = os.ExpandEnv(p.APIKey)
	p.BaseURL = os.ExpandEnv(p.BaseURL)
}

// ── Runtime config (TOML) ─────────────────────────────────────

type RuntimeConfig struct {
	Mode   RuntimeMode `toml:"mode"`
	APIURL string      `toml:"api_url,omitempty"`
	Team   TeamConfig  `toml:"team,omitempty"`
	Solo   SoloConfig  `toml:"solo,omitempty"`
}

type TeamConfig struct {
	APIURL string `toml:"api_url,omitempty"`
}

type SoloConfig struct {
	DefaultProvider string                   `toml:"default_provider,omitempty"`
	Model           string                   `toml:"model,omitempty"`
	DataDir         string                   `toml:"data_dir,omitempty"`
	Providers       map[string]ProviderConfig `toml:"providers,omitempty"`
}

// ActiveProvider returns the configured provider (config or env fallback).
func (s *SoloConfig) ActiveProvider() (*ProviderConfig, string) {
	// 1. Named provider from config
	if s.DefaultProvider != "" {
		if p, ok := s.Providers[s.DefaultProvider]; ok {
			p.ResolveEnv()
			if s.Model != "" && p.Model == "" {
				p.Model = s.Model
			}
			return &p, s.DefaultProvider
		}
	}
	// 2. First configured provider
	for name, p := range s.Providers {
		p.ResolveEnv()
		if s.Model != "" && p.Model == "" {
			p.Model = s.Model
		}
		return &p, name
	}
	// 3. Env var fallbacks
	if key := os.Getenv("OPENROUTER_API_KEY"); key != "" {
		model := os.Getenv("CENTRAL_SOLO_MODEL")
		if model == "" {
			model = "openai/gpt-4o-mini"
		}
		return &ProviderConfig{
			Kind:   ProviderOpenRouter,
			APIKey: key,
			Model:  model,
		}, "openrouter"
	}
	if url := os.Getenv("LLAMACPP_URL"); url != "" {
		model := os.Getenv("CENTRAL_SOLO_MODEL")
		if model == "" {
			model = "local-model"
		}
		return &ProviderConfig{
			Kind:    ProviderLlamaCpp,
			BaseURL: url,
			Model:   model,
		}, "llamacpp"
	}
	if key := os.Getenv("OPENAI_API_KEY"); key != "" {
		model := os.Getenv("CENTRAL_SOLO_MODEL")
		if model == "" {
			model = "gpt-4o"
		}
		return &ProviderConfig{
			Kind:   ProviderOpenAI,
			APIKey: key,
			Model:  model,
		}, "openai"
	}
	if key := os.Getenv("ANTHROPIC_API_KEY"); key != "" {
		model := os.Getenv("CENTRAL_SOLO_MODEL")
		if model == "" {
			model = "claude-sonnet-4-20250514"
		}
		return &ProviderConfig{
			Kind:   ProviderAnthropic,
			APIKey: key,
			Model:  model,
		}, "anthropic"
	}
	if key := os.Getenv("DEEPSEEK_API_KEY"); key != "" {
		model := os.Getenv("CENTRAL_SOLO_MODEL")
		if model == "" {
			model = "deepseek-chat"
		}
		return &ProviderConfig{
			Kind:   ProviderDeepSeek,
			APIKey: key,
			Model:  model,
		}, "deepseek"
	}
	return nil, ""
}

// HasAnyProvider returns true if at least one provider is configured
// (via config.toml or environment variables).
func HasAnyProvider() bool {
	rt, err := LoadRuntimeConfig()
	if err != nil || rt == nil {
		// No config file — check env vars directly
		return os.Getenv("OPENROUTER_API_KEY") != "" ||
			os.Getenv("LLAMACPP_URL") != "" ||
			os.Getenv("OPENAI_API_KEY") != "" ||
			os.Getenv("ANTHROPIC_API_KEY") != "" ||
			os.Getenv("DEEPSEEK_API_KEY") != ""
	}
	pc, _ := rt.Solo.ActiveProvider()
	return pc != nil
}

// ── Legacy flat config ─────────────────────────────────────────

type Config struct {
	APIURL          string
	WorkspacePath   string
	ConnectorID     string
	WebDiffMinLines int
	Runtime         RuntimeMode
}

// ── Config directory ───────────────────────────────────────────

func ConfigDir() (string, error) {
	base, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(base, "central")
	return dir, os.MkdirAll(dir, 0o700)
}

func RuntimeConfigPath() (string, error) {
	dir, err := ConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "config.toml"), nil
}

// ── Load / Save ────────────────────────────────────────────────

func LoadRuntimeConfig() (*RuntimeConfig, error) {
	path, err := RuntimeConfigPath()
	if err != nil {
		return nil, err
	}
	cfg := &RuntimeConfig{
		Mode: ModeSolo,
	}
	if data, err := os.ReadFile(path); err == nil {
		if err := toml.Unmarshal(data, cfg); err != nil {
			return nil, fmt.Errorf("config.toml: %w", err)
		}
	}
	switch cfg.Mode {
	case ModeSolo, ModeTeam, "":
		if cfg.Mode == "" {
			cfg.Mode = ModeSolo
		}
	default:
		return nil, fmt.Errorf("config.toml: unknown runtime mode %q (expected solo or team)", cfg.Mode)
	}
	return cfg, nil
}

func SaveRuntimeConfig(cfg *RuntimeConfig) error {
	path, err := RuntimeConfigPath()
	if err != nil {
		return err
	}
	var sb strings.Builder
	if err := toml.NewEncoder(&sb).Encode(cfg); err != nil {
		return err
	}
	return os.WriteFile(path, []byte(sb.String()), 0o600)
}

func ResolveMode() RuntimeMode {
	rt, err := LoadRuntimeConfig()
	if err != nil {
		return ModeSolo
	}
	return rt.Mode
}

// HasRuntimeConfig returns true if config.toml exists on disk.
func HasRuntimeConfig() bool {
	path, err := RuntimeConfigPath()
	if err != nil {
		return false
	}
	_, err = os.Stat(path)
	return err == nil
}

func Load() (*Config, error) {
	rt, err := LoadRuntimeConfig()
	if err != nil {
		rt = &RuntimeConfig{Mode: ModeSolo}
	}
	dir, err := ConfigDir()
	if err != nil {
		return nil, err
	}
	cfg := &Config{
		APIURL:          defaultAPIURL,
		ConnectorID:     "local-dev",
		WebDiffMinLines: 100,
		Runtime:         rt.Mode,
	}
	if v := os.Getenv("CENTRAL_API_URL"); v != "" {
		cfg.APIURL = v
	}
	if rt.Team.APIURL != "" {
		cfg.APIURL = rt.Team.APIURL
	}
	wsFile := filepath.Join(dir, "workspace")
	if data, err := os.ReadFile(wsFile); err == nil {
		cfg.WorkspacePath = string(data)
	}
	return cfg, nil
}

// ── Helpers ────────────────────────────────────────────────────

func SaveWorkspace(path string) error {
	dir, err := ConfigDir()
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "workspace"), []byte(path), 0o600)
}

func LoadActiveSession() string {
	dir, err := ConfigDir()
	if err != nil {
		return ""
	}
	data, err := os.ReadFile(filepath.Join(dir, "active_session"))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func SaveActiveSession(sessionID string) error {
	dir, err := ConfigDir()
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "active_session"), []byte(sessionID), 0o600)
}

func LoadActiveAgent() string {
	dir, err := ConfigDir()
	if err != nil {
		return ""
	}
	data, err := os.ReadFile(filepath.Join(dir, "active_agent"))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func SaveActiveAgent(name string) error {
	dir, err := ConfigDir()
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "active_agent"), []byte(name), 0o600)
}

func CredentialsPath() (string, error) {
	dir, err := ConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, auth.CredentialsFile), nil
}
