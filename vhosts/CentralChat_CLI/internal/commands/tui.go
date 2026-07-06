package commands

import (
	"fmt"
	"os"

	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/ui"
	"github.com/spf13/cobra"
)

func tuiCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "tui",
		Short: "Interactive session TUI (Surface Model)",
		Run: func(cmd *cobra.Command, args []string) {
			runTUI()
		},
	}
}

func runTUI() {
	cfg, err := config.Load()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := ui.RunApp(cfg); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
