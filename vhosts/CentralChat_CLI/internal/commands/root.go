package commands

import (
	"fmt"
	"os"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/auth"
	"github.com/centralchurch/central-cli/internal/clierrors"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/offline"
	"github.com/centralchurch/central-cli/internal/version"
	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "central",
	Short: "CentralChat CLI — AI agent runtime for SOLO and TEAM modes",
	Long: `CentralChat CLI — terminal-native AI agent.

RUNTIME MODES
  SOLO  Self-sufficient local agent (no VPS required).
        Set OPENROUTER_API_KEY or OLLAMA_URL, then just run: central
        Sessions and memory stored locally in ~/.config/central/
        
  TEAM  Enterprise mode with VPS control plane.
        Requires login: central login

QUICK START (SOLO)
  export OPENROUTER_API_KEY=sk-...
  central                       # launch TUI
  central ask "explain main.go" # one-shot question
  central doctor                # diagnose setup

COMMANDS
  central                  Launch interactive TUI
  central ask <text>       One-shot question (non-interactive)
  central login            Authenticate with TEAM VPS
  central doctor           Diagnose setup and connectivity
  central workspace <dir>  Bind a workspace directory
  central sync push|pull   Bridge SOLO ↔ TEAM
  central serve --local    [DEPRECATED] Python loopback server
  central models           List available models (TEAM)
  central sessions         List chat sessions
  central daemon           [TEAM] Connector executor daemon
  central approve|reject   [TEAM] Manage pending approvals
  central pending          [TEAM] List pending approvals
  central --version        Show version
  central --help           This help

TUI KEYBINDINGS
  Enter        Send message
  /            Slash commands: /model /agent /tools /help /prefs /doctor
  Tab          Switch Plan/Build mode
  Ctrl+H       Toggle sidebar
  Ctrl+B       Toggle bottom panel
  Ctrl+P       Command palette
  Ctrl+L       Logout
  Ctrl+C       Quit

CONFIGURATION
  ~/.config/central/config.toml   Runtime mode and provider config
  ~/.config/central/policy.yaml   Tool access policy (SOLO)
  ~/.config/central/agents/       Agent personas (SOLO)
  ~/.config/central/skills/       Skill prompts (SOLO)

ENVIRONMENT
  OPENROUTER_API_KEY   API key for OpenRouter (SOLO)
  LLAMACPP_URL         llama.cpp server URL (SOLO, default http://127.0.0.1:8080/v1)
  OPENAI_API_KEY       API key for OpenAI (SOLO)
  ANTHROPIC_API_KEY    API key for Anthropic (SOLO)
  DEEPSEEK_API_KEY     API key for DeepSeek (SOLO)
  CENTRAL_API_URL      VPS API URL (TEAM, default http://127.0.0.1:8004)
  CENTRAL_SOLO_MODEL   Override default model in SOLO mode`,
	Version: version.Version,
	Run: func(cmd *cobra.Command, args []string) {
		runTUI()
	},
}

func init() {
	rootCmd.PersistentFlags().Bool("offline", false, "modo read-only offline (cache local)")
}

func offlineMode(cmd *cobra.Command) bool {
	if offline.Enabled() {
		return true
	}
	f, _ := cmd.Root().PersistentFlags().GetBool("offline")
	return f
}

func guardMutating(cmd *cobra.Command, name string) {
	if offlineMode(cmd) {
		fmt.Fprintln(os.Stderr, "Modo offline (read-only): comando '"+name+"' bloqueado.")
		os.Exit(2)
	}
}

// guardSolo blocks commands that require VPS/TEAM mode.
func guardSolo(name string) {
	mode := config.ResolveMode()
	if mode == config.ModeSolo {
		fmt.Fprintf(os.Stderr, "%s is TEAM-only. SOLO mode uses local tools and policy.\n", name)
		os.Exit(2)
	}
}

func Execute() error {
	rootCmd.AddCommand(loginCmd())
	rootCmd.AddCommand(workspaceCmd())
	rootCmd.AddCommand(tuiCmd())
	rootCmd.AddCommand(askCmd())
	rootCmd.AddCommand(pendingCmd())
	rootCmd.AddCommand(diffCmd())
	rootCmd.AddCommand(approveCmd())
	rootCmd.AddCommand(rejectCmd())
	rootCmd.AddCommand(sessionsCmd())
	rootCmd.AddCommand(openCmd())
	rootCmd.AddCommand(agentsCmd())
	rootCmd.AddCommand(rulesCmd())
	rootCmd.AddCommand(auditCmd())
	rootCmd.AddCommand(queueCmd())
	rootCmd.AddCommand(policyCmd())
	rootCmd.AddCommand(breakGlassCmd())
	rootCmd.AddCommand(complianceCmd())
	rootCmd.AddCommand(doctorCmd())
	rootCmd.AddCommand(daemonCmd())
	rootCmd.AddCommand(watchCmd())
	rootCmd.AddCommand(modelsCmd())
	rootCmd.AddCommand(serveCmd())
	rootCmd.AddCommand(syncCmd())
	rootCmd.AddCommand(setupCmd())
	rootCmd.AddCommand(modeCmd())
	return rootCmd.Execute()
}

func loadClient() (*api.Client, *config.Config, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, nil, err
	}
	credPath, err := config.CredentialsPath()
	if err != nil {
		return nil, nil, err
	}
	cred, err := auth.Load(credPath)
	if err != nil {
		return nil, nil, fmt.Errorf("not logged in — run: central login")
	}
	base := cfg.APIURL
	if cred.APIURL != "" {
		base = cred.APIURL
	}
	return api.New(base, cred.AccessToken), cfg, nil
}

func mustClient() (*api.Client, *config.Config) {
	c, cfg, err := loadClient()
	if err != nil {
		fmt.Fprintln(os.Stderr, clierrors.UserMessage(err))
		os.Exit(1)
	}
	return c, cfg
}
