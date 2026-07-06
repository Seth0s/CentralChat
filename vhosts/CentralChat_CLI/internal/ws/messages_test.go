package ws

import (
	"encoding/json"
	"testing"

	"github.com/centralchurch/central-cli/internal/api"
)

// TestMessageRoundtrip verifies that every message type serializes
// and deserializes correctly through the parseMessage dispatch.
func TestMessageRoundtrip(t *testing.T) {
	tests := []struct {
		name string
		in   interface {
			Type() string
		}
		wantType string
	}{
		{
			name: "assistant_turn",
			in: AssistantTurn{
				MessageType:    "assistant_turn",
				RequestID:      "req-1",
				Text:           "hello",
				ChatSessionID:  "sess-1",
				ContextVersion: 3,
			},
			wantType: "assistant_turn",
		},
		{
			name: "tool_result",
			in: ToolResult{
				MessageType: "tool_result",
				RequestID:   "req-1",
				ToolName:    "read_file",
				ToolCallID:  "call-1",
				Result:      map[string]any{"content": "hello world"},
				DurationMs:  150,
				Success:     true,
			},
			wantType: "tool_result",
		},
		{
			name: "turn_complete",
			in: TurnComplete{
				MessageType:      "turn_complete",
				RequestID:        "req-1",
				ModelID:          "gpt-4o",
				PromptTokens:     100,
				CompletionTokens: 200,
				TotalTokens:      300,
				FirstTokenMs:     180,
				Status:           "completed",
			},
			wantType: "turn_complete",
		},
		{
			name: "heartbeat",
			in: Heartbeat{
				MessageType: "heartbeat",
				ConnectorID: "conn-1",
				Timestamp:   1719432000.5,
			},
			wantType: "heartbeat",
		},
		{
			name: "context_push",
			in: ContextPush{
				MessageType:   "context_push",
				ConnectorID:   "conn-1",
				GitBranch:     "main",
				GitDirty:      true,
				ActiveFile:    "src/main.go",
				WorkspacePath: "/home/dev",
				ExposedRoot:   "/home/dev",
			},
			wantType: "context_push",
		},
		{
			name: "inference_plan",
			in: InferencePlanMessage{
				MessageType: "inference_plan",
				Plan: api.InferencePlan{
					Schema:    "v1",
					RequestID: "req-1",
					Model: api.ModelSpec{
						ModelID:     "gpt-4o",
						MaxTokens:   4096,
						Temperature: 0.7,
					},
					Messages: []api.InferenceMsg{
						{Role: "system", Content: "You are helpful."},
					},
				},
				ContextVersion:      5,
				ApprovalRequiredFor: []string{"shell.exec"},
			},
			wantType: "inference_plan",
		},
		{
			name: "approval_required",
			in: ApprovalRequired{
				MessageType: "approval_required",
				RequestID:   "req-1",
				ToolName:    "shell.exec",
				Reason:      "dangerous command",
			},
			wantType: "approval_required",
		},
		{
			name: "policy_denied",
			in: PolicyDenied{
				MessageType: "policy_denied",
				RequestID:   "req-1",
				Reason:      "tool blocked by policy",
			},
			wantType: "policy_denied",
		},
		{
			name: "stale_diff_warning",
			in: StaleDiffWarning{
				MessageType: "stale_diff_warning",
				RequestID:   "req-1",
				FilePath:    "/tmp/x.txt",
				Message:     "File changed since last read.",
			},
			wantType: "stale_diff_warning",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Marshal
			b, err := json.Marshal(tt.in)
			if err != nil {
				t.Fatalf("marshal: %v", err)
			}

			// Parse back via dispatcher (simulates receiving)
			msg, err := parseMessage(b)
			if err != nil {
				t.Fatalf("parseMessage: %v", err)
			}

			if msg.Type() != tt.wantType {
				t.Errorf("Type() = %q, want %q", msg.Type(), tt.wantType)
			}

			// Verify "type" field was preserved in raw JSON
			var raw map[string]any
			if err := json.Unmarshal(b, &raw); err != nil {
				t.Fatalf("unmarshal raw: %v", err)
			}
			if raw["type"] != tt.wantType {
				t.Errorf("raw JSON type = %q, want %q", raw["type"], tt.wantType)
			}
		})
	}
}

// TestMessageInterface ensures all outbound types implement Message.
func TestMessageInterface(t *testing.T) {
	var _ Message = AssistantTurn{}
	var _ Message = ToolResult{}
	var _ Message = TurnComplete{}
	var _ Message = Heartbeat{}
	var _ Message = ContextPush{}
	var _ Message = InferencePlanMessage{}
	var _ Message = ApprovalRequired{}
	var _ Message = PolicyDenied{}
	var _ Message = StaleDiffWarning{}
	var _ Message = pingMessage{}
	var _ Message = ackMessage{}
	var _ Message = unknownMessage{}
}

// TestPingMessage ensures ping/ack types parse correctly.
func TestSystemMessages(t *testing.T) {
	// ping
	pingRaw := []byte(`{"type":"ping"}`)
	msg, err := parseMessage(pingRaw)
	if err != nil {
		t.Fatalf("parse ping: %v", err)
	}
	if msg.Type() != "ping" {
		t.Errorf("expected ping, got %q", msg.Type())
	}

	// welcome ack
	ackRaw := []byte(`{"type":"welcome","connector_id":"c1"}`)
	msg, err = parseMessage(ackRaw)
	if err != nil {
		t.Fatalf("parse welcome: %v", err)
	}
	if msg.Type() != "welcome" {
		t.Errorf("expected welcome, got %q", msg.Type())
	}

	// unknown type should not error
	unkRaw := []byte(`{"type":"future_type","data":42}`)
	msg, err = parseMessage(unkRaw)
	if err != nil {
		t.Fatalf("parse unknown: %v", err)
	}
	if msg.Type() != "future_type" {
		t.Errorf("expected future_type, got %q", msg.Type())
	}
}

// TestInferencePlanReuse verifies the api.InferencePlan struct is correctly reused.
func TestInferencePlanReuse(t *testing.T) {
	raw := []byte(`{
		"type": "inference_plan",
		"plan": {
			"schema": "v1",
			"request_id": "req-abc",
			"model": {"model_id": "gpt-4o", "profile": "", "max_tokens": 8000, "temperature": 0.5},
			"messages": [{"role": "system", "content": "You are helpful."}],
			"tools": [],
			"policy_digest": {
				"sha256": "abc123",
				"allowed_write_paths": ["/tmp"],
				"denied_tools": [],
				"requires_approval_for": ["shell.exec"],
				"dlp_enabled": true,
				"focus_mode": false,
				"role": "developer"
			},
			"context_meta": {
				"layers": ["git", "file"],
				"ui_trace_summary_pt": "",
				"build_ms": 42.0,
				"session_truncated": false,
				"recall_count": 3
			}
		},
		"context_version": 2,
		"approval_required_for": ["shell.exec"]
	}`)

	msg, err := parseMessage(raw)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}

	planMsg, ok := msg.(InferencePlanMessage)
	if !ok {
		t.Fatalf("expected InferencePlanMessage, got %T", msg)
	}

	if planMsg.Plan.RequestID != "req-abc" {
		t.Errorf("request_id = %q", planMsg.Plan.RequestID)
	}
	if planMsg.ContextVersion != 2 {
		t.Errorf("context_version = %d", planMsg.ContextVersion)
	}
	if len(planMsg.ApprovalRequiredFor) != 1 || planMsg.ApprovalRequiredFor[0] != "shell.exec" {
		t.Errorf("approval_required_for = %v", planMsg.ApprovalRequiredFor)
	}
	if !planMsg.Plan.PolicyDigest.DLPEnabled {
		t.Error("DLPEnabled should be true")
	}
}
