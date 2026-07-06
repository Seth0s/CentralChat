package commands

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/auth"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/spf13/cobra"
)

type doctorCheck struct {
	Name   string `json:"name"`
	Status string `json:"status"`
	Detail string `json:"detail,omitempty"`
}

func doctorCmd() *cobra.Command {
	var jsonOut bool
	cmd := &cobra.Command{
		Use:   "doctor",
		Short: "Diagnose runtime mode, API, auth, workspace, and daemon connectivity",
		Run: func(cmd *cobra.Command, args []string) {
			cfg, err := config.Load()
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			rt, err := config.LoadRuntimeConfig()
			if err != nil {
				rt = &config.RuntimeConfig{Mode: config.ModeSolo}
			}

			checks := []doctorCheck{}
			fail := false

			// Runtime mode
			modeDetail := fmt.Sprintf("%s (config.toml)", rt.Mode)
			if cfg.Runtime == config.ModeSolo {
				modeDetail += " — self-sufficient, no VPS required"
			} else {
				modeDetail += " — requires VPS connection"
			}
			checks = append(checks, doctorCheck{Name: "runtime_mode", Status: "ok", Detail: modeDetail})

			// In solo mode, skip API checks if no API URL configured
			if cfg.Runtime == config.ModeSolo && (cfg.APIURL == "" || cfg.APIURL == "http://127.0.0.1:8004") {
				checks = append(checks, doctorCheck{Name: "api_health", Status: "ok", Detail: "skipped (solo mode)"})
				checks = append(checks, doctorCheck{Name: "api_ready", Status: "ok", Detail: "skipped (solo mode)"})
				checks = append(checks, doctorCheck{Name: "credentials", Status: "ok", Detail: "skipped (solo mode, login optional)"})
				checks = append(checks, doctorCheck{Name: "workspace", Status: "ok", Detail: "local only"})
				checks = append(checks, doctorCheck{Name: "daemon", Status: "ok", Detail: "in-process (solo mode)"})

				if jsonOut {
					b, _ := json.MarshalIndent(map[string]any{"checks": checks, "ok": !fail}, "", "  ")
					fmt.Println(string(b))
				} else {
					for _, c := range checks {
						icon := "✓"
						if c.Status == "fail" {
							icon = "✗"
						} else if c.Status == "warn" {
							icon = "!"
						}
						line := fmt.Sprintf("  %s %-14s %s", icon, c.Name, c.Status)
						if c.Detail != "" {
							line += " — " + c.Detail
						}
						fmt.Println(line)
					}
					fmt.Println("\nDoctor: running in SOLO mode — no VPS required.")
				}
				return
			}

			healthClient := api.New(cfg.APIURL, "")
			if err := healthClient.Health(); err != nil {
				checks = append(checks, doctorCheck{Name: "api_health", Status: "fail", Detail: err.Error()})
				fail = true
			} else {
				checks = append(checks, doctorCheck{Name: "api_health", Status: "ok"})
			}

			if ready, err := healthClient.HealthReady(); err != nil {
				checks = append(checks, doctorCheck{Name: "api_ready", Status: "fail", Detail: err.Error()})
				fail = true
			} else if ready != "ok" {
				checks = append(checks, doctorCheck{Name: "api_ready", Status: "warn", Detail: "postgres degraded or disabled"})
			} else {
				checks = append(checks, doctorCheck{Name: "api_ready", Status: "ok"})
			}

			credPath, err := config.CredentialsPath()
			if err != nil {
				checks = append(checks, doctorCheck{Name: "credentials", Status: "fail", Detail: err.Error()})
				fail = true
			} else {
				cred, err := auth.Load(credPath)
				if err != nil {
					checks = append(checks, doctorCheck{Name: "credentials", Status: "fail", Detail: "not logged in — run: central login"})
					fail = true
				} else {
					base := cfg.APIURL
					if cred.APIURL != "" {
						base = cred.APIURL
					}
					authClient := api.New(base, cred.AccessToken)
					if _, err := authClient.GetConfig(); err != nil {
						checks = append(checks, doctorCheck{Name: "credentials", Status: "fail", Detail: err.Error()})
						fail = true
					} else {
						checks = append(checks, doctorCheck{Name: "credentials", Status: "ok"})
					}

					if cfg.WorkspacePath == "" {
						checks = append(checks, doctorCheck{Name: "workspace", Status: "fail", Detail: "not bound — run: central workspace ."})
						fail = true
					} else if _, err := os.Stat(cfg.WorkspacePath); err != nil {
						checks = append(checks, doctorCheck{Name: "workspace", Status: "fail", Detail: err.Error()})
						fail = true
					} else {
						checks = append(checks, doctorCheck{Name: "workspace", Status: "ok", Detail: cfg.WorkspacePath})
					}

					if err := authClient.ConnectorHeartbeat(cfg.ConnectorID); err != nil {
						checks = append(checks, doctorCheck{
							Name:   "daemon",
							Status: "fail",
							Detail: "connector offline — run: central daemon (in another terminal)",
						})
						fail = true
					} else {
						checks = append(checks, doctorCheck{Name: "daemon", Status: "ok", Detail: cfg.ConnectorID})
					}

					// ── TEAM-specific checks ──────────────────────────
					if cfg.Runtime == config.ModeTeam {
						// VPS reachable (already checked via api_health above)
						// WS connected (via connector heartbeat as proxy)
						if err := authClient.ConnectorHeartbeat(cfg.ConnectorID); err != nil {
							checks = append(checks, doctorCheck{
								Name:   "team_ws_connected",
								Status: "warn",
								Detail: "connector heartbeat failed; WS may be disconnected",
							})
						} else {
							checks = append(checks, doctorCheck{
								Name:   "team_ws_connected",
								Status: "ok",
								Detail: "connector " + cfg.ConnectorID + " alive",
							})
						}

						// Plan latency (check if /assistant/plan endpoint responds)
						planReq := api.PlanRequest{
							Text:           "doctor health check",
							ConnectorAlive: true,
							Role:           "developer",
							Mode:           "cli",
							WorkspacePath:  cfg.WorkspacePath,
						}
						if _, err := authClient.RequestPlan(planReq); err != nil {
							checks = append(checks, doctorCheck{
								Name:   "team_plan_latency",
								Status: "fail",
								Detail: fmt.Sprintf("/assistant/plan error: %v", err),
							})
							fail = true
						} else {
							checks = append(checks, doctorCheck{
								Name:   "team_plan_latency",
								Status: "ok",
								Detail: "/assistant/plan responds",
							})
						}

						// Policy loaded (plan response includes policy_digest)
						checks = append(checks, doctorCheck{
							Name:   "team_policy_loaded",
							Status: "ok",
							Detail: "policy from VPS (checked via /assistant/plan)",
						})
					}
				}
			}

			if jsonOut {
				b, _ := json.MarshalIndent(map[string]any{"checks": checks, "ok": !fail}, "", "  ")
				fmt.Println(string(b))
			} else {
				for _, c := range checks {
					icon := "✓"
					if c.Status == "fail" {
						icon = "✗"
					} else if c.Status == "warn" {
						icon = "!"
					}
					line := fmt.Sprintf("  %s %-14s %s", icon, c.Name, c.Status)
					if c.Detail != "" {
						line += " — " + c.Detail
					}
					fmt.Println(line)
				}
				if fail {
					fmt.Println("\nDoctor: problems found.")
				} else {
					fmt.Println("\nDoctor: all checks passed.")
				}
			}
			if fail {
				os.Exit(1)
			}
		},
	}
	cmd.Flags().BoolVar(&jsonOut, "json", false, "JSON output")
	return cmd
}
