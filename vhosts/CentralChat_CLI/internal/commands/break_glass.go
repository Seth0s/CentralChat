package commands

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func breakGlassCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "break-glass",
		Short: "Admin break-glass overrides (audited, 1h TTL)",
	}
	cmd.AddCommand(breakGlassListCmd())
	cmd.AddCommand(breakGlassGrantCmd())
	cmd.AddCommand(breakGlassRevokeCmd())
	return cmd
}

func breakGlassListCmd() *cobra.Command {
	var userID string
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List active break-glass grants",
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			out, err := client.ListBreakGlass(userID)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	cmd.Flags().StringVar(&userID, "user", "", "filter by user sub")
	return cmd
}

func breakGlassGrantCmd() *cobra.Command {
	var reason, userID string
	var ttl float64
	cmd := &cobra.Command{
		Use:   "grant <path-pattern>",
		Short: "Grant break-glass override for a path pattern",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			if reason == "" {
				fmt.Fprintln(os.Stderr, "--reason is required")
				os.Exit(1)
			}
			client, _ := mustClient()
			out, err := client.GrantBreakGlass(args[0], reason, userID, ttl)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Println(string(b))
		},
	}
	cmd.Flags().StringVar(&reason, "reason", "", "justification (required)")
	cmd.Flags().StringVar(&userID, "user", "", "target user sub (default: self)")
	cmd.Flags().Float64Var(&ttl, "ttl", 1, "TTL in hours (max 24)")
	return cmd
}

func breakGlassRevokeCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "revoke <grant-id>",
		Short: "Revoke an active break-glass grant",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			client, _ := mustClient()
			if err := client.RevokeBreakGlass(args[0]); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			fmt.Println("Revoked.")
		},
	}
	return cmd
}
