// Package api — InferencePlan client for TEAM hybrid inference.
//
// POST /assistant/plan — requests an InferencePlan from the VPS.
// POST /connector/inference-complete — reports inference usage.
//
// Design doc: docs/CLI_RUNTIME_MODES.md §4.2–4.3
package api

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// ── PlanRequest ─────────────────────────────────────────────────

// PlanRequest is sent to POST /assistant/plan.
// Mirrors the Python PlanRequest schema in inference_plan.py.
type PlanRequest struct {
	Text             string            `json:"text"`
	ChatSessionID    string            `json:"chat_session_id,omitempty"`
	WorkItemID       string            `json:"work_item_id,omitempty"`
	AgentName        string            `json:"agent_name,omitempty"`
	ModelOverride    string            `json:"model_override,omitempty"`
	History          []map[string]string `json:"history,omitempty"`
	TenantID         string            `json:"tenant_id,omitempty"`
	Role             string            `json:"role,omitempty"`
	Mode             string            `json:"mode,omitempty"`
	ConnectorAlive   bool              `json:"connector_alive"`
	ConnectorID      string            `json:"connector_id,omitempty"`
	WorkspacePath    string            `json:"workspace_path,omitempty"`
	FocusMode        bool              `json:"focus_mode"`
	SessionMode      string            `json:"session_mode,omitempty"`
	HandoffFromSessionID string        `json:"handoff_from_session_id,omitempty"`
	ContextVersion   *int              `json:"context_version,omitempty"`
}

// ── PlanResponse ────────────────────────────────────────────────

// PlanResponse is the VPS response to a plan request.
type PlanResponse struct {
	Plan        InferencePlan `json:"plan"`
	Status      string        `json:"status"`
	BlockReason string        `json:"block_reason,omitempty"`
}

// InferencePlan is the Go mapping of the VPS contract.
type InferencePlan struct {
	Schema        string          `json:"schema"`
	RequestID     string          `json:"request_id"`
	ChatSessionID string          `json:"chat_session_id,omitempty"`
	WorkItemID    string          `json:"work_item_id,omitempty"`
	Model         ModelSpec       `json:"model"`
	Messages      []InferenceMsg  `json:"messages"`
	Tools         []ToolDef       `json:"tools"`
	ToolCatalog   []string        `json:"tool_catalog,omitempty"`
	PolicyDigest  PolicyDigest    `json:"policy_digest"`
	ContextMeta   ContextMeta     `json:"context_meta"`
	Delta         *DeltaContext   `json:"delta,omitempty"`
}

// InferenceMsg is a chat message in the plan.
type InferenceMsg struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ToolDef matches the OpenAI function tool schema.
type ToolDef struct {
	Type     string `json:"type"`
	Function struct {
		Name        string         `json:"name"`
		Description string         `json:"description"`
		Parameters  map[string]any `json:"parameters"`
	} `json:"function"`
}

// ModelSpec defines which LLM the CLI should call.
type ModelSpec struct {
	ModelID     string  `json:"model_id"`
	Profile     string  `json:"profile"`
	MaxTokens   int     `json:"max_tokens"`
	Temperature float64 `json:"temperature"`
}

// PolicyDigest is a compact policy summary for local enforcement.
type PolicyDigest struct {
	SHA256              string   `json:"sha256"`
	AllowedWritePaths   []string `json:"allowed_write_paths"`
	DeniedTools         []string `json:"denied_tools"`
	RequiresApprovalFor []string `json:"requires_approval_for"`
	DLPEnabled          bool     `json:"dlp_enabled"`
	FocusMode           bool     `json:"focus_mode"`
	Role                string   `json:"role"`
}

// ContextMeta tracks what context layers were applied.
type ContextMeta struct {
	Layers           []string `json:"layers"`
	UITraceSummaryPt string   `json:"ui_trace_summary_pt"`
	BuildMs          float64  `json:"build_ms"`
	SessionTruncated bool     `json:"session_truncated"`
	RecallCount      int      `json:"recall_count"`
}

// DeltaContext is incremental context for subsequent turns.
type DeltaContext struct {
	BaseVersion     int             `json:"base_version"`
	AppendMessages  []InferenceMsg  `json:"append_messages"`
	ContextVersion  int             `json:"context_version"`
}

// ── Client methods ──────────────────────────────────────────────

// IsDenied returns true if a tool is denied by this policy.
func (p *PolicyDigest) IsDenied(toolName string) bool {
	for _, t := range p.DeniedTools {
		if t == toolName {
			return true
		}
	}
	return false
}

// RequiresApproval returns true if a tool requires confirmation.
func (p *PolicyDigest) RequiresApproval(toolName string) bool {
	for _, t := range p.RequiresApprovalFor {
		if t == toolName {
			return true
		}
	}
	return false
}

// RequestPlan calls POST /assistant/plan to get an InferencePlan.
func (c *Client) RequestPlan(req PlanRequest) (*InferencePlan, error) {
	resp, err := c.do(http.MethodPost, "/assistant/plan", req, nil)
	if err != nil {
		return nil, fmt.Errorf("plan request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("plan request failed (%d): %s", resp.StatusCode, string(body))
	}

	var planResp PlanResponse
	if err := json.NewDecoder(resp.Body).Decode(&planResp); err != nil {
		return nil, fmt.Errorf("decode plan response: %w", err)
	}

	if planResp.Status == "blocked" {
		return nil, fmt.Errorf("plan blocked: %s", planResp.BlockReason)
	}
	if planResp.Status == "error" {
		return nil, fmt.Errorf("plan error: %s", planResp.BlockReason)
	}

	return &planResp.Plan, nil
}

// ReportInferenceComplete sends inference usage to the VPS.
// POST /connector/inference-complete
func (c *Client) ReportInferenceComplete(requestID string, usage interface{}) error {
	body := map[string]any{
		"request_id": requestID,
		"usage":      usage,
	}

	resp, err := c.do(http.MethodPost, "/connector/inference-complete", body, nil)
	if err != nil {
		return fmt.Errorf("inference complete report: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("inference complete report failed (%d): %s", resp.StatusCode, string(b))
	}

	return nil
}
