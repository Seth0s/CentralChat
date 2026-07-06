// Package runtime — runtime status tracking for the TUI sidebar.
package runtime

import (
	"sync"
	"time"

	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/mem"
)

// RuntimeStatus holds live metrics about the agent runtime.
type RuntimeStatus struct {
	mu sync.Mutex

	CPUPercent float64
	MemUsedGB  float64
	MemTotalGB float64

	ActiveTools []ActiveTool
	RecentTools []ToolResult
	Background  []BgCommand

	PolicyStatus string
	ProviderInfo string

	// TEAM mode: WebSocket connection to VPS
	WSConnected bool
	WSUrl       string

	// TEAM mode: last plan latency
	LastPlanLatencyMs int64
	PlanCount         int

	// TEAM mode: policy loaded from VPS
	PolicyLoaded bool
}

// ActiveTool represents a tool currently executing.
type ActiveTool struct {
	Name      string
	Args      string
	StartTime time.Time
}

// BgCommand represents a background shell command.
type BgCommand struct {
	Command   string
	PID       int
	StartTime time.Time
	Done      bool
}

// NewRuntimeStatus creates a new status tracker.
func NewRuntimeStatus(policyStatus, providerInfo string) *RuntimeStatus {
	return &RuntimeStatus{
		PolicyStatus: policyStatus,
		ProviderInfo: providerInfo,
	}
}

// Collect refreshes CPU and memory metrics.
func (s *RuntimeStatus) Collect() {
	s.mu.Lock()
	defer s.mu.Unlock()

	if percent, err := cpu.Percent(0, false); err == nil && len(percent) > 0 {
		s.CPUPercent = percent[0]
	}
	if memInfo, err := mem.VirtualMemory(); err == nil {
		s.MemUsedGB = float64(memInfo.Used) / 1e9
		s.MemTotalGB = float64(memInfo.Total) / 1e9
	}
}

// AddActiveTool registers a tool that started executing.
func (s *RuntimeStatus) AddActiveTool(name, args string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ActiveTools = append(s.ActiveTools, ActiveTool{
		Name:      name,
		Args:      truncateStr(args, 40),
		StartTime: time.Now(),
	})
}

// RemoveActiveTool removes a tool from active and adds to recent.
func (s *RuntimeStatus) RemoveActiveTool(name string, result ToolResult) {
	s.mu.Lock()
	defer s.mu.Unlock()

	for i, t := range s.ActiveTools {
		if t.Name == name {
			s.ActiveTools = append(s.ActiveTools[:i], s.ActiveTools[i+1:]...)
			break
		}
	}
	s.RecentTools = append(s.RecentTools, result)
	if len(s.RecentTools) > 5 {
		s.RecentTools = s.RecentTools[len(s.RecentTools)-5:]
	}
}

// AddBackground registers a background command.
func (s *RuntimeStatus) AddBackground(command string, pid int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Background = append(s.Background, BgCommand{
		Command:   truncateStr(command, 50),
		PID:       pid,
		StartTime: time.Now(),
	})
}

// MarkBackgroundDone marks a background command as completed.
func (s *RuntimeStatus) MarkBackgroundDone(pid int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, bg := range s.Background {
		if bg.PID == pid {
			s.Background[i].Done = true
			break
		}
	}
}

// SetWSStatus updates the WebSocket connection status (TEAM mode).
func (s *RuntimeStatus) SetWSStatus(connected bool, url string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.WSConnected = connected
	s.WSUrl = url
}

// SetPlanLatency records the last plan request latency (TEAM mode).
func (s *RuntimeStatus) SetPlanLatency(ms int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.LastPlanLatencyMs = ms
	s.PlanCount++
}

// SetPolicyLoaded marks whether a TEAM policy was loaded from VPS.
func (s *RuntimeStatus) SetPolicyLoaded(loaded bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.PolicyLoaded = loaded
}

// Snapshot returns a copy of the current status (thread-safe).
func (s *RuntimeStatus) Snapshot() RuntimeStatus {
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := *s
	cp.ActiveTools = make([]ActiveTool, len(s.ActiveTools))
	copy(cp.ActiveTools, s.ActiveTools)
	cp.RecentTools = make([]ToolResult, len(s.RecentTools))
	copy(cp.RecentTools, s.RecentTools)
	cp.Background = make([]BgCommand, len(s.Background))
	copy(cp.Background, s.Background)
	return cp
}
