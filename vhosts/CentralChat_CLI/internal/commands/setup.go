package commands

import (
	"fmt"
	"os"
	"strings"

	"github.com/centralchurch/central-cli/internal/config"
	"github.com/spf13/cobra"
)

var setupProviderFlag string
var setupModelFlag string
var setupListFlag bool

func setupCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "setup",
		Short: "Configure LLM providers for SOLO mode",
		Long: `Configure one or more LLM providers for SOLO mode.

API keys are NEVER stored in config.toml — only $ENV_VAR references.
Add the key to your shell profile (~/.bashrc or ~/.zshrc).

Supported providers:
  openrouter   OPENROUTER_API_KEY
  ollama       OLLAMA_URL (local, no key needed)
  openai       OPENAI_API_KEY
  anthropic    ANTHROPIC_API_KEY
  deepseek     DEEPSEEK_API_KEY

Examples:
  central setup                  # Interactive (TUI)
  central setup --provider deepseek --model deepseek-chat
  central setup --list           # Show configured providers`,
		Run: runSetup,
	}
	cmd.Flags().StringVar(&setupProviderFlag, "provider", "", "Provider kind (openrouter, ollama, openai, anthropic, deepseek)")
	cmd.Flags().StringVar(&setupModelFlag, "model", "", "Model name (e.g., deepseek-chat)")
	cmd.Flags().BoolVar(&setupListFlag, "list", false, "List configured providers")
	return cmd
}

func runSetup(cmd *cobra.Command, args []string) {
	if setupListFlag {
		rt, err := config.LoadRuntimeConfig()
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error loading config:", err)
			os.Exit(1)
		}
		if rt == nil || len(rt.Solo.Providers) == 0 {
			fmt.Println("No providers configured.")
			fmt.Println("\nRun: central setup")
			return
		}
		fmt.Println("Configured providers:")
		for name, p := range rt.Solo.Providers {
			active := ""
			if name == rt.Solo.DefaultProvider {
				active = " (active)"
			}
			fmt.Printf("  %s  kind=%s  model=%s%s\n", name, p.Kind, p.Model, active)
		}
		return
	}

	if setupProviderFlag == "" {
		// No flags — run interactive TUI setup
		runTUI()
		return
	}

	// Non-interactive setup via flags
	kind := config.ProviderKind(strings.ToLower(setupProviderFlag))
	var envVar string
	switch kind {
	case config.ProviderOpenRouter:
		envVar = "OPENROUTER_API_KEY"
	case config.ProviderLlamaCpp:
		envVar = "LLAMACPP_URL"
	case config.ProviderOpenAI:
		envVar = "OPENAI_API_KEY"
	case config.ProviderAnthropic:
		envVar = "ANTHROPIC_API_KEY"
	case config.ProviderDeepSeek:
		envVar = "DEEPSEEK_API_KEY"
	default:
		fmt.Fprintf(os.Stderr, "Unknown provider: %s\n", setupProviderFlag)
		fmt.Fprintf(os.Stderr, "Valid: openrouter, ollama, openai, anthropic, deepseek\n")
		os.Exit(1)
	}

	model := setupModelFlag
	if model == "" {
		switch kind {
		case config.ProviderOpenRouter:
				model = "openai/gpt-4o-mini"
			case config.ProviderLlamaCpp:
				model = "local-model"
			case config.ProviderOpenAI:
			model = "gpt-4o"
		case config.ProviderAnthropic:
			model = "claude-sonnet-4-20250514"
		case config.ProviderDeepSeek:
			model = "deepseek-chat"
		}
	}

	rt, err := config.LoadRuntimeConfig()
	if err != nil || rt == nil {
		rt = &config.RuntimeConfig{Mode: config.ModeSolo}
	}
	if rt.Solo.Providers == nil {
		rt.Solo.Providers = make(map[string]config.ProviderConfig)
	}

	rt.Solo.DefaultProvider = string(kind)
	rt.Solo.Providers[string(kind)] = config.ProviderConfig{
		Kind:   kind,
		APIKey: "$" + envVar,
		Model:  model,
	}

	if err := config.SaveRuntimeConfig(rt); err != nil {
		fmt.Fprintf(os.Stderr, "Error saving config: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Provider %s configured.\n", kind)
	fmt.Printf("  Model: %s\n", model)
	if kind != config.ProviderLlamaCpp {
		fmt.Printf("  Set env var: export %s=\"***\"\n", envVar)
		fmt.Printf("  Add to your shell profile (~/.bashrc or ~/.zshrc).\n")
	}
	fmt.Println("  Config saved to ~/.config/central/config.toml")
	fmt.Println("\nRun: central")
}
