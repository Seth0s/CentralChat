package commands

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
	"time"

	"github.com/centralchurch/central-cli/internal/config"
	"github.com/spf13/cobra"
)

const soloDefaultPort = 9800

func serveCmd() *cobra.Command {
	var (
		port       int
		daemonize  bool
		backendDir string
	)
	cmd := &cobra.Command{
		Use:   "serve --local",
		Short: "[DEPRECATED] Start SOLO backend server (Python loopback)",
		Long: `DEPRECATED: The native Go AgentRuntime is now the default for SOLO mode.
This Python loopback server is no longer needed and will be removed.

To use SOLO mode:
  1. Set OPENROUTER_API_KEY or OLLAMA_URL in your environment
  2. Run: central
  3. The native Go runtime handles context assembly, inference, and tools.

If you still need the Python backend for testing:`,
		Run: func(cmd *cobra.Command, args []string) {
			rt, err := config.LoadRuntimeConfig()
			if err != nil {
				fmt.Fprintln(os.Stderr, "Config error:", err)
				os.Exit(1)
			}
			if rt.Mode != config.ModeSolo {
				fmt.Fprintln(os.Stderr, "serve --local is only available in SOLO mode.")
				fmt.Fprintln(os.Stderr, "Current mode:", rt.Mode)
				fmt.Fprintln(os.Stderr, "Set mode = 'solo' in ~/.config/central/config.toml")
				os.Exit(1)
			}

			// Resolve backend directory
			if backendDir == "" {
				// Try to find the CentralChat_Backend relative to the binary
				execPath, _ := os.Executable()
				candidates := []string{
					filepath.Join(filepath.Dir(execPath), "..", "..", "..", "vhosts", "CentralChat_Backend"),
					filepath.Join(os.Getenv("HOME"), "Workplace", "Projects", "CentralChat", "vhosts", "CentralChat_Backend"),
				}
				for _, c := range candidates {
					if info, err := os.Stat(filepath.Join(c, "app", "solo_server.py")); err == nil && !info.IsDir() {
						backendDir = c
						break
					}
				}
			}
			if backendDir == "" {
				fmt.Fprintln(os.Stderr, "Could not find CentralChat_Backend directory.")
				fmt.Fprintln(os.Stderr, "Set --backend-dir or run from the project root.")
				os.Exit(1)
			}

			pythonBin := os.Getenv("CENTRAL_PYTHON_BIN")
			if pythonBin == "" {
				pythonBin = "python"
			}

			srvArgs := []string{
				"-m", "app.solo_server",
				"--port", strconv.Itoa(port),
				"--host", "127.0.0.1",
			}

			fmt.Printf("Starting SOLO backend on 127.0.0.1:%d...\n", port)
			fmt.Printf("Backend dir: %s\n", backendDir)

			srvCmd := exec.Command(pythonBin, srvArgs...)
			srvCmd.Dir = backendDir
			srvCmd.Stdout = os.Stdout
			srvCmd.Stderr = os.Stderr
			srvCmd.Env = append(os.Environ(),
				"CENTRAL_DIR="+filepath.Join(os.Getenv("HOME"), ".central"),
				"CONTEXT_PIPELINE_ENABLED=1",
			)

			if daemonize {
				// Detach from terminal
				srvCmd.SysProcAttr = &syscall.SysProcAttr{
					Setsid: true,
				}
				if err := srvCmd.Start(); err != nil {
					fmt.Fprintln(os.Stderr, "Failed to start server:", err)
					os.Exit(1)
				}
				// Write PID
				configDir, _ := config.ConfigDir()
				pidFile := filepath.Join(configDir, "solo_server.pid")
				_ = os.WriteFile(pidFile, []byte(strconv.Itoa(srvCmd.Process.Pid)), 0o600)
				fmt.Printf("Server started (PID %d). Config: %s\n", srvCmd.Process.Pid, pidFile)
				fmt.Printf("API: http://127.0.0.1:%d\n", port)
				return
			}

			// Foreground: run until interrupted
			if err := srvCmd.Run(); err != nil {
				fmt.Fprintln(os.Stderr, "Server exited with error:", err)
				os.Exit(1)
			}
		},
	}

	cmd.Flags().IntVar(&port, "port", soloDefaultPort, "Port to listen on")
	cmd.Flags().BoolVar(&daemonize, "daemonize", false, "Run in background")
	cmd.Flags().StringVar(&backendDir, "backend-dir", "", "Path to CentralChat_Backend directory")

	return cmd
}

// WaitForSoloServer polls the health endpoint until the server is ready.
func WaitForSoloServer(port int, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	url := fmt.Sprintf("http://127.0.0.1:%d/health", port)
	for time.Now().Before(deadline) {
		resp, err := httpGet(url)
		if err == nil && resp != "" {
			return nil
		}
		time.Sleep(200 * time.Millisecond)
	}
	return fmt.Errorf("server did not become ready within %v", timeout)
}

func httpGet(url string) (string, error) {
	// Minimal HTTP GET without importing net/http in every build
	// Use exec curl as a simple fallback
	cmd := exec.Command("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url)
	out, err := cmd.Output()
	if err != nil {
		return "", err
	}
	return string(out), nil
}
