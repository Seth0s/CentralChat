package ui

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/solo"
	"github.com/centralchurch/central-cli/internal/websearch"
)

type agentsLoadedMsg struct {
	Lines []string
	Err   error
}

type memoryStatusMsg struct {
	Text string
	Err  error
}

type sessionListResultMsg struct {
	Lines []string
	Err   error
}

type doctorMsg struct {
	Text string
	Err  error
}

func (m model) loadAgentsCmd(args []string) tea.Cmd {
	client := m.client
	return func() tea.Msg {
		out, err := client.ListTeamAgents("published")
		if err != nil {
			return agentsLoadedMsg{Err: err}
		}
		items, _ := out["items"].([]any)
		var lines []string
		for _, it := range items {
			row, ok := it.(map[string]any)
			if !ok {
				continue
			}
			name, _ := row["name"].(string)
			if name == "" {
				continue
			}
			lines = append(lines, name)
		}
		if len(args) >= 2 && strings.EqualFold(args[0], "use") {
			name := args[1]
			_ = config.SaveActiveAgent(name)
			return agentsLoadedMsg{Lines: []string{"Active agent: " + name}}
		}
		if len(lines) == 0 {
			return agentsLoadedMsg{Lines: []string{"No published agents."}}
		}
		return agentsLoadedMsg{Lines: append([]string{"Agents:"}, lines...)}
	}
}

func (m model) memoryStatusCmd() tea.Cmd {
	client := m.client

	// SOLO mode: read from local SQLite
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			mem, err := solo.ListMemory()
			if err != nil {
				return memoryStatusMsg{Err: err}
			}
			if len(mem) == 0 {
				return memoryStatusMsg{Text: "No local memory."}
			}
			var parts []string
			for i, entry := range mem {
				if i >= 10 {
					parts = append(parts, fmt.Sprintf("... and %d more", len(mem)-10))
					break
				}
				parts = append(parts, entry)
			}
			return memoryStatusMsg{Text: strings.Join(parts, "\n")}
		}
	}

	return func() tea.Msg {
		out, err := client.GetPreferences()
		if err != nil {
			return memoryStatusMsg{Err: err}
		}
		prefs, _ := out["assistant_preferences"].(map[string]any)
		if len(prefs) == 0 {
			return memoryStatusMsg{Text: "No preferences loaded."}
		}
		var parts []string
		for _, k := range []string{"default_include_memory_recall", "default_include_long_session_memory", "default_include_host_context"} {
			if v, ok := prefs[k]; ok {
				parts = append(parts, fmt.Sprintf("%s: %v", k, v))
			}
		}
		return memoryStatusMsg{Text: strings.Join(parts, "\n")}
	}
}

func (m model) sessionListCmd() tea.Cmd {
	client := m.client

	// SOLO mode: TEAM-only command
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			return sessionListResultMsg{Lines: []string{"Use Hub (Ctrl+H) to manage local sessions."}}
		}
	}

	return func() tea.Msg {
		out, err := client.ListSessions()
		if err != nil {
			return sessionListResultMsg{Err: err}
		}
		items, _ := out["items"].([]any)
		var lines []string
		for _, it := range items {
			row, ok := it.(map[string]any)
			if !ok {
				continue
			}
			id, _ := row["id"].(string)
			title, _ := row["title"].(string)
			lines = append(lines, trim(title, 40)+"  "+shortID(id))
		}
		if len(lines) == 0 {
			return sessionListResultMsg{Lines: []string{"No sessions."}}
		}
		return sessionListResultMsg{Lines: append([]string{"Sessions:"}, lines...)}
	}
}

func (m model) approveListCmd() tea.Cmd {
	client := m.client
	return func() tea.Msg {
		out, err := client.ListApprovals("pending")
		if err != nil {
			return sessionListResultMsg{Err: err}
		}
		items, _ := out["items"].([]any)
		var lines []string
		for _, it := range items {
			row, ok := it.(map[string]any)
			if !ok {
				continue
			}
			id, _ := row["id"].(string)
			sum, _ := row["summary"].(string)
			lines = append(lines, id+"  "+trim(sum, 50))
		}
		if len(lines) == 0 {
			return sessionListResultMsg{Lines: []string{"No pending approvals."}}
		}
		return sessionListResultMsg{Lines: append([]string{"Approvals:"}, lines...)}
	}
}

func (m model) doctorCmd() tea.Cmd {
	client := m.client

	// SOLO mode: show local health
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			var parts []string
			parts = append(parts, "SOLO mode — local runtime")
			if m.soloAgent != nil && m.soloAgent.Provider != nil {
				parts = append(parts, fmt.Sprintf("Provider: %s (%s)", m.soloAgent.Provider.Kind, m.soloAgent.Provider.Model))
			} else {
				parts = append(parts, "Provider: not configured")
			}
			parts = append(parts, fmt.Sprintf("Workspace: %s", m.runtime.WorkspacePath))
			// Browser-Use status
			if websearch.NativeAvailable() {
				parts = append(parts, "Browser-Use: ✓ (native)")
			} else if websearch.ContainerAvailable() {
				parts = append(parts, "Browser-Use: ✓ (container)")
			} else if websearch.DockerAvailable() {
				parts = append(parts, "Browser-Use: ↺ (starts on first search)")
			} else {
				parts = append(parts, "Browser-Use: ✗ (pip install browser-use or docker)")
			}
			return doctorMsg{Text: strings.Join(parts, "\n")}
		}
	}

	return func() tea.Msg {
		var parts []string
		if err := client.Health(); err != nil {
			parts = append(parts, "API: ✗ "+err.Error())
		} else {
			parts = append(parts, "API: ✓")
		}
		if st, err := client.HealthReady(); err != nil {
			parts = append(parts, "Ready: ✗")
		} else {
			parts = append(parts, "Ready: "+st)
		}
		cat, err := client.GetCloudModels()
		if err == nil {
			if g, ok := cat["governance"].(map[string]any); ok {
				parts = append(parts, fmt.Sprintf("Modelos catálogo: %v", g["catalog_count"]))
				parts = append(parts, fmt.Sprintf("Providers: %v/%v", g["providers_configured"], g["providers_total"]))
			}
		}
		dm := DaemonManager{}
		dm.Refresh()
		parts = append(parts, dm.Chip())
		return doctorMsg{Text: strings.Join(parts, "\n")}
	}
}

// SessionMeta mirrors backend GET /ui/chat-sessions item.
type SessionMeta struct {
	ID           string
	Title        string
	MessageCount int
	Pinned       bool
	UpdatedAt    string
}

type sessionListMsg struct {
	Sessions             []SessionMeta
	SessionsEnabled      bool
	Err                  error
}

func (m rootModel) loadSessionsCmd() tea.Cmd {
	client := m.client
	// SOLO mode: load from local SQLite
	if m.cfg.Runtime == config.ModeSolo {
		return func() tea.Msg {
			sessions, err := solo.ListSessions()
			if err != nil {
				return sessionListMsg{Err: err}
			}
			var items []SessionMeta
			for _, s := range sessions {
				items = append(items, SessionMeta{
					ID:           s.ID,
					Title:        s.Title,
					MessageCount: s.MessageCount,
					UpdatedAt:    s.UpdatedAt.Format("2006-01-02 15:04"),
				})
			}
			return sessionListMsg{Sessions: items, SessionsEnabled: true}
		}
	}
	return func() tea.Msg {
		if client == nil {
			return sessionListMsg{Err: fmt.Errorf("sem cliente")}
		}
		out, err := client.ListSessions()
		if err != nil {
			return sessionListMsg{Err: err}
		}
		items, _ := out["items"].([]any)
		var sessions []SessionMeta
		for _, it := range items {
			row, ok := it.(map[string]any)
			if !ok {
				continue
			}
			id, _ := row["id"].(string)
			if id == "" {
				continue
			}
			title, _ := row["title"].(string)
			mc, _ := row["message_count"].(float64)
			pinned, _ := row["pinned"].(bool)
			updated, _ := row["updated_at"].(string)
			sessions = append(sessions, SessionMeta{
				ID: id, Title: title,
				MessageCount: int(mc), Pinned: pinned,
				UpdatedAt: updated,
			})
		}
		enabled, _ := out["chat_sessions_enabled"].(bool)
		return sessionListMsg{Sessions: sessions, SessionsEnabled: enabled}
	}
}

// WorkItemMeta mirrors backend GET /ui/work-items item.
type WorkItemMeta struct {
	ID        string
	Title     string
	Status    string
	Priority  string
}

type workItemsLoadedMsg struct {
	Items []WorkItemMeta
	Err   error
}

func (m rootModel) loadWorkItemsCmd() tea.Cmd {
	client := m.client
	// SOLO mode: load from local work queue
	if m.cfg.Runtime == config.ModeSolo {
		return func() tea.Msg {
			items, err := solo.ListWorkItems("")
			if err != nil {
				return workItemsLoadedMsg{Err: err}
			}
			var result []WorkItemMeta
			for _, wi := range items {
				result = append(result, WorkItemMeta{
					ID:     wi.ID,
					Title:  wi.Title,
					Status: wi.Status,
				})
			}
			return workItemsLoadedMsg{Items: result}
		}
	}
	return func() tea.Msg {
		if client == nil {
			return workItemsLoadedMsg{Err: fmt.Errorf("sem cliente")}
		}
		out, err := client.ListWorkItems("")
		if err != nil {
			return workItemsLoadedMsg{Err: err}
		}
		items, _ := out["items"].([]any)
		var result []WorkItemMeta
		for _, it := range items {
			row, ok := it.(map[string]any)
			if !ok {
				continue
			}
			id, _ := row["id"].(string)
			title, _ := row["title"].(string)
			status, _ := row["status"].(string)
			priority, _ := row["priority"].(string)
			if id == "" {
				continue
			}
			result = append(result, WorkItemMeta{ID: id, Title: title, Status: status, Priority: priority})
		}
		return workItemsLoadedMsg{Items: result}
	}
}

type sessionDeletedMsg struct {
	Err error
}

func (m rootModel) deleteSessionCmd(sid string) tea.Cmd {
	client := m.client
	return func() tea.Msg {
		if client == nil {
			return sessionDeletedMsg{Err: fmt.Errorf("sem cliente")}
		}
		err := client.DeleteSession(sid)
		return sessionDeletedMsg{Err: err}
	}
}

type sessionOpenMsg struct {
	surfaceLoadedMsg
	Err error
}

func (m model) sessionOpenCmd(id string) tea.Cmd {
	sid := strings.TrimSpace(id)
	client := m.client
	return func() tea.Msg {
		if sid == "" {
			return sessionOpenMsg{Err: fmt.Errorf("session_id_obrigatorio")}
		}
		snap, err := client.GetSurface(sid)
		if err != nil {
			return sessionOpenMsg{Err: err}
		}
		msg := surfaceLoadedMsg{SessionID: sid, Phase: phaseIdle}
		if t, ok := snap["title"].(string); ok {
			msg.Title = t
		}
		if ph, ok := snap["session_phase"].(string); ok && ph != "" {
			msg.Phase = sessionPhase(ph)
		}
		if raw, ok := snap["messages"].([]any); ok {
			for _, item := range raw {
				row, ok := item.(map[string]any)
				if !ok {
					continue
				}
				role, _ := row["role"].(string)
				content, _ := row["content"].(string)
				if role != "" && content != "" {
					msg.Msgs = append(msg.Msgs, chatLine{role: role, content: content})
				}
			}
		}
		_ = config.SaveActiveSession(sid)
		return sessionOpenMsg{surfaceLoadedMsg: msg}
	}
}

func shortID(id string) string {
	if len(id) <= 8 {
		return id
	}
	return id[:8]
}

// saveTurnSnapshot captures pre-turn state for /undo.
func (m *model) saveTurnSnapshot() {
	msgs := make([]chatLine, len(m.messages))
	copy(msgs, m.messages)
	m.turnSnap = &turnSnapshot{
		messages:      msgs,
		stickyPrompt:  m.stickyPrompt,
		stickyMode:    m.stickyPromptMode,
		phase:         m.phase,
		approval:      m.approval,
		clarify:       m.clarify,
		statusLine:    m.statusLine,
		sessionID:     m.sessionID,
		errBar:        m.errBar,
		lastTurnDuration: m.lastTurnDuration,
	}
}

// restoreTurnSnapshot restores pre-turn state for /undo.
func (m *model) restoreTurnSnapshot() {
	if m.turnSnap == nil {
		return
	}
	s := m.turnSnap
	m.messages = s.messages
	m.stickyPrompt = s.stickyPrompt
	m.stickyPromptMode = s.stickyMode
	m.phase = s.phase
	m.approval = s.approval
	m.clarify = s.clarify
	m.statusLine = s.statusLine
	if s.sessionID != "" {
		m.sessionID = s.sessionID
	}
	m.errBar = s.errBar
	m.lastTurnDuration = s.lastTurnDuration
	m.streaming = false
	m.streamingText = ""
	m.thinking = ""
	m.thinkingActive = false
	m.streamingThoughtOpen = false
	m.clarifyCustom = false
	m.pendingStreamReq = nil
	m.undoCount++
	m.turnSnap = nil
}

func (m *model) resetChatSessionState() {
	m.sessionID = ""
	m.sessionTitle = ""
	m.stickyPrompt = ""
	m.stickyPromptMode = modeBuild
	m.messages = nil
	m.streaming = false
	m.streamingText = ""
	m.thinking = ""
	m.thinkingActive = false
	m.thinkingStartedAt = time.Time{}
	m.streamingThoughtOpen = false
	m.phase = phaseIdle
	m.approval = nil
	m.clarify = nil
	m.clarifyCustom = false
	m.errBar = ""
	m.chatScrollOffset = 0
	m.pendingStreamReq = nil
	m.streamCh = nil
	m.lastTurnDuration = 0
	m.streamStartedAt = time.Time{}
	m.sessionStartedAt = time.Now()
}

func (m model) beginNewChatSession() (tea.Model, tea.Cmd) {
	if m.streaming {
		out := m
		out.statusLine = "Aguarda o stream terminar"
		return out, nil
	}
	out := m
	out.resetChatSessionState()
	out.statusLine = "Creating session…"
	return out, out.ensureSessionCmd("")
}
