package commands

import (
	"fmt"
	"os"
	"time"

	"github.com/spf13/cobra"
)

func watchCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "watch",
		Short: "Status panel — pending approvals and workspace (no chat input)",
		Run: func(cmd *cobra.Command, args []string) {
			client, cfg := mustClient()
			fmt.Printf("Central watch — workspace: %s\n", cfg.WorkspacePath)
			for {
				if ws, err := client.GetWorkspace(); err == nil {
					git, _ := ws["git"].(map[string]any)
					fmt.Printf("\r[%s] branch=%v dirty=%v     ",
						ws["path"], git["branch"], git["dirty_count"])
				}
				if ap, err := client.ListApprovals("pending"); err == nil {
					if items, ok := ap["items"].([]any); ok {
						fmt.Printf(" pending=%d ", len(items))
					}
				}
				os.Stdout.Sync()
				time.Sleep(2 * time.Second)
			}
		},
	}
}
