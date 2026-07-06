package commands

import (
	"fmt"
	"os"
	"time"

	"github.com/centralchurch/central-cli/internal/executor"
	"github.com/spf13/cobra"
)

func daemonCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "daemon",
		Short: "Local executor — poll connector jobs (file + shell)",
		Run: func(cmd *cobra.Command, args []string) {
			guardSolo("daemon")
			client, cfg := mustClient()
			workspace := cfg.WorkspacePath
			if workspace == "" {
				fmt.Fprintln(os.Stderr, "No workspace — run: central workspace .")
				os.Exit(1)
			}
			cid := cfg.ConnectorID
			if err := client.ConnectorRegister(cid); err != nil {
				fmt.Fprintf(os.Stderr, "register: %v (retrying)\n", err)
			}
			fmt.Printf("Daemon running (connector=%s workspace=%s)\n", cid, workspace)
			for {
				if err := client.ConnectorHeartbeat(cid); err != nil {
					_ = client.ConnectorRegister(cid)
				}
				jobs, err := client.PollJobs(cid)
				if err != nil {
					fmt.Fprintf(os.Stderr, "poll: %v\n", err)
					time.Sleep(2 * time.Second)
					continue
				}
				for _, job := range jobs {
					jobID, _ := job["job_id"].(string)
					actionID, _ := job["action_id"].(string)
					payload, _ := job["payload"].(map[string]any)
					result, status := executor.Execute(actionID, payload, workspace)
					submitted := false
					for attempt := 1; attempt <= 3; attempt++ {
						if err := client.SubmitJobResult(jobID, cid, status, result); err != nil {
							fmt.Fprintf(os.Stderr, "result %s attempt %d: %v\n", jobID, attempt, err)
							time.Sleep(time.Duration(attempt) * time.Second)
							continue
						}
						submitted = true
						break
					}
					if submitted {
						fmt.Printf("job %s %s → %s\n", jobID, actionID, status)
					} else {
						fmt.Fprintf(os.Stderr, "job %s %s failed to submit result after retries\n", jobID, actionID)
					}
				}
				time.Sleep(1 * time.Second)
			}
		},
	}
}
