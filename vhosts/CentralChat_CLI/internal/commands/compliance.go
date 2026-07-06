package commands

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func complianceCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "compliance",
		Short: "Compliance packs (PCI, LGPD, ISO27001)",
	}
	cmd.AddCommand(complianceListCmd())
	cmd.AddCommand(complianceShowCmd())
	cmd.AddCommand(complianceApplyCmd())
	cmd.AddCommand(complianceResidencyCmd())
	return cmd
}

func complianceListCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List available compliance packs",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ListCompliancePacks()
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			items, _ := out["items"].([]any)
			for _, it := range items {
				m, _ := it.(map[string]any)
				id, _ := m["id"].(string)
				name, _ := m["name"].(string)
				fw, _ := m["framework"].(string)
				fmt.Printf("%-12s  %-24s  %s\n", id, name, fw)
			}
		},
	}
	return cmd
}

func complianceShowCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "show <pack-id>",
		Short: "Show compliance pack details",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ShowCompliancePack(args[0])
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	return cmd
}

func complianceApplyCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "apply <pack-id>",
		Short: "Apply compliance pack to tenant policies",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ApplyCompliancePack(args[0])
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	return cmd
}

func complianceResidencyCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "residency",
		Short: "Show data residency / air-gap runtime flags",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.DeployResidency()
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	return cmd
}
