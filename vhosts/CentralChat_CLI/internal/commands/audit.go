package commands

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func auditCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "audit",
		Short: "Enterprise audit log (read-only)",
	}
	cmd.AddCommand(auditListCmd())
	cmd.AddCommand(auditExportCmd())
	cmd.AddCommand(auditReportCmd())
	return cmd
}

func auditListCmd() *cobra.Command {
	var since, user, action string
	var limit int
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List audit events",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ListAuditEvents(since, user, action, limit)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			items, _ := out["items"].([]any)
			if len(items) == 0 {
				fmt.Println("No audit events.")
				return
			}
			for _, it := range items {
				m, _ := it.(map[string]any)
				created, _ := m["created_at"].(string)
				act, _ := m["action"].(string)
				res, _ := m["resource"].(string)
				uid, _ := m["user_id"].(string)
				fmt.Printf("%s  %-24s  %s  %s\n", trim(created, 25), act, trim(res, 40), trim(uid, 36))
			}
		},
	}
	cmd.Flags().StringVar(&since, "since", "", "7d, 24h, or ISO date")
	cmd.Flags().StringVar(&user, "user", "", "filter by user UUID")
	cmd.Flags().StringVar(&action, "action", "", "filter by action")
	cmd.Flags().IntVar(&limit, "limit", 200, "max rows")
	return cmd
}

func auditExportCmd() *cobra.Command {
	var format, since, output string
	var limit int
	cmd := &cobra.Command{
		Use:   "export",
		Short: "Export audit log (csv or json)",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			body, err := client.ExportAudit(format, since, limit)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if output == "" || output == "-" {
				fmt.Print(string(body))
				return
			}
			if err := os.WriteFile(output, body, 0o644); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			fmt.Printf("Exported to %s\n", output)
		},
	}
	cmd.Flags().StringVar(&format, "format", "csv", "csv|json")
	cmd.Flags().StringVar(&since, "since", "", "7d, 24h, or ISO date")
	cmd.Flags().StringVar(&output, "output", "-", "output file (- for stdout)")
	cmd.Flags().IntVar(&limit, "limit", 5000, "max rows")
	return cmd
}

func auditReportCmd() *cobra.Command {
	var format, since, pathPrefix, output string
	var limit int
	cmd := &cobra.Command{
		Use:   "report",
		Short: "Structured audit report (json or pdf)",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			body, err := client.ExportAuditReport(format, since, pathPrefix, limit)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if output == "" || output == "-" {
				if format == "json" {
					var pretty map[string]any
					if json.Unmarshal(body, &pretty) == nil {
						b, _ := json.MarshalIndent(pretty, "", "  ")
						fmt.Println(string(b))
						return
					}
				}
				os.Stdout.Write(body)
				return
			}
			if err := os.WriteFile(output, body, 0o644); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			fmt.Printf("Report saved to %s\n", output)
		},
	}
	cmd.Flags().StringVar(&format, "format", "json", "json|pdf")
	cmd.Flags().StringVar(&since, "since", "7d", "7d, 24h, or ISO date")
	cmd.Flags().StringVar(&pathPrefix, "path", "", "filter by path prefix (e.g. payment/)")
	cmd.Flags().StringVar(&output, "output", "-", "output file (- for stdout)")
	cmd.Flags().IntVar(&limit, "limit", 5000, "max rows")
	return cmd
}

func policyCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "policy",
		Short: "Team policy",
	}
	cmd.AddCommand(&cobra.Command{
		Use:   "show",
		Short: "Show team policy snapshot",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ShowPolicies()
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	})
	return cmd
}
