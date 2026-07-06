// Package ws — WebSocket client for TEAM hybrid mode.
// Connects to wss://{api}/connector/v1/ws with JWT auth via query param.
//
// Message types (CLI→VPS): assistant_turn, tool_result, turn_complete, heartbeat, context_push
// Message types (VPS→CLI): inference_plan, approval_required, policy_denied, stale_diff_warning, ping
//
// Design doc: docs/CLI_RUNTIME_MODES.md §4.4
package ws

import (
	"github.com/centralchurch/central-cli/internal/api"
)

// ── Message interface ───────────────────────────────────────────

// Message is the common interface for all WebSocket protocol messages.
type Message interface {
	// Type returns the message type discriminator (e.g. "assistant_turn").
	Type() string
}

// ── CLI → VPS messages ──────────────────────────────────────────

// AssistantTurn is sent by the CLI to initiate a new inference turn.
type AssistantTurn struct {
	MessageType    string              `json:"type"`
	RequestID      string              `json:"request_id"`
	Text           string              `json:"text"`
	ChatSessionID  string              `json:"chat_session_id,omitempty"`
	WorkItemID     string              `json:"work_item_id,omitempty"`
	AgentName      string              `json:"agent_name,omitempty"`
	ModelOverride  string              `json:"model_override,omitempty"`
	History        []map[string]string `json:"history,omitempty"`
	ContextVersion int                 `json:"context_version,omitempty"`
}

func (m AssistantTurn) Type() string { return "assistant_turn" }

// ToolResult is sent by the CLI after executing a tool call.
type ToolResult struct {
	MessageType string         `json:"type"`
	RequestID   string         `json:"request_id"`
	ToolName    string         `json:"tool_name"`
	ToolCallID  string         `json:"tool_call_id"`
	Result      map[string]any `json:"result"`
	DurationMs  int            `json:"duration_ms"`
	Success     bool           `json:"success"`
	Error       string         `json:"error,omitempty"`
}

func (m ToolResult) Type() string { return "tool_result" }

// TurnComplete is sent by the CLI to signal the end of a turn with usage stats.
type TurnComplete struct {
	MessageType      string              `json:"type"`
	RequestID        string              `json:"request_id"`
	ModelID          string              `json:"model_id"`
	PromptTokens     int                 `json:"prompt_tokens"`
	CompletionTokens int                 `json:"completion_tokens"`
	TotalTokens      int                 `json:"total_tokens"`
	ReplyHash        string              `json:"reply_hash,omitempty"`
	ToolsUsed        []map[string]any    `json:"tools_used,omitempty"`
	FirstTokenMs     int                 `json:"first_token_ms,omitempty"`
	TotalDurationMs  int                 `json:"total_duration_ms"`
	Status           string              `json:"status"`
}

func (m TurnComplete) Type() string { return "turn_complete" }

// Heartbeat is sent periodically by the CLI as a keepalive.
type Heartbeat struct {
	MessageType string  `json:"type"`
	ConnectorID string  `json:"connector_id"`
	Timestamp   float64 `json:"timestamp"`
}

func (m Heartbeat) Type() string { return "heartbeat" }

// ContextPush is sent by the CLI to update L2 context (git branch, active file, etc.).
type ContextPush struct {
	MessageType   string `json:"type"`
	ConnectorID   string `json:"connector_id"`
	GitBranch     string `json:"git_branch,omitempty"`
	GitDirty      bool   `json:"git_dirty"`
	ActiveFile    string `json:"active_file,omitempty"`
	WorkspacePath string `json:"workspace_path,omitempty"`
	ExposedRoot   string `json:"exposed_root,omitempty"`
}

func (m ContextPush) Type() string { return "context_push" }

// ── VPS → CLI messages ──────────────────────────────────────────

// InferencePlanMessage is sent by the VPS in response to an assistant_turn.
type InferencePlanMessage struct {
	MessageType         string             `json:"type"`
	Plan                api.InferencePlan  `json:"plan"`
	ContextVersion      int                `json:"context_version"`
	ApprovalRequiredFor []string           `json:"approval_required_for,omitempty"`
}

func (m InferencePlanMessage) Type() string { return "inference_plan" }

// ApprovalRequired is sent by the VPS when a tool requires HITL approval.
type ApprovalRequired struct {
	MessageType string `json:"type"`
	RequestID   string `json:"request_id"`
	ToolName    string `json:"tool_name"`
	Reason      string `json:"reason,omitempty"`
}

func (m ApprovalRequired) Type() string { return "approval_required" }

// PolicyDenied is sent by the VPS when an action is blocked by policy.
type PolicyDenied struct {
	MessageType string `json:"type"`
	RequestID   string `json:"request_id"`
	Reason      string `json:"reason"`
}

func (m PolicyDenied) Type() string { return "policy_denied" }

// StaleDiffWarning is sent by the VPS when a file was modified since last read.
type StaleDiffWarning struct {
	MessageType string `json:"type"`
	RequestID   string `json:"request_id"`
	FilePath    string `json:"file_path"`
	Message     string `json:"message"`
}

func (m StaleDiffWarning) Type() string { return "stale_diff_warning" }

// ── Internal / system messages ──────────────────────────────────

// rawMessage is a partial decode used to dispatch incoming frames.
type rawMessage struct {
	Type string `json:"type"`
}
