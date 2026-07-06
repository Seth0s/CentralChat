package commands

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/centralchurch/central-cli/internal/config"
	"github.com/spf13/cobra"
)

func agentsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "agents",
		Short: "Team agent catalog",
	}
	cmd.AddCommand(agentsListCmd())
	cmd.AddCommand(agentsCreateCmd())
	cmd.AddCommand(agentsSubmitCmd())
	cmd.AddCommand(agentsPublishCmd())
	cmd.AddCommand(agentUseCmd())
	return cmd
}

func agentsListCmd() *cobra.Command {
	var status string
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List team agents",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ListTeamAgents(status)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			items, _ := out["items"].([]any)
			if len(items) == 0 {
				fmt.Println("No team agents.")
				return
			}
			for _, it := range items {
				m, _ := it.(map[string]any)
				name, _ := m["name"].(string)
				lc, _ := m["lifecycle_status"].(string)
				prompt, _ := m["prompt"].(string)
				fmt.Printf("%-20s %-10s  %s\n", name, lc, trim(prompt, 50))
			}
		},
	}
	cmd.Flags().StringVar(&status, "status", "published", "all|draft|review|published")
	return cmd
}

func agentsCreateCmd() *cobra.Command {
	var prompt, modelID string
	cmd := &cobra.Command{
		Use:   "create [name]",
		Short: "Create agent draft",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.CreateTeamAgent(args[0], prompt, modelID)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	cmd.Flags().StringVar(&prompt, "prompt", "", "system prompt")
	cmd.Flags().StringVar(&modelID, "model", "", "model id override")
	return cmd
}

func agentsSubmitCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "submit [agent_id]",
		Short: "Submit agent draft for review",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.SubmitTeamAgentReview(args[0])
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}

func agentsPublishCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "publish [agent_id]",
		Short: "Publish agent after review",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.PublishTeamAgent(args[0])
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
}

func agentUseCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "use [name]",
		Short: "Select team agent for this CLI session",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			name := args[0]
			if err := config.SaveActiveAgent(name); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			fmt.Printf("Active agent: %s\n", name)
		},
	}
}

func rulesCmd() *cobra.Command {
	var status string
	cmd := &cobra.Command{
		Use:   "rules",
		Short: "Team rules (pending + approved)",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ListTeamRules(status)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	cmd.Flags().StringVar(&status, "status", "all", "all|pending|approved")
	return cmd
}

func trim(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}
