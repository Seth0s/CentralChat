package commands

import (
	"fmt"
	"os"
	"strings"

	"github.com/centralchurch/central-cli/internal/config"
	"github.com/spf13/cobra"
)

var modeTeamURL string

func modeCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "mode [solo|team]",
		Short: "Show or switch runtime mode (SOLO / TEAM)",
		Long: `Manage the CentralChat runtime mode.

Without arguments, prints the current mode.

  central mode              Show current mode
  central mode solo         Switch to SOLO mode (local, no server required)
  central mode team         Switch to TEAM mode (connect to VPS)
  central mode team --url http://vps.example.com:8004`,
		Example: `  central mode
  central mode solo
  central mode team --url http://10.0.0.5:8004`,
		Run: runMode,
	}
	cmd.Flags().StringVar(&modeTeamURL, "url", "", "VPS API URL (TEAM mode only)")
	return cmd
}

func runMode(cmd *cobra.Command, args []string) {
	rt, err := config.LoadRuntimeConfig()
	if err != nil {
		rt = &config.RuntimeConfig{Mode: config.ModeSolo}
	}

	if len(args) == 0 {
		// Print current mode
		fmt.Println(string(rt.Mode))
		return
	}

	sub := strings.ToLower(args[0])
	switch sub {
	case "solo":
		if rt.Mode == config.ModeSolo {
			fmt.Println("Already in SOLO mode.")
			return
		}
		rt.Mode = config.ModeSolo
		rt.Team = config.TeamConfig{}
		if err := config.SaveRuntimeConfig(rt); err != nil {
			fmt.Fprintf(os.Stderr, "Error saving config: %v\n", err)
			os.Exit(1)
		}
		fmt.Println("Switched to SOLO mode. Restart central to apply.")

	case "team":
		if modeTeamURL != "" {
			rt.Team.APIURL = modeTeamURL
		}
		if rt.Team.APIURL == "" {
			fmt.Fprintln(os.Stderr, "TEAM mode requires an API URL. Use --url or set it in config.toml.")
			fmt.Fprintln(os.Stderr, "Example: central mode team --url http://vps.example.com:8004")
			os.Exit(1)
		}
		rt.Mode = config.ModeTeam
		if err := config.SaveRuntimeConfig(rt); err != nil {
			fmt.Fprintf(os.Stderr, "Error saving config: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Switched to TEAM mode (API: %s). Restart central to apply.\n", rt.Team.APIURL)

	default:
		fmt.Fprintf(os.Stderr, "Unknown mode: %s. Use 'solo' or 'team'.\n", sub)
		os.Exit(1)
	}
}
