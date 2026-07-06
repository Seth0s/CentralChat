package ui

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/centralchurch/central-cli/internal/config"
)

type daemonState string

const (
	daemonOffline  daemonState = "offline"
	daemonStarting daemonState = "starting"
	daemonOnline   daemonState = "online"
	daemonError    daemonState = "error"
)

type DaemonManager struct {
	state   daemonState
	lastErr string
}

func daemonPIDPath() (string, error) {
	dir, err := config.ConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "daemon.pid"), nil
}

func readDaemonPID() (int, bool) {
	p, err := daemonPIDPath()
	if err != nil {
		return 0, false
	}
	data, err := os.ReadFile(p)
	if err != nil {
		return 0, false
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || pid <= 0 {
		return 0, false
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return 0, false
	}
	// Signal 0 checks existence on Unix.
	if err := proc.Signal(syscall.Signal(0)); err != nil {
		return 0, false
	}
	return pid, true
}

func (d *DaemonManager) Refresh() {
	if _, ok := readDaemonPID(); ok {
		d.state = daemonOnline
		d.lastErr = ""
		return
	}
	if d.state == daemonStarting {
		return
	}
	d.state = daemonOffline
}

func (d *DaemonManager) Start() error {
	if _, ok := readDaemonPID(); ok {
		d.state = daemonOnline
		return nil
	}
	exe, err := os.Executable()
	if err != nil {
		d.state = daemonError
		d.lastErr = err.Error()
		return err
	}
	d.state = daemonStarting
	dir, err := config.ConfigDir()
	if err != nil {
		d.state = daemonError
		d.lastErr = err.Error()
		return err
	}
	logPath := filepath.Join(dir, "daemon.log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		d.state = daemonError
		d.lastErr = err.Error()
		return err
	}
	cmd := exec.Command(exe, "daemon")
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	if err := cmd.Start(); err != nil {
		d.state = daemonError
		d.lastErr = err.Error()
		return err
	}
	pidPath, _ := daemonPIDPath()
	_ = os.WriteFile(pidPath, []byte(strconv.Itoa(cmd.Process.Pid)), 0o600)
	go func() {
		time.Sleep(2 * time.Second)
		d.Refresh()
	}()
	return nil
}

func (d *DaemonManager) Chip() string {
	switch d.state {
	case daemonOnline:
		return "● daemon online"
	case daemonStarting:
		return "◐ daemon a arrancar"
	case daemonError:
		return "⚠ daemon erro"
	default:
		return "○ daemon offline"
	}
}

func (d *DaemonManager) Detail() string {
	if d.lastErr != "" {
		return d.lastErr
	}
	return ""
}

func (d *DaemonManager) LogTail(lines int) string {
	dir, err := config.ConfigDir()
	if err != nil {
		return ""
	}
	data, err := os.ReadFile(filepath.Join(dir, "daemon.log"))
	if err != nil {
		return "(sem logs)"
	}
	parts := strings.Split(string(data), "\n")
	if len(parts) > lines {
		parts = parts[len(parts)-lines:]
	}
	return strings.Join(parts, "\n")
}

func (d *DaemonManager) Stop() error {
	pid, ok := readDaemonPID()
	if !ok {
		d.state = daemonOffline
		return nil
	}
	proc, _ := os.FindProcess(pid)
	if proc != nil {
		_ = proc.Kill()
	}
	pidPath, _ := daemonPIDPath()
	_ = os.Remove(pidPath)
	d.state = daemonOffline
	return nil
}

func daemonGateMessage(d *DaemonManager) string {
	return fmt.Sprintf("%s\n\n[Enter] iniciar daemon · [s] continuar sem daemon (read-only) · [Esc] voltar", d.Chip())
}
