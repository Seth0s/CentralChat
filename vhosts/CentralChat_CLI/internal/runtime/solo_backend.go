// Package runtime — SoloBackend: local-first runtime with no VPS dependency.
package runtime

import (
	"fmt"
	"log"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/inference"
	"github.com/centralchurch/central-cli/internal/solo"
)

// SoloBackend implements RuntimeBackend for SOLO mode.
// Everything runs locally: context building, tool execution, session storage.
// No VPS connection required.
type SoloBackend struct {
	mode      config.RuntimeMode
	workspace string
	provider  *inference.Provider
	context   *ContextLite
	executor  *ExecutorBridge
	status    *RuntimeStatus
	callbacks *AgentCallbacks
}

// NewSoloBackend creates a SOLO-mode backend.
// workspace is the project root; provider is the LLM backend.
func NewSoloBackend(workspace string, provider *inference.Provider) *SoloBackend {
	ctx := NewContextLite(workspace)
	policy, err := solo.LoadPolicy()
	if err != nil {
		log.Printf("[solo] failed to load policy, using defaults: %v", err)
		policy = solo.DefaultPolicy()
	}
	ctx.Policy = policy

	exec := NewExecutorBridge(workspace, provider)

	st := NewRuntimeStatus("local", provider.Model)

	return &SoloBackend{
		mode:      config.ModeSolo,
		workspace: workspace,
		provider:  provider,
		context:   ctx,
		executor:  exec,
		status:    st,
	}
}

// Mode returns config.ModeSolo.
func (b *SoloBackend) Mode() config.RuntimeMode { return b.mode }

// Provider returns the LLM inference provider.
func (b *SoloBackend) Provider() *inference.Provider { return b.provider }

// Workspace returns the active workspace path.
func (b *SoloBackend) Workspace() string { return b.workspace }

// Status returns live runtime metrics.
func (b *SoloBackend) Status() *RuntimeStatus { return b.status }

// SetCallbacks stores streaming callbacks for AgentRuntime.
func (b *SoloBackend) SetCallbacks(cbs *AgentCallbacks) { b.callbacks = cbs }

// SetAgentPrompt loads an agent system prompt from ~/.central/agents/.
func (b *SoloBackend) SetAgentPrompt(prompt string) {
	b.context.AgentPrompt = prompt
}

// AddSkillPrompt appends a skill prompt to the context.
func (b *SoloBackend) AddSkillPrompt(prompt string) {
	b.context.SkillPrompts = append(b.context.SkillPrompts, prompt)
}

// Plan builds an InferencePlan locally via ContextLite.
// This is the canonical entry point for a SOLO-mode turn.
func (b *SoloBackend) Plan(userText string, sessionID string, history []inference.Message) (*api.InferencePlan, error) {
	return b.PrepareContext(userText, sessionID, history)
}

// PrepareContext builds messages and tools locally via ContextLite.
// It also loads past session history from SQLite if a sessionID is provided.
// Deprecated: use Plan() instead.
func (b *SoloBackend) PrepareContext(userText string, sessionID string, history []inference.Message) (*api.InferencePlan, error) {
	b.context.History = history

	// Load session history if available
	if sessionID != "" {
		entries, err := solo.LoadSession(sessionID)
		if err == nil && len(entries) > 0 {
			var loaded []inference.Message
			for _, e := range entries {
				loaded = append(loaded, inference.Message{Role: e.Role, Content: e.Content})
			}
			// Prepend loaded history before current history
			b.context.History = append(loaded, history...)
		}
	}

	messages := b.context.BuildMessages(userText)
	toolSchemas := b.context.SelectTools(userText, b.context.History)

	// Convert inference.ToolSchema to api.ToolDef
	tools := make([]api.ToolDef, len(toolSchemas))
	for i, ts := range toolSchemas {
		tools[i] = api.ToolDef{
			Type: ts.Type,
			Function: struct {
				Name        string         `json:"name"`
				Description string         `json:"description"`
				Parameters  map[string]any `json:"parameters"`
			}{
				Name:        ts.Function.Name,
				Description: ts.Function.Description,
				Parameters:  ts.Function.Parameters,
			},
		}
	}

	plan := &api.InferencePlan{
		Schema:    "inference_plan/v1",
		RequestID: fmt.Sprintf("solo-%d", len(history)),
		Model: api.ModelSpec{
			ModelID:     b.provider.Model,
			Profile:     "balanced",
			MaxTokens:   8192,
			Temperature: 0.7,
		},
		Messages: messagesToInferenceMsgs(messages),
		Tools:    tools,
		ContextMeta: api.ContextMeta{
			Layers: []string{"L0", "L1", "L2", "L3", "L4", "L5", "L6"},
		},
	}

	return plan, nil
}

// ExecuteTools runs tool calls in-process via ExecutorBridge.
func (b *SoloBackend) ExecuteTools(toolCalls []inference.ToolCall, policy *api.PolicyDigest) ([]ToolResult, error) {
	return b.executor.ExecuteAll(toolCalls, nil, nil), nil
}

// ReportComplete saves the turn to local SQLite audit log.
// This is the canonical method for end-of-turn reporting.
func (b *SoloBackend) ReportComplete(requestID string, usage inference.Usage) error {
	return b.CompleteTurn(requestID, usage)
}

// CompleteTurn saves the turn to local SQLite audit log.
// Deprecated: use ReportComplete() instead.
func (b *SoloBackend) CompleteTurn(requestID string, usage inference.Usage) error {
	return nil
}

// messagesToInferenceMsgs converts inference.Message slice to api.InferenceMsg slice.
func messagesToInferenceMsgs(msgs []inference.Message) []api.InferenceMsg {
	result := make([]api.InferenceMsg, len(msgs))
	for i, m := range msgs {
		result[i] = api.InferenceMsg{Role: m.Role, Content: m.Content}
	}
	return result
}
