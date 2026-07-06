package commands

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/solo"
	"github.com/spf13/cobra"
)

func queueCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "queue",
		Short: "Work queue (SOLO and TEAM)",
	}
	cmd.AddCommand(queueListCmd())
	cmd.AddCommand(queueShowCmd())
	cmd.AddCommand(queueAddCmd())
	cmd.AddCommand(queueWorkCmd())
	cmd.AddCommand(queueAssignCmd())
	cmd.AddCommand(queueDoneCmd())
	cmd.AddCommand(queueLinkCmd())
	cmd.AddCommand(queueCommentCmd())
	return cmd
}

// isSolo returns true if running in SOLO mode.
func isSolo() bool {
	return config.ResolveMode() == config.ModeSolo
}

// parseUserIDFromJWT extracts the "sub" claim from a JWT access token.
// Returns empty string if parsing fails (optional feature).
func parseUserIDFromJWT(token string) string {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return ""
	}
	// Decode the payload (middle part)
	payload := parts[1]
	// Add padding if needed
	if m := len(payload) % 4; m != 0 {
		payload += strings.Repeat("=", 4-m)
	}
	decoded, err := base64.RawURLEncoding.DecodeString(payload)
	if err != nil {
		return ""
	}
	var claims map[string]any
	if err := json.Unmarshal(decoded, &claims); err != nil {
		return ""
	}
	sub, _ := claims["sub"].(string)
	return sub
}

func queueListCmd() *cobra.Command {
	var status string
	var mine bool
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List work items",
		Run: func(cmd *cobra.Command, args []string) {
			if isSolo() {
				items, err := solo.ListWorkItems(status)
				if err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				if len(items) == 0 {
					fmt.Println("No work items.")
					return
				}
				for _, wi := range items {
					prio := wi.Priority
					if prio == "" {
						prio = "normal"
					}
					fmt.Printf("%-18s  %-14s  %-8s  %s\n", wi.ID, wi.Status, prio, trim(wi.Title, 60))
				}
				return
			}
			client, cfg := mustClient()
			var assigneeFilter string
			if mine {
				assigneeFilter = parseUserIDFromJWT(client.Token)
				if assigneeFilter == "" {
					fmt.Fprintln(os.Stderr, "Could not determine your user ID from token. Try without --mine.")
					os.Exit(1)
				}
			}
			out, err := client.ListWorkItems(status)
			if err != nil {
				_ = cfg
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			items, _ := out["items"].([]any)
			if len(items) == 0 {
				fmt.Println("No work items.")
				return
			}
			for _, it := range items {
				m, _ := it.(map[string]any)
				id, _ := m["id"].(string)
				title, _ := m["title"].(string)
				st, _ := m["status"].(string)
				pri, _ := m["priority"].(string)
				assignee, _ := m["assignee_id"].(string)
				// Filter by assignee if --mine
				if mine && assigneeFilter != "" && assignee != assigneeFilter {
					continue
				}
				fmt.Printf("%-12s  %-14s  %-8s  %s\n", id, st, pri, trim(title, 60))
			}
		},
	}
	cmd.Flags().StringVar(&status, "status", "", "open|in_progress|review|done")
	cmd.Flags().BoolVar(&mine, "mine", false, "Only show items assigned to you")
	return cmd
}

func queueShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show [id]",
		Short: "Show work item details",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			if isSolo() {
				items, err := solo.ListWorkItems("")
				if err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				for _, wi := range items {
					if wi.ID == args[0] {
						b, _ := json.MarshalIndent(wi, "", "  ")
						fmt.Println(string(b))
						return
					}
				}
				fmt.Fprintf(os.Stderr, "Work item %s not found.\n", args[0])
				os.Exit(1)
			}
			client, _ := mustClient()
			out, err := client.GetWorkItem(args[0])
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}

func queueAddCmd() *cobra.Command {
	var priority, sessionID, workspace, agentName, skills string
	cmd := &cobra.Command{
		Use:   "add [title]",
		Short: "Create work item",
		Args:  cobra.MinimumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			title := args[0]
			desc := ""
			if len(args) > 1 {
				desc = args[1]
			}
			if isSolo() {
				ctx := desc
				if agentName != "" {
					if ctx != "" {
						ctx += "\n"
					}
					ctx += "agent: " + agentName
				}
				if skills != "" {
					if ctx != "" {
						ctx += "\n"
					}
					ctx += "skills: " + skills
				}
				wi, err := solo.AddWorkItem(title, priority, ctx)
				if err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				b, _ := json.MarshalIndent(wi, "", "  ")
				fmt.Println(string(b))
				return
			}
			client, _ := mustClient()
			body := map[string]any{"title": title, "priority": priority}
			if desc != "" {
				body["description"] = desc
			}
			if sessionID != "" {
				body["session_id"] = sessionID
			}
			if workspace != "" {
				body["workspace_path"] = workspace
			}
			if agentName != "" {
				body["agent_name"] = agentName
			}
			if skills != "" {
				parts := strings.Split(skills, ",")
				trimmed := make([]string, 0, len(parts))
				for _, p := range parts {
					if t := strings.TrimSpace(p); t != "" {
						trimmed = append(trimmed, t)
					}
				}
				body["skills"] = trimmed
			}
			out, err := client.CreateWorkItemBody(body)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	cmd.Flags().StringVar(&priority, "priority", "normal", "low|normal|high|urgent")
	cmd.Flags().StringVar(&sessionID, "session", "", "linked session id")
	cmd.Flags().StringVar(&workspace, "workspace", "", "workspace path")
	cmd.Flags().StringVar(&agentName, "agent", "", "Agent name (e.g. coder, reviewer)")
	cmd.Flags().StringVar(&skills, "skills", "", "Comma-separated skill names (e.g. debug,test)")
	return cmd
}

func queueWorkCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "work [id]",
		Short: "Start work on item (in_progress + session)",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			if isSolo() {
				if err := solo.UpdateWorkItemStatus(args[0], "in_progress"); err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				fmt.Printf("Work item %s marked in_progress.\n", args[0])
				return
			}
			client, _ := mustClient()
			out, err := client.WorkWorkItem(args[0])
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			hint, _ := out["hint"].(string)
			sid, _ := out["session_id"].(string)
			if hint != "" {
				fmt.Println(hint)
			}
			if sid != "" {
				fmt.Printf("session_id: %s\n", sid)
			}
		},
	}
}

func queueAssignCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "assign [id] [user-uuid]",
		Short: "Assign work item",
		Args:  cobra.ExactArgs(2),
		Run: func(cmd *cobra.Command, args []string) {
			if isSolo() {
				fmt.Fprintln(os.Stderr, "assign is not available in SOLO mode (no multi-user).")
				os.Exit(1)
			}
			client, _ := mustClient()
			out, err := client.PatchWorkItem(args[0], map[string]any{"assignee_id": args[1]})
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}

func queueDoneCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "done [id]",
		Short: "Mark work item done",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			if isSolo() {
				if err := solo.UpdateWorkItemStatus(args[0], "done"); err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				fmt.Printf("Work item %s marked done.\n", args[0])
				return
			}
			client, _ := mustClient()
			out, err := client.PatchWorkItem(args[0], map[string]any{"status": "done"})
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}

func queueLinkCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "link [id] [url]",
		Short: "Link work item to external issue (Linear/Jira)",
		Args:  cobra.ExactArgs(2),
		Run: func(cmd *cobra.Command, args []string) {
			if isSolo() {
				fmt.Fprintln(os.Stderr, "link is not available in SOLO mode (no external integrations).")
				os.Exit(1)
			}
			client, _ := mustClient()
			out, err := client.LinkWorkItem(args[0], args[1], "")
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}

func queueCommentCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "comment [id] [text]",
		Short: "Add comment to work item",
		Args:  cobra.MinimumNArgs(2),
		Run: func(cmd *cobra.Command, args []string) {
			wiID := args[0]
			body := strings.Join(args[1:], " ")
			if isSolo() {
				if err := solo.AddWorkItemComment(wiID, body); err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				fmt.Printf("Comment added to %s.\n", wiID)
				return
			}
			client, _ := mustClient()
			out, err := client.PostComment(wiID, body)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}
