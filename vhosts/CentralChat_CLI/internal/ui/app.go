package ui

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/config"
	agentruntime "github.com/centralchurch/central-cli/internal/runtime"
	"github.com/centralchurch/central-cli/internal/solo"
	"github.com/centralchurch/central-cli/internal/inference"
)

type sessionPhase string

const (
	phaseIdle             sessionPhase = "idle"
	phaseStreaming        sessionPhase = "streaming"
	phaseWaitingApproval  sessionPhase = "waiting_approval"
	phaseWaitingClarify   sessionPhase = "waiting_clarify"
)

type chatLine struct {
	role        string
	content     string
	thought     string
	thoughtMs   int64
	thoughtOpen bool
	turnMode    interactionMode
	duration    time.Duration
}

// turnSnapshot saves state before each ask so /undo can restore it.
type turnSnapshot struct {
	messages      []chatLine
	stickyPrompt  string
	stickyMode    interactionMode
	phase         sessionPhase
	approval      *approvalCard
	clarify       *clarifyCard
	statusLine    string
	sessionID     string
	errBar        string
	lastTurnDuration time.Duration
}

type approvalCard struct {
	ID      string
	Action  string
	Summary string
	Command string
	Path    string
}

type clarifyCard struct {
	InterruptID string
	Question    string
	Choices     []string
}

type streamEventMsg struct {
	Event string
	Data  string
}

type streamDoneMsg struct{ Err error }

type streamStartedMsg struct {
	ch chan streamEventMsg
}

type tickMsg struct{}

type sidebarRefreshMsg struct {
	Workspace       string
	Branch          string
	DirtyCount      int
	Pending         int
	Model           string
	ModelScope      string
	InferenceDest   string
	AutoTier        string
	Temperature     float64
	Effort          string
	MaxTokens       int
	ConnectorOnline bool
	WorkQueueCount  int
	UsageTotalCost  float64
	ProviderRouting string
	ThinkingBudget int
	// SOLO runtime metrics
	RuntimeSnap *agentruntime.RuntimeStatus
	// TEAM mode WS status
	WSConnected bool
	WSUrl       string
	// TEAM mode plan metrics
	LastPlanLatencyMs int64
	PlanCount         int
	PolicyLoaded      bool
}

type surfaceLoadedMsg struct {
	SessionID string
	Title     string
	Phase     sessionPhase
	Msgs      []chatLine
	Clar      *clarifyCard
	Appr      *approvalCard
}

type surfaceLoadErrMsg struct{ Err error }

// RunOptions optional session to resume (from `central open` or active_session).
type RunOptions struct {
	SessionID string
	Title     string
}

// Run starts session TUI only (legacy `central tui`).
func Run(client *api.Client, cfg *config.Config, opts RunOptions) error {
	m := newModel(client, cfg, opts)
	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
	_, err := p.Run()
	return err
}

type model struct {
	client    *api.Client
	runtime   *config.Config
	tuiCfg    TUIConfig
	width     int
	height    int

	showSidebar    bool
	reasoningPanel string // open | collapsed | hidden (hidden → collapsed in panel)

	chromeRows         int
	skipSessionHeader  bool
	streamingThoughtOpen bool
	thinkingStartedAt  time.Time

	phase          sessionPhase
	sessionID      string
	sessionTitle   string
	modelName      string
	contextPct     int
	tokensIn       int
	tokensOut      int
	workspace      string
	branch         string
	dirtyCount     int
	pendingCount   int
	workQueueCount int
	usageTotalCost float64
	activity       []string
	toolLog        toolLog
	statusLine     string

	messages       []chatLine
	streamingText  string
	thinking       string
	thinkingActive bool

	approval       *approvalCard
	clarify        *clarifyCard
	clarifyCustom  bool

	paletteOpen    bool
	paletteItems   []string
	paletteIdx     int

	modelPickerOpen   bool
	modelPickerItems  []cloudModelRow
	modelPickerPage   int
	modelPickerAllowOK bool
	modelPickerProvider    string
	modelPickerProvidersCache []string
	modelPickerProvidersAPI    []providerInfo
	modelPickerFocus       string
	modelPickerSearch      textarea.Model
	providerPanel          PickerPanel
	modelPanel             PickerPanel

	// Agent picker
	agentPickerOpen      bool
	agentPickerItems     []agentRow
	agentPickerSkills    []skillRow
	agentPickerSkillSel  map[string]bool
	agentPickerFocus     string
	agentPanel           PickerPanel
	skillPanel           PickerPanel

	// Tools picker
	toolsPickerOpen  bool
	toolsPickerItems []toolRow
	toolsPanel       PickerPanel

	// Params picker
	paramsPickerOpen  bool
	paramsPickerItems []paramRow
	paramsPanel       PickerPanel

	inferenceDest     string
	autoTier          string
	providerRouting   string
	thinkingBudget    int
	temperature       float64
	effort            string
	maxTokens         int
	connectorOnline   bool
	sessionModelOverride string
	userDefaultModel  string

	slashPaletteOpen bool
	slashItems       []slashCommand
	slashIdx         int
	slashOff         int

	workspaceTabs []WorkspaceTab
	activeTabID   string
	requestHub    bool
	requestSetup  bool
	offlineMode   bool
	useAgentTools bool
	daemonChip    string
	loadingFrame  int
	spinnerFrame  int

	interactionMode   interactionMode
	sessionStartedAt  time.Time
	streamStartedAt   time.Time
	lastTurnDuration  time.Duration
	requestLogout     bool
	chatScrollOffset  int
	userScrolledUp   bool            // true when user manually scrolled away from bottom
	stickyPrompt      string          // last user prompt pinned at top (not session title)
	stickyPromptMode  interactionMode

	input textarea.Model
	streamCh chan streamEventMsg
	streaming bool
	errBar    string

	pendingStreamReq *api.AskRequest

	sessionToolNames  []string
	sessionSkillNames []string
	activeAgentName   string

	// /retry — last user prompt for resend
	lastPrompt      string
	lastPromptMode  interactionMode
	lastMedia       []api.MediaAttachment

	// /undo — snapshot before each turn
	turnSnap        *turnSnapshot
	undoCount       int
	lastRequestID   string  // for backend undo endpoint

	// Dynamic sticky: which user message is visible in the current viewport
	visibleTurnUserIdx int
	// Runtime badge: [SOLO] or [TEAM]
	runtimeBadge string

	// SOLO mode agent runtime (nil in TEAM mode)
	soloAgent *agentruntime.AgentRuntime

	// TEAM mode agent runtime (nil in SOLO mode)
	teamAgent *agentruntime.AgentRuntime

	// SOLO runtime metrics (always collected in SOLO mode)
	soloStatus *agentruntime.RuntimeStatus

	// TEAM mode runtime metrics
	teamStatus *agentruntime.RuntimeStatus

	// SOLO runtime metrics snapshot (updated by sidebar refresh)
	runtimeSnap *agentruntime.RuntimeStatus
}

func resolveSoloProvider() *inference.Provider {
	rt, err := config.LoadRuntimeConfig()
	if err != nil {
		return nil
	}
	pc, _ := rt.Solo.ActiveProvider()
	if pc == nil {
		return nil
	}
	return inference.NewProvider(inference.ProviderKind(pc.Kind), pc.BaseURL, pc.APIKey, pc.Model)
}

// switchToSolo activates SOLO mode from within a session.
func (m *model) switchToSolo() {
	if m.runtime.Runtime == config.ModeSolo {
		m.messages = append(m.messages, chatLine{role: "system", content: "Already in SOLO mode."})
		return
	}
	provider := resolveSoloProvider()
	if provider == nil {
		m.messages = append(m.messages, chatLine{role: "system", content: "Cannot switch to SOLO: no provider configured. Set OPENROUTER_API_KEY or OLLAMA_URL."})
		return
	}
	ctx := agentruntime.NewContextLite(m.runtime.WorkspacePath)
	ctx.AgentPrompt = agentruntime.LoadAgentPrompt("default")
	ctx.SkillPrompts = agentruntime.LoadSkillPrompts()
	ctx.DLPEnabled = true
	if policy, err := solo.LoadPolicy(); err == nil {
		ctx.Policy = policy
	}
	m.soloAgent = agentruntime.NewAgentRuntime(provider, ctx, m.runtime.WorkspacePath)
	m.soloAgent.Status = agentruntime.NewRuntimeStatus("enforced", string(provider.Kind))
	m.soloStatus = m.soloAgent.Status
	m.runtimeBadge = "SOLO"

	// Clear TEAM mode agent
	m.teamAgent = nil
	m.teamStatus = nil

	rt, _ := config.LoadRuntimeConfig()
	if rt != nil {
		rt.Mode = config.ModeSolo
		_ = config.SaveRuntimeConfig(rt)
	}
	m.messages = append(m.messages, chatLine{role: "system", content: "Switched to SOLO mode."})
}

// switchToTeam activates TEAM mode from within a session.
func (m *model) switchToTeam() {
	if m.runtime.Runtime == config.ModeTeam {
		m.messages = append(m.messages, chatLine{role: "system", content: "Already in TEAM mode."})
		return
	}
	// Verify VPS is reachable
	if m.client == nil || m.client.BaseURL == "" {
		m.messages = append(m.messages, chatLine{role: "system", content: "Cannot switch to TEAM: no API URL configured. Set CENTRAL_API_URL or login first."})
		return
	}
	m.soloAgent = nil
	m.runtimeBadge = "TEAM"

	// Create TeamBackend + AgentRuntime for hybrid inference
	provider := resolveSoloProvider()
	if provider != nil {
		ctx := agentruntime.NewContextLite(m.runtime.WorkspacePath)
		ctx.AgentPrompt = agentruntime.LoadAgentPrompt("default")
		ctx.SkillPrompts = agentruntime.LoadSkillPrompts()
		ctx.DLPEnabled = true
		if policy, err := solo.LoadPolicy(); err == nil {
			ctx.Policy = policy
		}
		backend := agentruntime.NewTeamBackend(m.runtime.WorkspacePath, provider, m.client)
		m.teamAgent = agentruntime.NewAgentRuntimeWithBackend(provider, ctx, m.runtime.WorkspacePath, backend)
		m.teamAgent.Status = agentruntime.NewRuntimeStatus("team", string(provider.Kind))
	}

	// Initialize TEAM status tracker
	m.teamStatus = agentruntime.NewRuntimeStatus("team", "vps")
	if m.client != nil {
		wsURL := m.client.BaseURL
		if strings.HasPrefix(wsURL, "https://") {
			wsURL = "wss://" + wsURL[8:] + "/ws/connector"
		} else if strings.HasPrefix(wsURL, "http://") {
			wsURL = "ws://" + wsURL[7:] + "/ws/connector"
		}
		m.teamStatus.SetWSStatus(false, wsURL)
	}

	rt, _ := config.LoadRuntimeConfig()
	if rt != nil {
		rt.Mode = config.ModeTeam
		_ = config.SaveRuntimeConfig(rt)
	}
	m.messages = append(m.messages, chatLine{role: "system", content: "Switched to TEAM mode. VPS: " + m.client.BaseURL})
}

func newModel(client *api.Client, runtime *config.Config, opts RunOptions) model {
	ti := styleSessionInput(textarea.New())
	ti.SetWidth(60)

	tcfg := LoadTUIConfig()
	applyTheme(tcfg.Theme)
	rp := normalizeReasoningPanel(tcfg.ReasoningPanel)

	badge := strings.ToUpper(string(runtime.Runtime))
	if badge == "" {
		badge = "SOLO"
	}

	var soloAgent *agentruntime.AgentRuntime
	var teamAgent *agentruntime.AgentRuntime
	var soloStatus *agentruntime.RuntimeStatus
	var teamStatus *agentruntime.RuntimeStatus
	if runtime.Runtime == config.ModeSolo {
		provider := resolveSoloProvider()
		// Always create context lite for policy + DLP
		ctx := agentruntime.NewContextLite(runtime.WorkspacePath)
		ctx.AgentPrompt = agentruntime.LoadAgentPrompt("default")
		ctx.SkillPrompts = agentruntime.LoadSkillPrompts()
		ctx.DLPEnabled = true
		// Load local policy
		if policy, err := solo.LoadPolicy(); err == nil {
			ctx.Policy = policy
		}
		if provider != nil {
			soloAgent = agentruntime.NewAgentRuntime(provider, ctx, runtime.WorkspacePath)
			soloAgent.Status = agentruntime.NewRuntimeStatus(
				"enforced", string(provider.Kind),
			)
		}
		// Always create a status tracker for sidebar metrics in SOLO mode
		if soloStatus == nil {
			soloStatus = agentruntime.NewRuntimeStatus("local", "solo")
		}
	} else {
		// TEAM mode: create TeamBackend + AgentRuntime and status tracker
		provider := resolveSoloProvider() // same provider concept for local inference
		ctx := agentruntime.NewContextLite(runtime.WorkspacePath)
		ctx.AgentPrompt = agentruntime.LoadAgentPrompt("default")
		ctx.SkillPrompts = agentruntime.LoadSkillPrompts()
		ctx.DLPEnabled = true
		if policy, err := solo.LoadPolicy(); err == nil {
			ctx.Policy = policy
		}

		teamStatus = agentruntime.NewRuntimeStatus("team", "vps")
		if provider != nil && client != nil {
			backend := agentruntime.NewTeamBackend(runtime.WorkspacePath, provider, client)
			teamAgent = agentruntime.NewAgentRuntimeWithBackend(provider, ctx, runtime.WorkspacePath, backend)
			teamAgent.Status = agentruntime.NewRuntimeStatus("team", string(provider.Kind))
		}

		if client != nil {
			wsURL := client.BaseURL
			if strings.HasPrefix(wsURL, "https://") {
				wsURL = "wss://" + wsURL[8:] + "/ws/connector"
			} else if strings.HasPrefix(wsURL, "http://") {
				wsURL = "ws://" + wsURL[7:] + "/ws/connector"
			}
			teamStatus.SetWSStatus(false, wsURL)
		}
	}

	return model{
		client:         client,
		runtime:        runtime,
		tuiCfg:         tcfg,
		showSidebar:    true,
		reasoningPanel: rp,
		phase:          phaseIdle,
		sessionID:      strings.TrimSpace(opts.SessionID),
		sessionTitle:   strings.TrimSpace(opts.Title),
		workspace:      runtime.WorkspacePath,
		modelName:      "default",
		activity:       []string{},
		useAgentTools:  true,
		interactionMode: modeBuild,
		sessionStartedAt: time.Now(),
		stickyPromptMode: modeBuild,
		activeAgentName:  config.LoadActiveAgent(),
		runtimeBadge:     badge,
		soloAgent:        soloAgent,
		teamAgent:        teamAgent,
		soloStatus:       soloStatus,
		teamStatus:       teamStatus,
		input:            ti,
	}
}

type spinTickMsg struct{}

func spinEvery(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(time.Time) tea.Msg { return spinTickMsg{} })
}

func (m model) Init() tea.Cmd {
	cmds := []tea.Cmd{
		textarea.Blink,
		m.refreshSidebarCmd(),
		m.loadSessionCapabilitiesCmd(),
		tickEvery(3 * time.Second),
		spinEvery(120 * time.Millisecond),
	}
	if m.sessionID != "" {
		cmds = append(cmds, m.loadSurfaceCmd())
	}
	return tea.Batch(cmds...)
}

func (m model) loadSurfaceCmd() tea.Cmd {
	sid := m.sessionID
	client := m.client
	// SOLO mode: load from local SQLite
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			entries, err := solo.LoadSession(sid)
			if err != nil {
				return surfaceLoadErrMsg{Err: err}
			}
			msg := surfaceLoadedMsg{Phase: phaseIdle, SessionID: sid}
			for _, e := range entries {
				msg.Msgs = append(msg.Msgs, chatLine{role: e.Role, content: e.Content})
			}
			// Use first user message as title
			for _, e := range entries {
				if e.Role == "user" && len(e.Content) > 0 {
					t := e.Content
					if len(t) > 80 {
						t = t[:79] + "…"
					}
					msg.Title = t
					break
				}
			}
			return msg
		}
	}
	return func() tea.Msg {
		snap, err := client.GetSurface(sid)
		if err != nil {
			return surfaceLoadErrMsg{Err: err}
		}
		msg := surfaceLoadedMsg{Phase: phaseIdle}
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
		if intr, ok := snap["interrupt"].(map[string]any); ok {
			q, _ := intr["question"].(string)
			iid, _ := intr["interrupt_id"].(string)
			var choices []string
			if arr, ok := intr["choices"].([]any); ok {
				for _, c := range arr {
					if s, ok := c.(string); ok {
						choices = append(choices, s)
					}
				}
			}
			if iid != "" && q != "" {
				msg.Clar = &clarifyCard{InterruptID: iid, Question: q, Choices: choices}
				msg.Phase = phaseWaitingClarify
			}
		}
		if pend, ok := snap["pending_approval"].(map[string]any); ok {
			aid, _ := pend["approval_id"].(string)
			sum, _ := pend["summary"].(string)
			if aid != "" {
				msg.Appr = &approvalCard{ID: aid, Summary: sum}
				msg.Phase = phaseWaitingApproval
			}
		}
		return msg
	}
}

func (m model) ensureSessionCmd(title string) tea.Cmd {
	client := m.client
	// SOLO mode: use local SQLite
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			sid, err := solo.CreateSession(title)
			if err != nil {
				return surfaceLoadErrMsg{Err: err}
			}
			_ = config.SaveActiveSession(sid)
			return surfaceLoadedMsg{Title: title, Phase: phaseIdle, SessionID: sid}
		}
	}
	return func() tea.Msg {
		out, err := client.CreateSession(title)
		if err != nil {
			return surfaceLoadErrMsg{Err: err}
		}
		sess, _ := out["session"].(map[string]any)
		if sess == nil {
			return surfaceLoadErrMsg{Err: fmt.Errorf("create session: unexpected response format")}
		}
		sid, _ := sess["id"].(string)
		t, _ := sess["title"].(string)
		if sid == "" {
			return surfaceLoadErrMsg{Err: fmt.Errorf("create session: missing id")}
		}
		_ = config.SaveActiveSession(sid)
		return surfaceLoadedMsg{Title: t, Phase: phaseIdle, SessionID: sid}
	}
}

func tickEvery(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(t time.Time) tea.Msg { return tickMsg{} })
}

func (m model) refreshSidebarCmd() tea.Cmd {
	client := m.client
	// SOLO mode: fill sidebar from local data
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			out := sidebarRefreshMsg{}
			out.Workspace = m.runtime.WorkspacePath
			out.Model = m.modelName
			out.ConnectorOnline = true
			if sessions, err := solo.ListSessions(); err == nil {
				out.WorkQueueCount = len(sessions)
			}
			if m.soloAgent != nil && m.soloAgent.Provider != nil {
				out.InferenceDest = string(m.soloAgent.Provider.Kind)
			} else {
				out.InferenceDest = "none"
			}
			// Collect runtime metrics always in SOLO
			if m.soloStatus != nil {
				m.soloStatus.Collect()
				snap := m.soloStatus.Snapshot()
				out.RuntimeSnap = &snap
			}
			return out
		}
	}
	return func() tea.Msg {
		out := sidebarRefreshMsg{}

		// Use consolidated endpoint when available, fall back to individual calls
		if sb, err := client.GetSidebar(); err == nil {
			if ws, ok := sb["workspace"].(map[string]any); ok {
				out.Workspace, _ = ws["path"].(string)
				out.Branch, _ = ws["branch"].(string)
				if dc, ok := ws["dirty_count"].(float64); ok {
					out.DirtyCount = int(dc)
				}
			}
			if pr, ok := sb["preferences"].(map[string]any); ok {
				out.Model, _ = pr["model"].(string)
				out.InferenceDest, _ = pr["inference_dest"].(string)
				out.AutoTier, _ = pr["auto_tier"].(string)
				if t, ok := pr["temperature"].(float64); ok {
					out.Temperature = t
				}
				out.Effort, _ = pr["effort"].(string)
				if mt, ok := pr["max_tokens"].(float64); ok {
					out.MaxTokens = int(mt)
				}
				out.ProviderRouting, _ = pr["provider_routing"].(string)
			if tb, ok := pr["thinking_budget"].(float64); ok {
				out.ThinkingBudget = int(tb)
			}
			}
			if us, ok := sb["usage"].(map[string]any); ok {
				if tc, ok := us["total_cost"].(float64); ok {
					out.UsageTotalCost = tc
				}
			}
			if pa, ok := sb["pending_approvals"].(float64); ok {
				out.Pending = int(pa)
			}
			if wq, ok := sb["work_queue_count"].(float64); ok {
				out.WorkQueueCount = int(wq)
			}
			if cn, ok := sb["connector"].(map[string]any); ok {
				out.ConnectorOnline, _ = cn["online"].(bool)
			}
		} else {
			// Fallback: individual API calls (backward compat)
			if ws, err := client.GetWorkspace(); err == nil {
				if p, ok := ws["path"].(string); ok {
					out.Workspace = p
				}
				if git, ok := ws["git"].(map[string]any); ok {
					if b, ok := git["branch"].(string); ok {
						out.Branch = b
					}
					if dc, ok := git["dirty_count"].(float64); ok {
						out.DirtyCount = int(dc)
					}
				}
			}
			if ap, err := client.ListApprovals("pending"); err == nil {
				if items, ok := ap["items"].([]any); ok {
					out.Pending = len(items)
				}
			}
			if prefs, err := client.GetPreferences(); err == nil {
				if ap, ok := prefs["assistant_preferences"].(map[string]any); ok {
					out.Model, _ = ap["llm_model_id"].(string)
					out.InferenceDest, _ = ap["inference_destination"].(string)
					out.AutoTier, _ = ap["auto_tier"].(string)
					if t, ok := ap["temperature"].(float64); ok {
						out.Temperature = t
					}
					out.Effort, _ = ap["effort"].(string)
					out.ProviderRouting, _ = ap["provider_routing"].(string)
					if tb, ok := ap["thinking_budget"].(float64); ok {
						out.ThinkingBudget = int(tb)
					}
				}
			}
			if wq, err := client.ListWorkItems(""); err == nil {
				if items, ok := wq["items"].([]any); ok {
					out.WorkQueueCount = len(items)
				}
			}
			if usage, err := client.GetUsage(); err == nil {
				if tc, ok := usage["total_cost"].(float64); ok {
					out.UsageTotalCost = tc
				}
			}
		}
		// TEAM mode: collect WS and plan metrics from teamStatus
		if m.teamStatus != nil {
			snap := m.teamStatus.Snapshot()
			out.RuntimeSnap = &snap
			out.WSConnected = snap.WSConnected
			out.WSUrl = snap.WSUrl
			out.LastPlanLatencyMs = snap.LastPlanLatencyMs
			out.PlanCount = snap.PlanCount
			out.PolicyLoaded = snap.PolicyLoaded
		}
		return out
	}
}

func waitStream(ch chan streamEventMsg) tea.Cmd {
	return func() tea.Msg {
		ev, ok := <-ch
		if !ok {
			return streamEventMsg{Event: "__done__", Data: ""}
		}
		return ev
	}
}

func (m model) startStream(req api.AskRequest) tea.Cmd {
	ch := make(chan streamEventMsg, 256) // buffered to avoid provider backpressure
	client := m.client
	workspace := m.runtime.WorkspacePath
	req.UseAgentTools = m.useAgentTools
	if m.sessionID != "" {
		req.ChatSessionID = m.sessionID
	}
	if m.sessionModelOverride != "" {
		req.ModelOverride = m.sessionModelOverride
	}
	if m.activeTabID != "" {
		req.WorkspaceID = m.activeTabID
	}

	// SOLO mode: use local AgentRuntime instead of VPS SSE
	if m.soloAgent != nil && m.soloAgent.Provider != nil {
		go func() {
			m.soloAgent.SessionID = m.sessionID
			m.soloAgent.OnToken = func(token string) {
				b, _ := json.Marshal(map[string]string{"d": token})
				ch <- streamEventMsg{Event: "token", Data: string(b)}
			}
			m.soloAgent.OnToolStart = func(name string, args map[string]any) {
				label := fmt.Sprintf("Running %s...", name)
				b, _ := json.Marshal(map[string]string{"label": label, "phase": "streaming"})
				ch <- streamEventMsg{Event: "status", Data: string(b)}
			}
			m.soloAgent.OnToolResult = func(name string, output string, errStr string) {
				if errStr != "" {
					label := fmt.Sprintf("%s failed: %s", name, errStr)
					b, _ := json.Marshal(map[string]string{"label": label, "phase": "streaming"})
					ch <- streamEventMsg{Event: "status", Data: string(b)}
				}
			}
			// OnDone and OnError are NOT used — the TUI handles completion
			// via the return value of Run(). This avoids double-close race.
			m.soloAgent.OnDone = nil
			m.soloAgent.OnError = nil

			err := m.soloAgent.Run(req.Text)
			if err != nil {
				ch <- streamEventMsg{Event: "__error__", Data: err.Error()}
			}
			ch <- streamEventMsg{Event: "__done__", Data: ""}
			close(ch)
		}()

		return func() tea.Msg {
			return streamStartedMsg{ch: ch}
		}
	}

	// SOLO mode without provider: show error immediately
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			return streamEventMsg{Event: "__error__",
				Data: "No provider configured. Set OPENROUTER_API_KEY or OLLAMA_URL in your environment, or edit ~/.config/central/config.toml"}
		}
	}

	// TEAM mode: use TeamBackend + AgentRuntime (hybrid: VPS plan, local inference)
	if m.teamAgent != nil && m.teamAgent.Provider != nil {
		go func() {
			m.teamAgent.SessionID = m.sessionID
			m.teamAgent.OnToken = func(token string) {
				b, _ := json.Marshal(map[string]string{"d": token})
				ch <- streamEventMsg{Event: "token", Data: string(b)}
			}
			m.teamAgent.OnToolStart = func(name string, args map[string]any) {
				label := fmt.Sprintf("Running %s...", name)
				b, _ := json.Marshal(map[string]string{"label": label, "phase": "streaming"})
				ch <- streamEventMsg{Event: "status", Data: string(b)}
			}
			m.teamAgent.OnToolResult = func(name string, output string, errStr string) {
				if errStr != "" {
					label := fmt.Sprintf("%s failed: %s", name, errStr)
					b, _ := json.Marshal(map[string]string{"label": label, "phase": "streaming"})
					ch <- streamEventMsg{Event: "status", Data: string(b)}
				}
			}
			m.teamAgent.OnDone = nil
			m.teamAgent.OnError = nil

			err := m.teamAgent.Run(req.Text)
			if err != nil {
				ch <- streamEventMsg{Event: "__error__", Data: err.Error()}
			}
			ch <- streamEventMsg{Event: "__done__", Data: ""}
			close(ch)
		}()

		return func() tea.Msg {
			return streamStartedMsg{ch: ch}
		}
	}

	// TEAM mode without agent: fall back to old SSE path
	if m.runtime.Runtime == config.ModeTeam {
		go func() {
			err := client.AskStream(req, workspace, func(event, data string) error {
				ch <- streamEventMsg{Event: event, Data: data}
				return nil
			})
			if err != nil {
				ch <- streamEventMsg{Event: "__error__", Data: err.Error()}
			}
			ch <- streamEventMsg{Event: "__done__", Data: ""}
			close(ch)
		}()

		return func() tea.Msg {
			return streamStartedMsg{ch: ch}
		}
	}

	// No mode matched — should not happen
	return func() tea.Msg {
		return streamEventMsg{Event: "__error__",
			Data: "No runtime mode configured."}
	}
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.MouseMsg:
		ev := tea.MouseEvent(msg)
		if msg.Shift && !ev.IsWheel() {
			return m, tea.DisableMouse
		}
		var reenable tea.Cmd
		if msg.Action == tea.MouseActionRelease && !msg.Shift {
			reenable = tea.EnableMouseCellMotion
		}
		if m.isMouseInMessageViewport(msg.Y) {
			switch msg.Type {
			case tea.MouseLeft:
				m.toggleLastThought()
				return m, reenable
			case tea.MouseWheelUp:
				m.scrollChatBy(-3)
				return m, reenable
			case tea.MouseWheelDown:
				m.scrollChatBy(3)
				return m, reenable
			}
		}
		return m, reenable

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.syncInputWidth()
		InvalidateMarkdownCache()
		return m, nil

	case tickMsg:
		return m, tea.Batch(m.refreshSidebarCmd(), tickEvery(3*time.Second))

	case spinTickMsg:
		if m.width == 0 {
			m.loadingFrame++
			return m, spinEvery(120*time.Millisecond)
		}
		if m.streaming {
			m.spinnerFrame++
			return m, spinEvery(100*time.Millisecond)
		}
		// Keep a fast tick for responsive timer/sidebar updates
		return m, spinEvery(time.Second)

	case sidebarRefreshMsg:
		if msg.Workspace != "" {
			m.workspace = msg.Workspace
		}
		if msg.Branch != "" {
			m.branch = msg.Branch
		}
		m.dirtyCount = msg.DirtyCount
		m.pendingCount = msg.Pending
		if msg.Model != "" {
			m.userDefaultModel = msg.Model
			if m.sessionModelOverride == "" {
				m.modelName = msg.Model
			}
		}
		if msg.InferenceDest != "" {
			m.inferenceDest = msg.InferenceDest
		}
		if msg.AutoTier != "" {
			m.autoTier = msg.AutoTier
		}
		m.temperature = msg.Temperature
		if msg.Effort != "" {
			m.effort = msg.Effort
		}
		m.providerRouting = msg.ProviderRouting
		m.thinkingBudget = msg.ThinkingBudget
		m.maxTokens = msg.MaxTokens
		m.connectorOnline = msg.ConnectorOnline
		m.workQueueCount = msg.WorkQueueCount
		m.usageTotalCost = msg.UsageTotalCost
		if msg.RuntimeSnap != nil {
			m.runtimeSnap = msg.RuntimeSnap
		}
		// TEAM mode: update WS and plan metrics from sidebar refresh
		if m.runtime.Runtime == config.ModeTeam {
			if m.teamStatus != nil {
				m.teamStatus.SetWSStatus(msg.WSConnected, msg.WSUrl)
				if msg.PlanCount > 0 {
					m.teamStatus.SetPlanLatency(msg.LastPlanLatencyMs)
					// PlanCount is incremented by SetPlanLatency, so we set it explicitly
					// via a manual snapshot update below
				}
			}
			// Store team metrics on the model for sidebar rendering
			m.connectorOnline = msg.WSConnected // override: WS status is the connector status in TEAM
		}
		return m, nil

	case sessionCapabilitiesMsg:
		if msg.Err != nil {
			return m, nil
		}
		if len(msg.Tools) > 0 {
			m.sessionToolNames = msg.Tools
		}
		if len(msg.Skills) > 0 {
			m.sessionSkillNames = msg.Skills
		}
		if msg.Agent != "" {
			m.activeAgentName = msg.Agent
		}
		return m, nil

	case surfaceLoadedMsg:
		if msg.SessionID != "" {
			m.sessionID = msg.SessionID
		}
		if msg.Title != "" {
			m.sessionTitle = msg.Title
		}
		if msg.Phase != "" {
			m.phase = msg.Phase
		}
		if len(msg.Msgs) > 0 {
			m.messages = msg.Msgs
			if strings.TrimSpace(m.stickyPrompt) == "" {
				m.syncStickyPromptFromMessages()
			}
		} else if m.messages == nil {
			m.messages = nil
			m.stickyPrompt = ""
		}
		m.clarify = msg.Clar
		m.approval = msg.Appr
		if m.statusLine == "Creating session…" {
			m.statusLine = "New session"
		}
		if m.pendingStreamReq != nil {
			req := *m.pendingStreamReq
			m.pendingStreamReq = nil
			m.streaming = true
			return m, m.startStream(req)
		}
		return m, nil

	case surfaceLoadErrMsg:
		m.errBar = msg.Err.Error()
		return m, nil

	case sessionOpenMsg:
		if msg.Err != nil {
			m.errBar = msg.Err.Error()
			return m, nil
		}
		if msg.SessionID != "" {
			m.sessionID = msg.SessionID
		}
		if msg.Title != "" {
			m.sessionTitle = msg.Title
		}
		if msg.Phase != "" {
			m.phase = msg.Phase
		}
		m.messages = msg.Msgs
		if strings.TrimSpace(m.stickyPrompt) == "" {
			m.syncStickyPromptFromMessages()
		}
		m.clarify = msg.Clar
		m.approval = msg.Appr
		m.streaming = false
		m.streamingText = ""
		m.statusLine = "Session opened"
		return m, nil

	case streamEventMsg:
		if msg.Event == "__done__" {
			m.streaming = false
			m.streamCh = nil
			if !m.streamStartedAt.IsZero() {
				m.lastTurnDuration = time.Since(m.streamStartedAt)
				m.streamStartedAt = time.Time{}
			}
			if m.phase == phaseStreaming {
				thoughtMs := int64(0)
				if !m.thinkingStartedAt.IsZero() {
					thoughtMs = time.Since(m.thinkingStartedAt).Milliseconds()
				}
				if m.streamingText != "" || m.thinking != "" || thoughtMs > 0 {
					m.messages = append(m.messages, chatLine{
						role:        "assistant",
						content:     m.streamingText,
						thought:     m.thinking,
						thoughtMs:   thoughtMs,
						thoughtOpen: m.streamingThoughtOpen,
						turnMode:    m.interactionMode,
						duration:    m.lastTurnDuration,
					})
				}
				m.streamingText = ""
				m.thinking = ""
				m.thinkingActive = false
				m.thinkingStartedAt = time.Time{}
				m.streamingThoughtOpen = false
				m.phase = phaseIdle
				m.statusLine = ""
				m.scrollChatToBottom()
			}
			return m, m.refreshSidebarCmd()
		}
		if msg.Event == "__error__" {
			m.streaming = false
			m.streamCh = nil
			m.phase = phaseIdle
			m.errBar = msg.Data
			return m, nil
		}
		m.handleStreamEvent(msg.Event, msg.Data)
		if m.streaming && !m.userScrolledUp {
			m.scrollChatToBottom()
		}
		if m.streamCh != nil {
			return m, waitStream(m.streamCh)
		}
		return m, nil

	case streamStartedMsg:
		m.streamCh = msg.ch
		return m, waitStream(msg.ch)

	case modelPickerLoadedMsg:
		if msg.Err != nil {
			m.errBar = msg.Err.Error()
			m.modelPickerOpen = false
			return m, nil
		}
		m.modelPickerItems = msg.Models
		m.modelPickerProvidersAPI = msg.Providers
		m.modelPickerProvidersCache = nil
		m.providerPanel = PickerPanel{MaxVisible: 10}
		m.modelPanel = PickerPanel{MaxVisible: 9}
		m.modelPickerProvider = ""
		m.modelPickerFocus = "provider"
		m.modelPickerSearch = newModelPickerSearch()
		m.modelPickerAllowOK = msg.AllowlistOK
		m.inferenceDest = msg.InferenceDest
		if msg.UserDefault != "" {
			m.userDefaultModel = msg.UserDefault
		}
		if msg.ActiveModelID != "" && m.sessionModelOverride == "" {
			m.modelName = msg.ActiveModelID
		}
		if len(msg.Models) == 0 {
			m.messages = append(m.messages, chatLine{role: "system", content: "No models available — contact tenant admin."})
			m.modelPickerOpen = false
		}
		return m, nil

	case agentPickerLoadedMsg:
		if msg.Err != nil {
			m.errBar = msg.Err.Error()
			m.agentPickerOpen = false
			return m, nil
		}
		m.agentPickerItems = msg.Agents
		m.agentPickerSkills = msg.Skills
		m.agentPanel = PickerPanel{MaxVisible: 10}
		m.skillPanel = PickerPanel{MaxVisible: 8}
		m.agentPickerFocus = "agent"
		m.agentPickerSkillSel = map[string]bool{}
		for _, sk := range m.sessionSkillNames {
			m.agentPickerSkillSel[sk] = true
		}
		for i, a := range msg.Agents {
			if a.Active {
				m.agentPanel.Cursor = i
				break
			}
		}
		return m, nil

	case agentsLoadedMsg:
		if msg.Err != nil {
			m.errBar = msg.Err.Error()
			return m, nil
		}
		m.messages = append(m.messages, chatLine{role: "system", content: strings.Join(msg.Lines, "\n")})
		return m, nil

	case toolsLoadedMsg:
		if msg.Err != nil {
			m.errBar = msg.Err.Error()
			m.toolsPickerOpen = false
			return m, nil
		}
		m.toolsPickerItems = msg.Tools
		m.toolsPanel = PickerPanel{MaxVisible: 12}
		return m, nil

	case memoryStatusMsg:
		if msg.Err != nil {
			m.errBar = msg.Err.Error()
			return m, nil
		}
		m.messages = append(m.messages, chatLine{role: "system", content: msg.Text})
		return m, nil

	case sessionListResultMsg:
		if msg.Err != nil {
			m.errBar = msg.Err.Error()
			return m, nil
		}
		m.messages = append(m.messages, chatLine{role: "system", content: strings.Join(msg.Lines, "\n")})
		return m, nil

	case doctorMsg:
		if msg.Err != nil {
			m.errBar = msg.Err.Error()
			return m, nil
		}
		m.messages = append(m.messages, chatLine{role: "system", content: msg.Text})
		return m, nil

	case modelPickerAppliedMsg:
		if msg.Err != nil {
			m.errBar = modelPickerPolicyMessage(msg.Err)
			return m, nil
		}
		// SOLO mode: update provider model
		if m.soloAgent != nil && m.soloAgent.Provider != nil {
			m.soloAgent.Provider.ChangeModel(msg.ModelID)
		}
		if msg.Scope == "session" {
			m.sessionModelOverride = msg.ModelID
		} else {
			m.sessionModelOverride = ""
			m.userDefaultModel = msg.ModelID
		}
		m.modelName = msg.ModelID
		m.statusLine = "Model: " + msg.ModelID
		if msg.Scope == "session" {
			m.statusLine += " (session)"
		}
		m.messages = append(m.messages, chatLine{role: "system", content: "Active model: " + msg.ModelID})
		return m, nil

	case tea.KeyMsg:
		if m.paramsPickerOpen {
			return m.updateParamsPicker(msg)
		}
		if m.toolsPickerOpen {
			return m.updateToolsPicker(msg)
		}
		if m.agentPickerOpen {
			return m.updateAgentPicker(msg)
		}
		if m.modelPickerOpen {
			return m.updateModelPicker(msg)
		}
		if m.slashPaletteOpen {
			return m.updateSlashPalette(msg)
		}
		if m.paletteOpen {
			return m.updatePalette(msg)
		}
		if m.clarify != nil && m.phase == phaseWaitingClarify {
			if m.clarifyCustom {
				switch msg.String() {
				case "esc":
					m.clarifyCustom = false
					m.input.SetValue("")
					m.input.Placeholder = "Message… (/help)"
					return m, nil
				case "enter":
					custom := strings.TrimSpace(m.input.Value())
					if custom == "" {
						return m, nil
					}
					return m.submitClarifyChoice("", custom)
				default:
					var cmd tea.Cmd
					m.input, cmd = m.input.Update(msg)
					return m, cmd
				}
			}
			switch msg.String() {
			case "1", "2", "3", "4":
				idx := int(msg.String()[0] - '1')
				if idx >= 0 && idx < len(m.clarify.Choices) {
					choice := m.clarify.Choices[idx]
					if strings.EqualFold(choice, "outro") || strings.HasPrefix(strings.ToLower(choice), "outro") {
						m.clarifyCustom = true
						m.input.SetValue("")
						m.input.Placeholder = "Resposta personalizada…"
						return m, nil
					}
					return m.submitClarifyChoice(choice, "")
				}
			case "o":
				m.clarifyCustom = true
				m.input.SetValue("")
				m.input.Placeholder = "Resposta personalizada…"
				return m, nil
			default:
				return m, nil
			}
		}
		if m.approval != nil && m.phase == phaseWaitingApproval {
			switch strings.ToLower(msg.String()) {
			case "a":
				id := m.approval.ID
				m.approval = nil
				m.phase = phaseIdle
				return m, func() tea.Msg {
					if _, err := m.client.Approve(id); err != nil {
						return streamDoneMsg{Err: err}
					}
					return sidebarRefreshMsg{}
				}
			case "r":
				id := m.approval.ID
				m.approval = nil
				m.phase = phaseIdle
				return m, func() tea.Msg {
					if err := m.client.Deny(id, ""); err != nil {
						return streamDoneMsg{Err: err}
					}
					return sidebarRefreshMsg{}
				}
			case "d":
				id := m.approval.ID
				return m, func() tea.Msg {
					out, err := m.client.ApprovalDiff(id)
					if err != nil {
						return streamDoneMsg{Err: err}
					}
					preview := ""
					if d, ok := out["diff"].(string); ok {
						preview = d
					} else if c, ok := out["command"].(string); ok {
						preview = "Command: " + c
					}
					return streamEventMsg{Event: "local_diff", Data: preview}
				}
			}
		}

		switch msg.String() {
		case "ctrl+c":
			if m.streaming {
				m.streaming = false
				m.phase = phaseIdle
				m.statusLine = "cancelado"
				return m, nil
			}
			return m, tea.Quit
		case "ctrl+l":
			if m.runtime.Runtime == config.ModeSolo {
				m.messages = append(m.messages, chatLine{role: "system", content: "Ctrl+L logout is TEAM-only. Use Ctrl+C to quit or /hub to return to Hub."})
				return m, nil
			}
			m.requestLogout = true
			return m, nil
		case "ctrl+b":
			m.showSidebar = !m.showSidebar
			m.syncInputWidth()
			return m, nil
		case "ctrl+t":
			m.reasoningPanel = toggleReasoningInPanel(m.reasoningPanel)
			return m, nil
		case "ctrl+h":
			m.requestHub = true
			return m, nil
		case "ctrl+p":
			m.paletteOpen = true
			m.paletteItems = []string{
				"Toggle painel",
				"Toggle reasoning",
				"Refresh painel",
			}
			m.paletteIdx = 0
			return m, nil
		case "pgup", "shift+up":
			if !m.slashPaletteOpen && !m.modelPickerOpen && !m.paletteOpen && !m.paramsPickerOpen && !m.toolsPickerOpen && !m.agentPickerOpen {
				m.scrollChatBy(-5)
				return m, nil
			}
		case "pgdown", "shift+down":
			if !m.slashPaletteOpen && !m.modelPickerOpen && !m.paletteOpen && !m.paramsPickerOpen && !m.toolsPickerOpen && !m.agentPickerOpen {
				m.scrollChatBy(5)
				return m, nil
			}
		case "ctrl+shift+c":
			if !m.slashPaletteOpen && !m.modelPickerOpen && !m.paletteOpen && !m.paramsPickerOpen && !m.toolsPickerOpen && !m.agentPickerOpen {
				return m.copyLastAssistant()
			}
		case "ctrl+shift+t":
			if !m.slashPaletteOpen && !m.modelPickerOpen && !m.paletteOpen && !m.paramsPickerOpen && !m.toolsPickerOpen && !m.agentPickerOpen &&
				m.phase != phaseWaitingClarify && !m.clarifyCustom {
				m.toggleLastThought()
				return m, nil
			}
		case "tab":
			if !m.slashPaletteOpen && !m.modelPickerOpen && !m.paletteOpen &&
				m.phase != phaseWaitingClarify && !m.clarifyCustom {
				m.toggleInteractionMode()
				return m, nil
			}
		case "enter":
			if m.phase == phaseWaitingApproval {
				return m, nil
			}
			if m.phase == phaseWaitingClarify && !m.clarifyCustom {
				return m, nil
			}
			text := strings.TrimSpace(m.input.Value())
			if text == "" && !m.streaming && len(m.toolLog.Calls) > 0 {
				// Toggle diff of last tool with diff lines
				for i := len(m.toolLog.Calls) - 1; i >= 0; i-- {
					if len(m.toolLog.Calls[i].DiffLines) > 0 {
						if m.toolLog.DiffOpen == i {
							m.toolLog.DiffOpen = -1
						} else {
							m.toolLog.DiffOpen = i
						}
						return m, nil
					}
				}
				return m, nil
			}
			if text == "" || m.streaming {
				return m, nil
			}
			if strings.HasPrefix(text, "/") {
				return m.handleSlash(text)
			}
			display := text
			media, stripped, labels := parseAttachments(text, m.runtime.WorkspacePath)
			if stripped != "" {
				text = stripped
			}
			for _, label := range labels {
				display += " [img:" + label + "]"
			}
			m.saveTurnSnapshot()
			m.lastPrompt = text
			m.lastPromptMode = m.interactionMode
			m.lastMedia = media
			m.messages = append(m.messages, chatLine{role: "user", content: display, turnMode: m.interactionMode})
			m.stickyPrompt = display
			m.stickyPromptMode = m.interactionMode
			m.scrollChatToBottom()
			m.toolLog.clear()
			m.input.SetValue("")
			m.input.Placeholder = "Message… (/help)"
			m.streaming = true
			m.phase = phaseStreaming
			m.streamingText = ""
			m.thinking = ""
			m.thinkingActive = false
			m.thinkingStartedAt = time.Time{}
			m.streamingThoughtOpen = false
			m.statusLine = "● A processar…"
			m.errBar = ""
			m.streamStartedAt = time.Now()
			req := api.AskRequest{Text: text, UseAgentTools: m.useAgentTools, MediaAttachments: media}
			if m.sessionID == "" {
				title := m.sessionTitle
				if title == "" {
					title = truncateSessionTitle(text)
				}
				m.pendingStreamReq = &req
				return m, m.ensureSessionCmd(title)
			}
			return m, m.startStream(req)
		}
	}

	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	m.openSlashPaletteFromInput()
	return m, cmd
}

func (m *model) handleSlash(text string) (tea.Model, tea.Cmd) {
	m.input.SetValue("")
	fields := strings.Fields(text)
	if len(fields) == 0 {
		return sessionTea(m), nil
	}
	cmd := strings.ToLower(fields[0])
	switch cmd {
	case "/help":
		lines := []string{
			"══════ Model & Agent ══════",
			"  /model    Browse and switch LLM models",
			"  /agent    Select agent persona + skills",
			"  /tools    View available tool catalog",
			"",
			"══════ Session ══════",
			"  /memory   Show saved memories",
			"  /session  List recent sessions",
			"  /resume   Reopen a past session",
			"  /clear    Clear current conversation",
			"  /undo     Undo last turn",
			"  /retry    Retry last turn",
			"  /pin      Pin current session",
			"",
			"══════ Configuration ══════",
			"  /setup    Add or edit LLM provider keys",
			"  /prefs    View / save preferences",
			"  /mode     Switch SOLO / TEAM mode",
			"  /doctor   System health check",
			"",
			"══════ Navigation ══════",
			"  /hub      Return to workspace hub",
			"  /logout   Sign out (TEAM only)",
			"  /exit     Quit CentralChat",
			"",
			"══════ Keyboard ══════",
			"  Tab       Plan ↔ Build mode",
			"  Ctrl+H    Toggle session hub",
			"  Ctrl+B    Toggle sidebar",
			"  Ctrl+P    Command palette",
			"  Ctrl+L    Logout (TEAM only)",
			"  Ctrl+C    Quit",
		}
		m.messages = append(m.messages, chatLine{role: "system", content: strings.Join(lines, "\n")})
	case "/model", "/models", "/m":
		m.modelPickerOpen = true
		m.modelPickerProvider = ""
		m.providerPanel = PickerPanel{MaxVisible: 10}
		m.modelPanel = PickerPanel{MaxVisible: 9}
		m.modelPickerFocus = "provider"
		m.modelPickerSearch = newModelPickerSearch()
		m.input.Blur()
		return sessionTea(m), m.loadModelPickerCmd()
	case "/agent", "/agents":
		m.agentPickerOpen = true
		m.agentPanel = PickerPanel{MaxVisible: 10}
		m.skillPanel = PickerPanel{MaxVisible: 8}
		m.agentPickerFocus = "agent"
		m.agentPickerSkillSel = nil
		m.input.Blur()
		return sessionTea(m), m.loadAgentPickerCmd()
	case "/tools":
		m.toolsPickerOpen = true
		m.toolsPanel = PickerPanel{MaxVisible: 12}
		m.input.Blur()
		return sessionTea(m), m.loadToolsCmd()
	case "/memory":
		return sessionTea(m), m.memoryStatusCmd()
	case "/session", "/sessions":
		if len(fields) >= 3 && strings.EqualFold(fields[1], "open") {
			return sessionTea(m), m.sessionOpenCmd(fields[2])
		}
		return sessionTea(m), m.sessionListCmd()
	case "/approve":
		return sessionTea(m), m.approveListCmd()
	case "/workspace":
		m.requestHub = true
	case "/doctor":
		return sessionTea(m), m.doctorCmd()
	case "/mode":
		if len(fields) >= 2 {
			switch strings.ToLower(fields[1]) {
			case "solo":
				m.switchToSolo()
			case "team":
				m.switchToTeam()
			default:
				m.messages = append(m.messages, chatLine{role: "system", content: "Usage: /mode solo|team"})
			}
		} else {
			current := "team"
			if m.runtime.Runtime == config.ModeSolo {
				current = "solo"
			}
			m.messages = append(m.messages, chatLine{role: "system", content: "Current mode: " + current + ". Use /mode solo|team to switch."})
		}
		return sessionTea(m), nil
	case "/setup":
		m.messages = append(m.messages, chatLine{role: "system", content: "Opening provider setup. Press Esc to return."})
		m.requestSetup = true
		return sessionTea(m), nil
	case "/thinking":
		m.reasoningPanel = toggleReasoningInPanel(m.reasoningPanel)
	case "/tier":
		if len(fields) < 2 {
			m.messages = append(m.messages, chatLine{role: "system", content: "Usage: /tier economy|balanced|premium. Current: " + m.autoTier})
		} else {
			val := strings.ToLower(fields[1])
			if val == "economy" || val == "balanced" || val == "premium" {
				m.autoTier = val
				m.messages = append(m.messages, chatLine{role: "system", content: "Auto tier set to " + val + ". Save with /prefs."})
			} else {
				m.messages = append(m.messages, chatLine{role: "system", content: "Invalid tier. Use: economy, balanced, premium"})
			}
		}
	case "/route":
		if len(fields) < 2 {
			m.messages = append(m.messages, chatLine{role: "system", content: "Usage: /route cheapest|fastest|throughput. Current: " + m.providerRouting})
		} else {
			val := strings.ToLower(fields[1])
			if val == "cheapest" || val == "fastest" || val == "throughput" {
				m.providerRouting = val
				m.messages = append(m.messages, chatLine{role: "system", content: "Provider routing set to " + val + ". Save with /prefs."})
			} else {
				m.messages = append(m.messages, chatLine{role: "system", content: "Invalid route. Use: cheapest, fastest, throughput"})
			}
		}
	case "/temp":
		if len(fields) < 2 {
			m.messages = append(m.messages, chatLine{role: "system", content: fmt.Sprintf("Usage: /temp 0.0-2.0. Current: %.1f", m.temperature)})
		} else {
			if t, err := strconv.ParseFloat(fields[1], 64); err == nil && t >= 0 && t <= 2.0 {
				m.temperature = t
				m.messages = append(m.messages, chatLine{role: "system", content: fmt.Sprintf("Temperature set to %.1f. Save with /prefs.", t)})
			} else {
				m.messages = append(m.messages, chatLine{role: "system", content: "Invalid. Use a number between 0.0 and 2.0"})
			}
		}
	case "/effort":
		if len(fields) < 2 {
			m.messages = append(m.messages, chatLine{role: "system", content: "Usage: /effort low|medium|high. Current: " + m.effort})
		} else {
			val := strings.ToLower(fields[1])
			if val == "low" || val == "medium" || val == "high" {
				m.effort = val
				m.messages = append(m.messages, chatLine{role: "system", content: "Effort set to " + val + ". Save with /prefs."})
			} else {
				m.messages = append(m.messages, chatLine{role: "system", content: "Invalid effort. Use: low, medium, high"})
			}
		}
	case "/thinking-budget":
		if len(fields) < 2 {
			m.messages = append(m.messages, chatLine{role: "system", content: fmt.Sprintf("Usage: /thinking-budget <tokens>. Current: %d", m.thinkingBudget)})
		} else {
			if tb, err := strconv.Atoi(fields[1]); err == nil && tb >= 0 {
				m.thinkingBudget = tb
				m.messages = append(m.messages, chatLine{role: "system", content: fmt.Sprintf("Thinking budget set to %d tokens. Save with /prefs.", tb)})
			} else {
				m.messages = append(m.messages, chatLine{role: "system", content: "Invalid. Use a non-negative number (e.g. 16000)"})
			}
		}
	case "/params":
		m.paramsPickerOpen = true
		m.paramsPickerItems = m.buildParamsPickerItems()
		m.paramsPanel = PickerPanel{MaxVisible: 8}
		m.input.Blur()
	case "/undo":
		if m.turnSnap == nil && m.lastRequestID == "" {
			m.messages = append(m.messages, chatLine{role: "system", content: "Nothing to undo."})
		} else {
			m.restoreTurnSnapshot()
			var cmds []tea.Cmd
			if m.lastRequestID != "" {
				rid := m.lastRequestID
				m.lastRequestID = ""
				cmds = append(cmds, func() tea.Msg {
					out, err := m.client.UndoRequest(rid)
					if err != nil {
						return memoryStatusMsg{Err: err}
					}
					restored := 0
					if v, ok := out["files_restored"].(float64); ok {
						restored = int(v)
					}
					deleted := 0
					if v, ok := out["files_deleted"].(float64); ok {
						deleted = int(v)
					}
					msg := "Turn undone."
					if restored+deleted > 0 {
						msg += fmt.Sprintf(" Reverted %d file(s).", restored+deleted)
					}
					return memoryStatusMsg{Text: msg}
				})
			}
			m.messages = append(m.messages, chatLine{role: "system", content: "Turn undone."})
			return sessionTea(m), tea.Batch(cmds...)
		}
	case "/retry":
		if m.lastPrompt == "" {
			m.messages = append(m.messages, chatLine{role: "system", content: "No prompt to retry."})
		} else if m.streaming {
			m.messages = append(m.messages, chatLine{role: "system", content: "Wait for stream to finish."})
		} else {
			m.saveTurnSnapshot()
			m.messages = append(m.messages, chatLine{role: "user", content: m.lastPrompt, turnMode: m.lastPromptMode})
			m.stickyPrompt = m.lastPrompt
			m.stickyPromptMode = m.lastPromptMode
			m.scrollChatToBottom()
			m.streaming = true
			m.phase = phaseStreaming
			m.streamingText = ""
			m.thinking = ""
			m.thinkingActive = false
			m.thinkingStartedAt = time.Time{}
			m.streamingThoughtOpen = false
			m.statusLine = "● Processing…"
			m.errBar = ""
			m.streamStartedAt = time.Now()
			req := api.AskRequest{Text: m.lastPrompt, UseAgentTools: m.useAgentTools, MediaAttachments: m.lastMedia}
			if m.sessionID == "" {
				title := m.sessionTitle
				if title == "" {
					title = truncateSessionTitle(m.lastPrompt)
				}
				m.pendingStreamReq = &req
				return sessionTea(m), m.ensureSessionCmd(title)
			}
			return sessionTea(m), m.startStream(req)
		}
	case "/prefs":
		// SOLO mode: open config.toml in editor
		if m.runtime.Runtime == config.ModeSolo {
			path, _ := config.RuntimeConfigPath()
			if path != "" {
				m.messages = append(m.messages, chatLine{role: "system", content: "Config: " + path})
			}
			return sessionTea(m), nil
		}
		prefs := map[string]any{}
		if m.sessionModelOverride != "" {
			prefs["llm_model_id"] = m.sessionModelOverride
		} else if m.userDefaultModel != "" {
			prefs["llm_model_id"] = m.userDefaultModel
		}
		if m.inferenceDest != "" {
			prefs["inference_destination"] = m.inferenceDest
		}
		if m.autoTier != "" {
			prefs["auto_tier"] = m.autoTier
		}
		if m.providerRouting != "" {
			prefs["provider_routing"] = m.providerRouting
		}
		if m.temperature > 0 {
			prefs["temperature"] = m.temperature
		}
		if m.effort != "" {
			prefs["effort"] = m.effort
		}
		if m.thinkingBudget > 0 {
			prefs["thinking_budget"] = m.thinkingBudget
		}
		if len(prefs) == 0 {
			m.messages = append(m.messages, chatLine{role: "system", content: "No settings to save. Use /model, /agent, or /tools first."})
		} else {
			return sessionTea(m), func() tea.Msg {
				_, err := m.client.SetPreferences(prefs)
				if err != nil {
					return memoryStatusMsg{Err: err}
				}
				return memoryStatusMsg{Text: "Preferences saved as defaults for new sessions."}
			}
		}
	case "/clear":
		if m.streaming {
			m.statusLine = "Wait for stream to finish"
		} else {
			sid := m.sessionID
			m.resetChatSessionState()
			m.sessionID = sid
			m.statusLine = "Conversation cleared"
		}
	case "/pin":
		if m.sessionID == "" {
			m.messages = append(m.messages, chatLine{role: "system", content: "No active session to pin."})
		} else {
			return sessionTea(m), func() tea.Msg {
				out, err := m.client.PinSession(m.sessionID, true)
				if err != nil {
					return memoryStatusMsg{Err: err}
				}
				pinned, _ := out["pinned"].(bool)
				if pinned {
					return memoryStatusMsg{Text: "Session pinned."}
				}
				return memoryStatusMsg{Text: "Session unpinned."}
			}
		}
	case "/resume":
		return sessionTea(m), m.sessionListCmd()
	case "/logout":
		if m.runtime.Runtime == config.ModeSolo {
			m.messages = append(m.messages, chatLine{role: "system", content: "/logout is TEAM-only. Use /hub to return to Hub."})
		} else {
			m.requestLogout = true
		}
	case "/exit":
		return sessionTea(m), tea.Quit
	default:
		m.messages = append(m.messages, chatLine{role: "system", content: "Unknown command. /help"})
	}
	return sessionTea(m), nil
}

func (m model) updatePalette(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc", "ctrl+p":
		m.paletteOpen = false
		return m, nil
	case "up", "k":
		if m.paletteIdx > 0 {
			m.paletteIdx--
		}
	case "down", "j":
		if m.paletteIdx < len(m.paletteItems)-1 {
			m.paletteIdx++
		}
	case "enter":
		m.paletteOpen = false
		switch m.paletteItems[m.paletteIdx] {
		case "Toggle painel", "Toggle sidebar":
			m.showSidebar = !m.showSidebar
			m.syncInputWidth()
		case "Toggle reasoning":
			m.reasoningPanel = toggleReasoningInPanel(m.reasoningPanel)
		case "Refresh painel", "Refresh sidebar":
			return m, m.refreshSidebarCmd()
		}
	}
	return m, nil
}

func (m *model) handleStreamEvent(event, data string) {
	switch event {
	case "local_diff":
		m.messages = append(m.messages, chatLine{role: "system", content: data})
	case "token":
		var p struct{ D string `json:"d"` }
		if json.Unmarshal([]byte(data), &p) == nil {
			m.streamingText += p.D
		}
	case "thinking":
		var p struct{ D string `json:"d"` }
		if json.Unmarshal([]byte(data), &p) == nil {
			if m.thinkingStartedAt.IsZero() {
				m.thinkingStartedAt = time.Now()
			}
			m.thinking += p.D
			m.thinkingActive = true
		}
	case "thinking_done":
		m.thinkingActive = false
	case "status":
		var p struct {
			Label string `json:"label"`
			Phase string `json:"phase"`
		}
		if json.Unmarshal([]byte(data), &p) == nil {
			if p.Label != "" {
				m.statusLine = "● " + p.Label
			}
			if p.Phase != "" {
				m.phase = sessionPhase(p.Phase)
			}
			m.pushActivity(p.Label)
		}
	case "usage", "token_usage":
		var u map[string]any
		if json.Unmarshal([]byte(data), &u) == nil {
			if v, ok := u["prompt_tokens"].(float64); ok {
				m.tokensIn = int(v)
			}
			if v, ok := u["in"].(float64); ok {
				m.tokensIn = int(v)
			}
			if v, ok := u["completion_tokens"].(float64); ok {
				m.tokensOut = int(v)
			}
			if v, ok := u["out"].(float64); ok {
				m.tokensOut = int(v)
			}
			if v, ok := u["pct"].(float64); ok {
				m.contextPct = int(v)
			}
			total := m.tokensIn + m.tokensOut
			if total > 0 && m.contextPct == 0 {
				m.contextPct = min(99, total/1000)
			}
		}
	case "approval_required":
		var p map[string]any
		if json.Unmarshal([]byte(data), &p) == nil {
			id, _ := p["approval_id"].(string)
			act, _ := p["action_id"].(string)
			sum, _ := p["summary"].(string)
			cmd, _ := p["command"].(string)
			path, _ := p["path"].(string)
			m.approval = &approvalCard{ID: id, Action: act, Summary: sum, Command: cmd, Path: path}
			m.phase = phaseWaitingApproval
			m.pendingCount++
			m.streaming = false
		}
	case "clarify_required":
		var p map[string]any
		if json.Unmarshal([]byte(data), &p) == nil {
			iid, _ := p["interrupt_id"].(string)
			q, _ := p["question"].(string)
			var choices []string
			if arr, ok := p["choices"].([]any); ok {
				for _, c := range arr {
					if s, ok := c.(string); ok {
						choices = append(choices, s)
					}
				}
			}
			m.clarify = &clarifyCard{InterruptID: iid, Question: q, Choices: choices}
			m.phase = phaseWaitingClarify
			m.streaming = false
			m.statusLine = "● waiting for your choice"
		}
	case "provider":
		var p struct{ D string `json:"d"` }
		if json.Unmarshal([]byte(data), &p) == nil && p.D != "" {
			m.modelName = p.D
		}
	case "start":
		var p struct {
			RequestID     string `json:"request_id"`
			ChatSessionID string `json:"chat_session_id"`
		}
		if json.Unmarshal([]byte(data), &p) == nil {
			if p.ChatSessionID != "" {
				m.sessionID = p.ChatSessionID
				_ = config.SaveActiveSession(p.ChatSessionID)
			}
			if p.RequestID != "" {
				m.lastRequestID = p.RequestID
				m.pushActivity("stream " + p.RequestID[:min(8, len(p.RequestID))])
			}
		}
	case "tool_proposed":
		var p struct {
			Tool      string         `json:"tool"`
			Arguments map[string]any `json:"arguments"`
		}
		if json.Unmarshal([]byte(data), &p) == nil {
			params := toolParamsFromArgs(p.Tool, p.Arguments)
			m.toolLog.add(toolCall{
				Name:      p.Tool,
				Params:    params,
				Status:    toolQueued,
				StartedAt: time.Now(),
			})
		}
	case "tool_running":
		var p struct {
			Tool      string         `json:"tool"`
			Arguments map[string]any `json:"arguments"`
		}
		if json.Unmarshal([]byte(data), &p) == nil {
			idx := m.toolLog.findByAction(p.Tool)
			if idx >= 0 && m.toolLog.Calls[idx].Status == toolQueued {
				m.toolLog.Calls[idx].Status = toolRunning
				m.toolLog.Calls[idx].StartedAt = time.Now()
			} else {
				params := toolParamsFromArgs(p.Tool, p.Arguments)
				m.toolLog.add(toolCall{
					Name:      p.Tool,
					Params:    params,
					Status:    toolRunning,
					StartedAt: time.Now(),
				})
			}
			m.pushActivity("▶ " + p.Tool)
		}
	case "tool_result":
		var p struct {
			Tool    string `json:"tool"`
			Preview string `json:"preview"`
		}
		if json.Unmarshal([]byte(data), &p) == nil {
			idx := m.toolLog.lastRunning()
			if idx >= 0 && m.toolLog.Calls[idx].Name == p.Tool {
				tc := &m.toolLog.Calls[idx]
				tc.Status = toolDone
				tc.Duration = time.Since(tc.StartedAt)
				tc.Preview = p.Preview
				if len(tc.Preview) > 40 {
					tc.Preview = tc.Preview[:40] + "…"
				}
				if p.Tool == "write_file" || p.Tool == "patch" {
					var full struct {
						Result map[string]any `json:"result"`
					}
					if json.Unmarshal([]byte(data), &full) == nil {
						if diff, ok := full.Result["diff"].(string); ok && diff != "" {
							tc.DiffLines = strings.Split(diff, "\n")
						}
					}
				}
			}
			prev := p.Preview
			if len(prev) > 40 {
				prev = prev[:40] + "…"
			}
			m.pushActivity("✓ " + p.Tool + " " + prev)
		}
	case "tool_denied":
		var p struct {
			Tool   string `json:"tool"`
			Reason string `json:"reason"`
		}
		if json.Unmarshal([]byte(data), &p) == nil {
			idx := m.toolLog.lastRunning()
			if idx >= 0 && m.toolLog.Calls[idx].Name == p.Tool {
				m.toolLog.Calls[idx].Status = toolDone
				m.toolLog.Calls[idx].Duration = time.Since(m.toolLog.Calls[idx].StartedAt)
				m.toolLog.Calls[idx].Preview = "denied: " + p.Reason
			}
		}
	case "error":
		m.errBar = data
	case "done":
		// stream may still flush tokens; finalization on __done__
	}
}

func (m *model) pushActivity(line string) {
	if line == "" {
		return
	}
	m.activity = append([]string{line}, m.activity...)
	if len(m.activity) > 5 {
		m.activity = m.activity[:5]
	}
}

func (m model) chatWidth() int {
	w := sessionInnerWidth(m.width)
	if m.showSidebar {
		w -= m.rightPanelWidth() + sessionColumnGap
	}
	if w < 20 {
		return 20
	}
	return w
}

func (m *model) syncInputWidth() {
	inset := contentInset(sessionInnerWidth(m.width))
	boxW := chatContentWidth(m.chatWidth(), inset)
	innerTextW := boxW - 6
	// Account for spinner during streaming (must match renderInputBox)
	if m.streaming && boxW >= 50 {
		innerTextW -= 17 // spinnerW(16) + gap(1)
	}
	if innerTextW < 16 {
		innerTextW = 16
	}
	m.input.SetWidth(innerTextW)
}

func (m model) renderSessionBody(bodyH int) string {
	innerW := sessionInnerWidth(m.width)
	chatW := m.chatWidth()
	chat := m.renderChatColumn(bodyH)

	if !m.showSidebar {
		return fitBlockHeight(chat, innerW, bodyH, chatCanvasStyle())
	}

	sidebarW := m.rightPanelWidth()
	sidebar := m.renderRightPanel(bodyH)
	joined := joinHorizontalBlocks(chat, sidebar, chatW, sessionColumnGap, sidebarW)

	rowW := chatW + sessionColumnGap + sidebarW
	if rowW < innerW {
		return padBlockToWidth(joined, innerW, chatCanvasStyle(), 0)
	}
	return joined
}

func (m model) View() string {
	if m.width == 0 {
		hint := "Ctrl+C sair"
		if m.offlineMode {
			hint = "Modo read-only (daemon offline) · " + hint
		}
		return renderLoadingScreen(m.width, m.height, m.loadingFrame, "Preparing session", hint)
	}

	contentH := m.contentHeight()
	body := m.renderSessionBody(contentH)

	status := m.statusLine
	if m.errBar != "" {
		status = styleError.Render(m.errBar)
	}

	var extra string
	if m.paletteOpen {
		extra = m.renderPalette()
	}

	sections := []string{body}
	if status != "" {
		sections = append(sections, transparentLine(sessionInnerWidth(m.width), status, contentInset(sessionInnerWidth(m.width))))
	}
	if extra != "" {
		sections = append(sections, extra)
	}

	out := lipgloss.JoinVertical(lipgloss.Left, sections...)
	if m.skipSessionHeader {
		return ensureFrameHeight(out, sessionInnerWidth(m.width), m.contentHeight())
	}

	all := lipgloss.JoinVertical(lipgloss.Left,
		renderSessionHeaderPanel(sessionInnerWidth(m.width), m.displayTurnTitle(), workspacesFile{}, nil, -1, "", m.runtimeBadge, m.connectorOnline),
		out,
	)
	return applySessionFrame(ensureFrameHeight(all, sessionInnerWidth(m.width), m.height-2*sessionFrameMargin), m.width, m.height)
}

func (m model) renderPalette() string {
	var lines []string
	for i, item := range m.paletteItems {
		mark := "  "
		if i == m.paletteIdx {
			mark = "> "
		}
		lines = append(lines, mark+item)
	}
	return lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).Background(lipgloss.Color(ColorCanvas)).Padding(0, 1).Render(
		"Command palette\n" + strings.Join(lines, "\n"),
	)
}

func shortPath(p string, keep int) string {
	if p == "" {
		return "(sem workspace)"
	}
	parts := strings.Split(strings.TrimRight(p, "/"), "/")
	if len(parts) <= keep {
		return p
	}
	return "…/" + strings.Join(parts[len(parts)-keep:], "/")
}

func trim(s string, n int) string {
	s = strings.ReplaceAll(s, "\n", " ")
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}

// trimPreserveNewlines caps length without flattening paragraph breaks (assistant markdown-as-text).
func trimPreserveNewlines(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}

// wrapMultiline wraps each line independently so code blocks and lists keep structure in the TUI.
func wrapMultiline(s string, width int) string {
	if s == "" {
		return ""
	}
	lines := strings.Split(s, "\n")
	out := make([]string, 0, len(lines))
	for _, ln := range lines {
		if strings.TrimSpace(ln) == "" {
			out = append(out, "")
			continue
		}
		out = append(out, wrap(ln, width))
	}
	return strings.Join(out, "\n")
}

func wrap(s string, width int) string {
	if width < 8 {
		return s
	}
	var out []string
	for len(s) > width {
		out = append(out, s[:width])
		s = s[width:]
	}
	if s != "" {
		out = append(out, s)
	}
	return strings.Join(out, "\n")
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func (m model) submitClarifyChoice(choice, custom string) (tea.Model, tea.Cmd) {
	if m.clarify == nil {
		return m, nil
	}
	label := choice
	if custom != "" {
		label = custom
	}
	m.messages = append(m.messages, chatLine{role: "user", content: "[Clarify] " + label})
	m.stickyPrompt = "[Clarify] " + label
	m.stickyPromptMode = m.interactionMode
	m.input.SetValue("")
	m.clarifyCustom = false
	m.input.Placeholder = "Message… (/help)"
	interruptID := m.clarify.InterruptID
	m.clarify = nil
	m.streaming = true
	m.phase = phaseStreaming
	m.streamingText = ""
	m.thinking = ""
	m.thinkingActive = false
	m.statusLine = "● A continuar…"
	m.errBar = ""
	m.streamStartedAt = time.Now()
	req := api.AskRequest{
		Text:          "(continua)",
		UseAgentTools: m.useAgentTools,
		ClarifyResponse: &api.ClarifyResponse{
			InterruptID: interruptID,
			Choice:      choice,
			Custom:      custom,
		},
	}
	return m, m.startStream(req)
}

func truncateSessionTitle(text string) string {
	t := strings.TrimSpace(text)
	if t == "" {
		return "New conversation"
	}
	return trim(t, 80)
}

var imageExtensions = map[string]string{
	".png":  "image/png",
	".jpg":  "image/jpeg",
	".jpeg": "image/jpeg",
	".gif":  "image/gif",
	".webp": "image/webp",
}

func parseAttachments(text, workspace string) ([]api.MediaAttachment, string, []string) {
	media, cleaned, labels := parseImageAttachments(text, workspace)
	// P3c: ficheiros não-imagem como referência textual no prompt
	var fileRefs []string
	for _, token := range strings.Fields(text) {
		if !strings.HasPrefix(token, "@") {
			continue
		}
		raw := strings.TrimPrefix(token, "@")
		raw = strings.Trim(raw, `"'`)
		ext := strings.ToLower(filepath.Ext(raw))
		if _, isImg := imageExtensions[ext]; isImg {
			continue
		}
		path := raw
		if !filepath.IsAbs(path) && workspace != "" {
			path = filepath.Join(workspace, raw)
		}
		if st, err := os.Stat(path); err == nil && !st.IsDir() {
			fileRefs = append(fileRefs, filepath.Base(path))
			cleaned += "\n[ref:" + path + "]"
		}
	}
	labels = append(labels, fileRefs...)
	return media, strings.TrimSpace(cleaned), labels
}

func parseImageAttachments(text, workspace string) ([]api.MediaAttachment, string, []string) {
	var out []api.MediaAttachment
	var labels []string
	cleaned := text
	for _, token := range strings.Fields(text) {
		if !strings.HasPrefix(token, "@") {
			continue
		}
		raw := strings.TrimPrefix(token, "@")
		raw = strings.Trim(raw, `"'`)
		if raw == "" {
			continue
		}
		path := raw
		if !filepath.IsAbs(path) && workspace != "" {
			path = filepath.Join(workspace, raw)
		}
		ext := strings.ToLower(filepath.Ext(path))
		mime, ok := imageExtensions[ext]
		if !ok {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		out = append(out, api.MediaAttachment{
			Kind:       "image",
			Mime:       mime,
			DataBase64: base64.StdEncoding.EncodeToString(data),
		})
		labels = append(labels, filepath.Base(path))
		cleaned = strings.Replace(cleaned, token, "", 1)
	}
	cleaned = strings.TrimSpace(strings.Join(strings.Fields(cleaned), " "))
	return out, cleaned, labels
}
