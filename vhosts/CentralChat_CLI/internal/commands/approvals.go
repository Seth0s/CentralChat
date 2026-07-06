package commands

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/centralchurch/central-cli/internal/config"
	"github.com/spf13/cobra"
)

func pendingCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "pending",
		Short: "List pending approvals",
		Run: func(cmd *cobra.Command, args []string) {
			guardSolo("pending")
			client, _ := mustClient()
			out, err := client.ListApprovals("pending")
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			items, _ := out["items"].([]any)
			if len(items) == 0 {
				fmt.Println("No pending approvals.")
				return
			}
			for _, it := range items {
				m, _ := it.(map[string]any)
				fmt.Printf("%s  %s  %s\n", m["approval_id"], m["action_id"], m["status"])
			}
		},
	}
}

func diffCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "diff [approval_id]",
		Short: "Show unified diff for an approval",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			guardSolo("diff")
			client, _ := mustClient()
			out, err := client.ApprovalDiff(args[0])
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if d, ok := out["diff"].(string); ok && d != "" {
				fmt.Print(d)
				return
			}
			if kind, _ := out["kind"].(string); kind == "shell" {
				if c, ok := out["command"].(string); ok {
					fmt.Printf("Command: %s\n", c)
				}
				if cwd, ok := out["cwd"].(string); ok && cwd != "" {
					fmt.Printf("CWD: %s\n", cwd)
				}
				return
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}

func approveCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "approve [approval_id]",
		Short: "Approve a pending change",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			guardMutating(cmd, "approve")
			guardSolo("approve")
			client, _ := mustClient()
			out, err := client.Approve(args[0])
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			fmt.Printf("Approved: %s\n", args[0])
			if job, ok := out["client_job_id"]; ok {
				fmt.Printf("Client job enqueued: %v (ensure central daemon is running)\n", job)
			}
		},
	}
}

func rejectCmd() *cobra.Command {
	var reason string
	cmd := &cobra.Command{
		Use:   "reject [approval_id]",
		Short: "Reject a pending change",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			guardMutating(cmd, "reject")
			client, _ := mustClient()
			if err := client.Deny(args[0], reason); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			fmt.Printf("Rejected: %s\n", args[0])
		},
	}
	cmd.Flags().StringVarP(&reason, "message", "m", "", "rejection reason")
	return cmd
}

func sessionsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "sessions",
		Short: "List chat sessions",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ListSessions()
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	cmd.AddCommand(sessionsRenameCmd())
	return cmd
}

func sessionsRenameCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "rename [session_id] <title>",
		Short: "Rename a chat session (D12)",
		Args:  cobra.MinimumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			guardSolo("pending")
			client, _ := mustClient()
			var sid, title string
			if len(args) == 1 {
				sid = config.LoadActiveSession()
				title = args[0]
				if sid == "" {
					fmt.Fprintln(os.Stderr, "no active session — pass session_id or run: central open")
					os.Exit(1)
				}
			} else {
				sid = args[0]
				title = args[1]
			}
			if title == "" {
				fmt.Fprintln(os.Stderr, "title required")
				os.Exit(1)
			}
			out, err := client.PatchSession(sid, title)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}
