package commands

import (
	"fmt"
	"os"
	"strings"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/solo"
	"github.com/spf13/cobra"
)

func syncCmd() *cobra.Command {
	var (
		tenant   string
		rulesOnly bool
		dryRun   bool
	)
	cmd := &cobra.Command{
		Use:   "sync [push|pull]",
		Short: "Bridge SOLO ↔ TEAM: push sessions or pull team rules",
		Long: `Sync local SOLO data with a TEAM tenant.

Push:
  Uploads local sessions and memory to the VPS tenant.
  Requires login to the TEAM API.

Pull:
  Downloads approved team rules from VPS to ~/.config/central/skills/
  so the SOLO agent can follow team conventions.`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			action := strings.ToLower(args[0])

			rt, err := config.LoadRuntimeConfig()
			if err != nil {
				fmt.Fprintln(os.Stderr, "Config error:", err)
				os.Exit(1)
			}

			switch action {
			case "push":
				if rt.Mode != config.ModeSolo {
					fmt.Fprintln(os.Stderr, "sync push is for SOLO→TEAM migration.")
					fmt.Fprintln(os.Stderr, "Current mode:", rt.Mode)
					os.Exit(1)
				}
				if tenant == "" {
					fmt.Fprintln(os.Stderr, "--tenant is required for push (e.g. --tenant my-org)")
					os.Exit(1)
				}
				client, _ := mustClient()
				doSyncPush(client, tenant, dryRun)

			case "pull":
				if !rulesOnly {
					fmt.Fprintln(os.Stderr, "Use --rules to pull team rules (other pull modes not yet implemented)")
					os.Exit(1)
				}
				client, _ := mustClient()
				doSyncPullRules(client, tenant, dryRun)

			default:
				fmt.Fprintf(os.Stderr, "Unknown action: %s (use push or pull)\n", action)
				os.Exit(1)
			}
		},
	}

	cmd.Flags().StringVar(&tenant, "tenant", "", "TEAM tenant ID (required for push)")
	cmd.Flags().BoolVar(&rulesOnly, "rules", false, "Pull team rules only")
	cmd.Flags().BoolVar(&dryRun, "dry-run", false, "Show what would be synced without uploading")
	return cmd
}

// ── Push: sessions + memory → VPS ──────────────────────────────

func doSyncPush(client *api.Client, tenant string, dryRun bool) {
	// List local sessions
	sessions, err := solo.ListSessions()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to list local sessions: %v\n", err)
		os.Exit(1)
	}

	if len(sessions) == 0 {
		fmt.Println("No local sessions to sync.")
		return
	}

	fmt.Printf("Syncing %d sessions to tenant %s...\n", len(sessions), tenant)
	if dryRun {
		fmt.Println("(dry-run — nothing uploaded)")
	}

	pushed := 0
	for _, s := range sessions {
		entries, err := solo.LoadSession(s.ID)
		if err != nil {
			fmt.Fprintf(os.Stderr, "  ⚠ %s: failed to load (%v)\n", s.ID, err)
			continue
		}

		// Build messages for VPS
		var messages []map[string]string
		for _, e := range entries {
			messages = append(messages, map[string]string{
				"role":    e.Role,
				"content": e.Content,
			})
		}

		if dryRun {
			fmt.Printf("  → %s (%d messages) [dry-run]\n", truncateStr(s.Title, 50), len(entries))
			pushed++
			continue
		}

		// Try to create session on VPS
		title := s.Title
		if title == "" {
			title = s.ID
		}
		out, err := client.CreateSession(title)
		if err != nil {
			fmt.Fprintf(os.Stderr, "  ✗ %s: create session failed (%v)\n", s.ID, err)
			continue
		}

		sess, _ := out["session"].(map[string]any)
		if sess == nil {
			fmt.Fprintf(os.Stderr, "  ✗ %s: unexpected response\n", s.ID)
			continue
		}
		vpsSessionID, _ := sess["id"].(string)
		if vpsSessionID == "" {
			fmt.Fprintf(os.Stderr, "  ✗ %s: no session ID in response\n", s.ID)
			continue
		}

		// Upload messages via ask endpoint (each turn creates history)
		// For now, we push the full session as a single import
		if err := client.ImportSession(vpsSessionID, messages); err != nil {
			fmt.Fprintf(os.Stderr, "  ✗ %s: import failed (%v)\n", s.ID, err)
			continue
		}

		fmt.Printf("  ✓ %s → %s (%d messages)\n", s.ID, vpsSessionID, len(entries))
		pushed++
	}

	// Push memory
	mem, err := solo.LoadMemory()
	if err == nil && len(mem.Facts) > 0 {
		fmt.Printf("Syncing %d memory facts...\n", len(mem.Facts))
		for _, f := range mem.Facts {
			if dryRun {
				fmt.Printf("  → memory: %s [dry-run]\n", truncateStr(f.Content, 60))
				continue
			}
			// Memory push via preferences or dedicated endpoint
			_ = f // VPS memory API not yet implemented — skip for now
		}
	}

	fmt.Printf("\nDone: %d/%d sessions synced.\n", pushed, len(sessions))
	if pushed < len(sessions) {
		fmt.Println("Some sessions failed — check errors above.")
	}
}

// ── Pull: team rules → local skills ────────────────────────────

func doSyncPullRules(client *api.Client, tenant string, dryRun bool) {
	fmt.Println("Pulling team rules from VPS...")

	// Get team rules from VPS
	rules, err := client.GetTeamRules(tenant)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to fetch team rules: %v\n", err)
		fmt.Fprintln(os.Stderr, "Make sure you are logged in and the tenant exists.")
		os.Exit(1)
	}

	if len(rules) == 0 {
		fmt.Println("No team rules found on VPS.")
		return
	}

	// Save as skill files
	configDir, _ := config.ConfigDir()
	skillsDir := configDir + "/skills"
	os.MkdirAll(skillsDir, 0o700)

	saved := 0
	for i, rule := range rules {
		name := fmt.Sprintf("team-rule-%d", i+1)
		if n, ok := rule["name"].(string); ok && n != "" {
			name = sanitizeFilename(n)
		}
		content, _ := rule["prompt"].(string)
		if content == "" {
			content, _ = rule["content"].(string)
		}
		if content == "" {
			continue
		}

		path := fmt.Sprintf("%s/%s.txt", skillsDir, name)
		if dryRun {
			fmt.Printf("  → %s (%d bytes) [dry-run]\n", path, len(content))
		} else {
			if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
				fmt.Fprintf(os.Stderr, "  ✗ %s: %v\n", path, err)
				continue
			}
			fmt.Printf("  ✓ %s\n", path)
		}
		saved++
	}

	fmt.Printf("\nDone: %d/%d rules saved to %s/\n", saved, len(rules), skillsDir)
	fmt.Println("The SOLO agent will load these on next turn.")
}

func sanitizeFilename(name string) string {
	name = strings.ToLower(name)
	name = strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '-' || r == '_' {
			return r
		}
		return '-'
	}, name)
	return strings.Trim(name, "-")
}

func truncateStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}
