// Package runtime — TeamBackend: hybrid VPS + local inference runtime.
package runtime

import (
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/inference"
)

// TeamBackend implements RuntimeBackend for TEAM mode.
// Context is assembled by the VPS (via POST /assistant/plan). Inference
// runs locally (OpenRouter/Ollama). Tools execute in-process with policy
// enforcement from the plan's policy_digest.
type TeamBackend struct {
	mode       config.RuntimeMode
	workspace  string
	provider   *inference.Provider
	client     *api.Client
	status     *RuntimeStatus
	callbacks  *AgentCallbacks
	executor   *ExecutorBridge

	// Cached from last plan
	lastPlan       *api.InferencePlan
	contextVersion int

	// Delta context cache: sessionID → last InferencePlan
	contextCache map[string]*api.InferencePlan

	// WS connection tracking
	wsURL string
}

// NewTeamBackend creates a TEAM-mode backend.
// workspace is the project root; provider is the LLM backend; client
// is the authenticated VPS API client.
func NewTeamBackend(workspace string, provider *inference.Provider, client *api.Client) *TeamBackend {
	exec := NewExecutorBridge(workspace, provider)

	st := NewRuntimeStatus("team", provider.Model)

	// Derive WS URL from API base URL
	wsURL := client.BaseURL
	if wsURL != "" {
		// Convert http(s):// to ws(s):// for WebSocket connection
		if strings.HasPrefix(wsURL, "https://") {
			wsURL = "wss://" + wsURL[8:] + "/ws/connector"
		} else if strings.HasPrefix(wsURL, "http://") {
			wsURL = "ws://" + wsURL[7:] + "/ws/connector"
		}
	}
	st.SetWSStatus(false, wsURL)

	return &TeamBackend{
		mode:         config.ModeTeam,
		workspace:    workspace,
		provider:     provider,
		client:       client,
		executor:     exec,
		status:       st,
		contextCache: make(map[string]*api.InferencePlan),
		wsURL:        wsURL,
	}
}

// Mode returns config.ModeTeam.
func (b *TeamBackend) Mode() config.RuntimeMode { return b.mode }

// Provider returns the LLM inference provider.
func (b *TeamBackend) Provider() *inference.Provider { return b.provider }

// Workspace returns the active workspace path.
func (b *TeamBackend) Workspace() string { return b.workspace }

// Status returns live runtime metrics.
func (b *TeamBackend) Status() *RuntimeStatus { return b.status }

// SetCallbacks stores streaming callbacks for AgentRuntime.
func (b *TeamBackend) SetCallbacks(cbs *AgentCallbacks) { b.callbacks = cbs }

// Plan requests an InferencePlan from the VPS via POST /assistant/plan.
// This is the canonical entry point for a TEAM-mode turn.
// It records plan latency and updates WS status on success/failure.
func (b *TeamBackend) Plan(userText string, sessionID string, history []inference.Message) (*api.InferencePlan, error) {
	start := time.Now()
	plan, err := b.PrepareContext(userText, sessionID, history)
	latencyMs := time.Since(start).Milliseconds()

	b.status.SetPlanLatency(latencyMs)

	if err != nil {
		// Mark WS disconnected on plan failure
		b.status.SetWSStatus(false, b.wsURL)
		return nil, err
	}

	// Plan success implies VPS is reachable
	b.status.SetWSStatus(true, b.wsURL)

	// Mark policy loaded if plan has a non-empty policy digest
	if plan != nil && plan.PolicyDigest.SHA256 != "" {
		b.status.SetPolicyLoaded(true)
	}

	// Cache the plan for delta context on next turn
	if sessionID != "" {
		b.CachePlan(sessionID, plan)
	}

	return plan, nil
}

// PrepareContext requests an InferencePlan from the VPS.
// POST /assistant/plan → parses the response into messages and tools
// for local inference.
// When a cached plan exists for this session and the context version is
// sequential, only delta (new messages) is requested.
// Deprecated: use Plan() instead.
func (b *TeamBackend) PrepareContext(userText string, sessionID string, history []inference.Message) (*api.InferencePlan, error) {
	// Build a PlanRequest
	req := api.PlanRequest{
		Text:           userText,
		ChatSessionID:  sessionID,
		WorkspacePath:  b.workspace,
		Role:           "developer",
		Mode:           "cli",
		ConnectorAlive: true,
	}

	// Check delta context cache: if we have a cached plan for this session
	// and the context version is sequential, request only new messages.
	if cached := b.GetCachedPlan(sessionID); cached != nil {
		if b.contextVersion > 0 {
			req.ContextVersion = &b.contextVersion
		}
	} else if b.contextVersion > 0 {
		req.ContextVersion = &b.contextVersion
	}

	log.Printf("[team] requesting plan: text=%q session=%s version=%d",
		truncateStr(userText, 80), sessionID, b.contextVersion)

	plan, err := b.client.RequestPlan(req)
	if err != nil {
		return nil, fmt.Errorf("plan request failed: %w", err)
	}

	b.lastPlan = plan

	// Update context version for next turn
	if plan.Delta != nil {
		b.contextVersion = plan.Delta.ContextVersion
		// Use only the new messages from delta for the next turn
		// (the plan already contains merged messages; delta is for tracking)
	}

	return plan, nil
}

// ExecuteTools runs tool calls in-process, gated by the plan's policy_digest.

// ── Delta context cache ──────────────────────────────────────────

// GetCachedPlan returns the last InferencePlan for a session.
// Used for delta context: when context_version matches lastVersion+1,
// only new messages from the delta need to be sent.
func (b *TeamBackend) GetCachedPlan(sessionID string) *api.InferencePlan {
	if b.contextCache == nil {
		return nil
	}
	return b.contextCache[sessionID]
}

// CachePlan stores an InferencePlan for a session.
// Subsequent turns can use delta context (only new messages) when the
// context version is sequential.
func (b *TeamBackend) CachePlan(sessionID string, plan *api.InferencePlan) {
	if b.contextCache == nil {
		b.contextCache = make(map[string]*api.InferencePlan)
	}
	b.contextCache[sessionID] = plan
}

// CheckWSHealth performs a quick health check against the VPS to verify
// WebSocket connectivity. Updates the runtime status accordingly.
func (b *TeamBackend) CheckWSHealth() bool {
	if b.client == nil {
		b.status.SetWSStatus(false, b.wsURL)
		return false
	}
	err := b.client.Health()
	connected := err == nil
	b.status.SetWSStatus(connected, b.wsURL)
	return connected
}

// ── Tool execution ───────────────────────────────────────────────
func (b *TeamBackend) ExecuteTools(toolCalls []inference.ToolCall, policy *api.PolicyDigest) ([]ToolResult, error) {
	// If no plan loaded yet, use the default ExecutorBridge policy
	pd := policy
	if pd == nil && b.lastPlan != nil {
		pd = &b.lastPlan.PolicyDigest
	}

	if pd != nil {
		// Filter out denied tools
		var filtered []inference.ToolCall
		var denied []ToolResult
		for _, tc := range toolCalls {
			if pd.IsDenied(tc.Function.Name) {
				log.Printf("[team] tool denied by policy: %s", tc.Function.Name)
				denied = append(denied, ToolResult{
					ToolCallID: tc.ID,
					Name:       tc.Function.Name,
					Error:      fmt.Sprintf("tool denied by team policy: %s", tc.Function.Name),
				})
			} else if pd.RequiresApproval(tc.Function.Name) {
				log.Printf("[team] tool requires approval: %s", tc.Function.Name)
				// In TEAM mode, unapproved write tools are blocked.
				// Future: send to VPS for approval flow.
				denied = append(denied, ToolResult{
					ToolCallID: tc.ID,
					Name:       tc.Function.Name,
					Error:      fmt.Sprintf("tool requires team approval: %s", tc.Function.Name),
				})
			} else {
				filtered = append(filtered, tc)
			}
		}
		results := b.executor.ExecuteAll(filtered, nil, nil)
		return append(results, denied...), nil
	}

	return b.executor.ExecuteAll(toolCalls, nil, nil), nil
}

// ReportComplete reports inference usage to the VPS via POST /connector/inference-complete.
// This is the canonical method for end-of-turn reporting.
func (b *TeamBackend) ReportComplete(requestID string, usage inference.Usage) error {
	return b.CompleteTurn(requestID, usage)
}

// CompleteTurn reports inference usage to the VPS.
// Deprecated: use ReportComplete() instead.
func (b *TeamBackend) CompleteTurn(requestID string, usage inference.Usage) error {
	if b.client == nil || requestID == "" {
		return nil
	}
	log.Printf("[team] turn complete: request=%s tokens=%d", requestID, usage.TotalTokens)
	return b.client.ReportInferenceComplete(requestID, usage)
}
