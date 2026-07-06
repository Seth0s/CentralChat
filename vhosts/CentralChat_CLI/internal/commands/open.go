package commands

import (
	"fmt"
	"os"

	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/ui"
	"github.com/spf13/cobra"
)

func openCmd() *cobra.Command {
	return &cobra.Command{
		Use:   `open [title]`,
		Short: "Open a new session with title and launch TUI (D12)",
		Args:  cobra.MaximumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			client, cfg := mustClient()
			if cfg.WorkspacePath == "" {
				fmt.Fprintln(os.Stderr, "No workspace — run: central workspace .")
				os.Exit(1)
			}
			title := "Nova conversa"
			if len(args) > 0 && args[0] != "" {
				title = args[0]
			}
			out, err := client.CreateSession(title)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			sess, _ := out["session"].(map[string]any)
			sid, _ := sess["id"].(string)
			if sid == "" {
				fmt.Fprintln(os.Stderr, "create session: missing id")
				os.Exit(1)
			}
			if err := config.SaveActiveSession(sid); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			wiOut, err := client.CreateWorkItem(title, "", "normal", sid, cfg.WorkspacePath)
			if err == nil {
				if item, ok := wiOut["item"].(map[string]any); ok {
					if wid, ok := item["id"].(string); ok && wid != "" {
						fmt.Printf("Work item: %s\n", wid)
					}
				}
			}
			if err := ui.Run(client, cfg, ui.RunOptions{SessionID: sid, Title: title}); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
		},
	}
}
