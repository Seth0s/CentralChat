package commands

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/spf13/cobra"
)

func askCmd() *cobra.Command {
	var stream bool
	cmd := &cobra.Command{
		Use:   "ask [message]",
		Short: "Send a message to the assistant",
		Args:  cobra.MinimumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			client, cfg := mustClient()
			text := strings.Join(args, " ")
			workspace := strings.TrimSpace(cfg.WorkspacePath)
			if !stream {
				fmt.Fprintln(os.Stderr, "Use --stream for MVP tool loop")
				os.Exit(1)
			}
			var reply strings.Builder
			err := client.AskStream(api.AskRequest{Text: text, UseAgentTools: true}, workspace, func(event, data string) error {
				switch event {
				case "token":
					var payload struct {
						D string `json:"d"`
					}
					if json.Unmarshal([]byte(data), &payload) == nil {
						fmt.Print(payload.D)
						reply.WriteString(payload.D)
					}
				case "approval_required":
					var payload map[string]any
					if json.Unmarshal([]byte(data), &payload) == nil {
						fmt.Fprintf(os.Stderr, "\n⚠ Approval required: %v\n  central diff %v\n  central approve %v\n",
							payload["summary"], payload["approval_id"], payload["approval_id"])
					}
				case "tool_denied":
					var payload struct {
						ErrorCode string `json:"error_code"`
						MessagePT string `json:"message_pt"`
						Tool      string `json:"tool"`
					}
					if json.Unmarshal([]byte(data), &payload) == nil {
						msg := payload.MessagePT
						if msg == "" {
							msg = data
						}
						fmt.Fprintf(os.Stderr, "\n⛔ Policy blocked tool %s: %s\n", payload.Tool, msg)
						if payload.ErrorCode == "policy_path_denied" || payload.ErrorCode == "policy_tool_denied" {
							fmt.Fprintln(os.Stderr, "  Suggestion: request break-glass from admin or change path.")
						}
					} else {
						fmt.Fprintf(os.Stderr, "\n⛔ Tool blocked by policy: %s\n", data)
					}
				case "status":
					var payload struct {
						Label string `json:"label"`
					}
					if json.Unmarshal([]byte(data), &payload) == nil && payload.Label != "" {
						fmt.Fprintf(os.Stderr, "\r● %s", payload.Label)
					}
				case "error":
					fmt.Fprintf(os.Stderr, "\nerror: %s\n", data)
				case "done":
					fmt.Fprintln(os.Stderr)
				}
				return nil
			})
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if reply.Len() > 0 {
				fmt.Println()
			}
		},
	}
	cmd.Flags().BoolVar(&stream, "stream", true, "SSE stream (default)")
	return cmd
}
