package runtime

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/executor"
	"github.com/centralchurch/central-cli/internal/inference"
	"github.com/centralchurch/central-cli/internal/solo"
	"github.com/centralchurch/central-cli/internal/websearch"
)

// toolSem limits concurrent tool executions to prevent I/O saturation.
var toolSem = make(chan struct{}, 4)

// ── AgentRuntime ────────────────────────────────────────────────

type AgentRuntime struct {
	Provider *inference.Provider
	Context  *ContextLite
	Executor *ExecutorBridge
	
	// Backend is the RuntimeBackend for mode-aware operation.
	// When set, AgentRuntime uses backend.Plan() and backend.ReportComplete().
	// When nil, falls back to direct ContextLite + ExecutorBridge (legacy SOLO).
	Backend RuntimeBackend

	SessionID string

	MaxToolRounds int
	ToolResults   []ToolResult
	TurnStart     time.Time
	LastReply     string

	// Streaming callbacks
	OnToken      func(token string)
	OnToolStart  func(name string, args map[string]any)
	OnToolResult func(name string, output string, err string)
	OnDone       func(usage inference.Usage)
	OnError      func(err error)

	// Runtime status for TUI sidebar
	Status *RuntimeStatus
	
	// planRequestID is set when Backend.Plan() returns a plan; used for ReportComplete.
	planRequestID string
}

type ToolResult struct {
	ToolCallID string
	Name       string
	Output     string
	Error      string
}

// ── Construction ─────────────────────────────────────────────────

func NewAgentRuntime(provider *inference.Provider, ctx *ContextLite, workspace string) *AgentRuntime {
	return &AgentRuntime{
		Provider:      provider,
		Context:       ctx,
		Executor:      NewExecutorBridge(workspace, provider),
		MaxToolRounds: 8,
	}
}

// NewAgentRuntimeWithBackend creates an AgentRuntime that uses a RuntimeBackend for
// plan retrieval and turn completion. This is the recommended constructor for both
// SOLO and TEAM modes. Pass a SoloBackend or TeamBackend as appropriate.
func NewAgentRuntimeWithBackend(provider *inference.Provider, ctx *ContextLite, workspace string, backend RuntimeBackend) *AgentRuntime {
	return &AgentRuntime{
		Provider:      provider,
		Context:       ctx,
		Executor:      NewExecutorBridge(workspace, provider),
		Backend:       backend,
		MaxToolRounds: 8,
	}
}

// ── Run ──────────────────────────────────────────────────────────
// Run executes a full turn with a 5-minute timeout.
func (a *AgentRuntime) Run(userText string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	a.TurnStart = time.Now()
	a.ToolResults = nil
	a.LastReply = ""
	a.planRequestID = ""

	// Load session history if available
	if a.SessionID != "" {
		entries, err := solo.LoadSession(a.SessionID)
		if err == nil && len(entries) > 0 {
			var history []inference.Message
			for _, e := range entries {
				history = append(history, inference.Message{Role: e.Role, Content: e.Content})
			}
			a.Context.History = history
		}
	}

	// Determine messages and tools
	var messages []inference.Message
	var tools []inference.ToolSchema

	if a.Backend != nil {
		// Use backend.Plan() to get the InferencePlan
		plan, err := a.Backend.Plan(userText, a.SessionID, a.Context.History)
		if err != nil {
			return fmt.Errorf("plan: %w", err)
		}
		a.planRequestID = plan.RequestID

		// Convert plan messages/tools to inference types
		messages = planMsgsToInferenceMsgs(plan.Messages)
		tools = planToolsToToolSchemas(plan.Tools)

		log.Printf("[agent] plan mode=%s request=%s: %d messages, %d tools",
			a.Backend.Mode(), plan.RequestID, len(messages), len(tools))
	} else {
		// Legacy SOLO path: use ContextLite directly
		messages = a.Context.BuildMessages(userText)
		tools = a.Context.SelectTools(userText, a.Context.History)
	}

	log.Printf("[agent] turn start: %d messages, %d tools, session=%s", len(messages), len(tools), a.SessionID)

	// Run with context deadline
	errCh := make(chan error, 1)
	go func() {
		replyText, usage, err := a.runLoop(ctx, messages, tools, 0)

		// Report completion via backend if available
		if a.Backend != nil && a.planRequestID != "" {
			if reportErr := a.Backend.ReportComplete(a.planRequestID, usage); reportErr != nil {
				log.Printf("[agent] report complete failed: %v", reportErr)
			}
		}

		if a.SessionID != "" && replyText != "" {
			if saveErr := solo.AppendTurn(a.SessionID, userText, replyText); saveErr != nil {
				log.Printf("[agent] failed to save turn: %v", saveErr)
			}
			solo.AppendAudit("turn_complete", map[string]any{
				"session_id":  a.SessionID,
				"tools_used":  len(a.ToolResults),
				"duration_ms": time.Since(a.TurnStart).Milliseconds(),
			})
		}
		errCh <- err
	}()

	select {
	case err := <-errCh:
		return err
	case <-ctx.Done():
		return fmt.Errorf("turn timeout after %v", time.Since(a.TurnStart))
	}
}

// ── Tool loop ────────────────────────────────────────────────────

func (a *AgentRuntime) runLoop(ctx context.Context, messages []inference.Message, tools []inference.ToolSchema, round int) (string, inference.Usage, error) {
	if round >= a.MaxToolRounds {
		return "", inference.Usage{}, fmt.Errorf("max tool rounds exceeded (%d)", a.MaxToolRounds)
	}
	// Check context before each round
	if ctx.Err() != nil {
		return "", inference.Usage{}, ctx.Err()
	}

	var replyText strings.Builder
	var pendingToolCalls []inference.ToolCall
	var usage inference.Usage

	err := a.Provider.Stream(ctx, messages, tools, func(ev inference.StreamEvent) {
		switch ev.Type {
		case "token":
			replyText.WriteString(ev.Token)
			a.LastReply = replyText.String()
			if a.OnToken != nil {
				a.OnToken(ev.Token)
			}
		case "tool_call":
			pendingToolCalls = ev.Tools
		case "done":
			usage = ev.Usage
		case "error":
			if a.OnError != nil {
				a.OnError(ev.Err)
			}
		}
	})
	if err != nil {
		if a.OnError != nil {
			a.OnError(err)
		}
		return replyText.String(), usage, err
	}

	// No tool calls → turn complete
	if len(pendingToolCalls) == 0 {
		if a.OnDone != nil {
			a.OnDone(usage)
		}
		return replyText.String(), usage, nil
	}

	// Execute tools (read-only in parallel, writes sequential)
	assistantMsg := inference.Message{
		Role:      "assistant",
		Content:   replyText.String(),
		ToolCalls: pendingToolCalls,
	}

	results := a.executeTools(pendingToolCalls)

	var toolMsgs []inference.Message
	for i, tc := range pendingToolCalls {
		output := results[i].Output
		if results[i].Error != "" {
			output = "Error: " + results[i].Error
		}
		toolMsgs = append(toolMsgs, inference.Message{
			Role:       "tool",
			Content:    output,
			ToolCallID: tc.ID,
		})
	}

	// Build next messages: previous + assistant tool_calls + tool results
	nextMessages := make([]inference.Message, 0, len(messages)+1+len(toolMsgs))
	nextMessages = append(nextMessages, messages...)
	nextMessages = append(nextMessages, assistantMsg)
	nextMessages = append(nextMessages, toolMsgs...)

	// Continue with no tools — model already has them
	reply, loopUsage, err := a.runLoop(ctx, nextMessages, nil, round+1)
	// Accumulate usage across tool rounds
	usage.PromptTokens += loopUsage.PromptTokens
	usage.CompletionTokens += loopUsage.CompletionTokens
	usage.TotalTokens += loopUsage.TotalTokens
	return reply, usage, err
}

// ── Parallel tool execution ─────────────────────────────────────

// tool classification
func isReadOnly(name string) bool {
	switch name {
	case "read_file", "search_files", "session_search", "clarify", "web_search", "vision_analyze":
		return true
	case "memory":
		return true // memory search is read-only; add is handled separately
	default:
		return false
	}
}

func isShell(name string) bool {
	return name == "terminal"
}

func isWrite(name string) bool {
	switch name {
	case "write_file", "patch":
		return true
	default:
		return false
	}
}

// executeTools runs all tool calls, parallelizing read-only operations.
func (a *AgentRuntime) executeTools(toolCalls []inference.ToolCall) []ToolResult {
	results := make([]ToolResult, len(toolCalls))

	// Phase 0: read-only — parallel
	readIdx := phaseIndices(toolCalls, isReadOnly)
	if len(readIdx) > 1 {
		a.executeParallel(toolCalls, readIdx, results)
	} else {
		for _, i := range readIdx {
			results[i] = a.executeOne(toolCalls[i])
		}
	}

	// Phase 1: shell — sequential
	for _, i := range phaseIndices(toolCalls, isShell) {
		results[i] = a.executeOne(toolCalls[i])
	}

	// Phase 2: write — sequential
	for _, i := range phaseIndices(toolCalls, isWrite) {
		results[i] = a.executeOne(toolCalls[i])
	}

	return results
}

func phaseIndices(toolCalls []inference.ToolCall, fn func(string) bool) []int {
	var idx []int
	for i, tc := range toolCalls {
		if fn(tc.Function.Name) {
			idx = append(idx, i)
		}
	}
	return idx
}

func (a *AgentRuntime) executeParallel(toolCalls []inference.ToolCall, indices []int, results []ToolResult) {
	var wg sync.WaitGroup
	for _, i := range indices {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			toolSem <- struct{}{}
			defer func() { <-toolSem }()
			results[idx] = a.executeOne(toolCalls[idx])
		}(i)
	}
	wg.Wait()
}

func (a *AgentRuntime) executeOne(tc inference.ToolCall) ToolResult {
	args := parseToolArgs(tc.Function.Arguments)
	argsStr := fmt.Sprintf("%v", args)

	if a.Status != nil {
		a.Status.AddActiveTool(tc.Function.Name, argsStr)
	}

	if a.OnToolStart != nil {
		a.OnToolStart(tc.Function.Name, args)
	}

	output, execErr := a.Executor.Execute(tc.Function.Name, args)

	result := ToolResult{
		ToolCallID: tc.ID,
		Name:       tc.Function.Name,
		Output:     output,
	}
	if execErr != nil {
		result.Error = execErr.Error()
	}
	a.ToolResults = append(a.ToolResults, result)

	if a.Status != nil {
		a.Status.RemoveActiveTool(tc.Function.Name, result)
	}

	if a.OnToolResult != nil {
		a.OnToolResult(tc.Function.Name, output, result.Error)
	}

	return result
}

// ── Tool argument parsing ────────────────────────────────────────

func parseToolArgs(raw string) map[string]any {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return map[string]any{}
	}
	var args map[string]any
	if err := json.Unmarshal([]byte(raw), &args); err != nil {
		log.Printf("[agent] failed to parse tool args: %v (raw=%s)", err, truncateStr(raw, 200))
		return map[string]any{"_raw": raw}
	}
	return args
}

func truncateStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}

// ── ExecutorBridge (typed) ──────────────────────────────────────

type ExecutorBridge struct {
	Workspace string
	Policy    *solo.Policy
	Provider  *inference.Provider
}

func NewExecutorBridge(workspace string, provider *inference.Provider) *ExecutorBridge {
	policy, err := solo.LoadPolicy()
	if err != nil {
		log.Printf("[agent] failed to load policy, using defaults: %v", err)
		policy = solo.DefaultPolicy()
	}
	return &ExecutorBridge{Workspace: workspace, Policy: policy, Provider: provider}
}

// ExecuteAll runs a list of tool calls with the standard phase strategy:
// read-only tools in parallel, then shell sequentially, then writes sequentially.
// It invokes the provided callbacks for status updates.
func (e *ExecutorBridge) ExecuteAll(toolCalls []inference.ToolCall, onStart func(name string, args map[string]any), onResult func(name, output, errStr string)) []ToolResult {
	results := make([]ToolResult, len(toolCalls))

	// Phase 0: read-only — parallel
	readIdx := phaseIndices(toolCalls, isReadOnly)
	if len(readIdx) > 1 {
		e.executeParallel(toolCalls, readIdx, results, onStart, onResult)
	} else {
		for _, i := range readIdx {
			results[i] = e.executeOneWithCB(toolCalls[i], onStart, onResult)
		}
	}

	// Phase 1: shell — sequential
	for _, i := range phaseIndices(toolCalls, isShell) {
		results[i] = e.executeOneWithCB(toolCalls[i], onStart, onResult)
	}

	// Phase 2: write — sequential
	for _, i := range phaseIndices(toolCalls, isWrite) {
		results[i] = e.executeOneWithCB(toolCalls[i], onStart, onResult)
	}

	return results
}

// executeParallel runs tool calls concurrently with semaphore gating.
func (e *ExecutorBridge) executeParallel(toolCalls []inference.ToolCall, indices []int, results []ToolResult, onStart func(string, map[string]any), onResult func(string, string, string)) {
	var wg sync.WaitGroup
	for _, i := range indices {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			toolSem <- struct{}{}
			defer func() { <-toolSem }()
			results[idx] = e.executeOneWithCB(toolCalls[idx], onStart, onResult)
		}(i)
	}
	wg.Wait()
}

// executeOneWithCB executes a single tool call with callbacks.
func (e *ExecutorBridge) executeOneWithCB(tc inference.ToolCall, onStart func(string, map[string]any), onResult func(string, string, string)) ToolResult {
	args := parseToolArgs(tc.Function.Arguments)
	if onStart != nil {
		onStart(tc.Function.Name, args)
	}
	output, execErr := e.Execute(tc.Function.Name, args)
	result := ToolResult{
		ToolCallID: tc.ID,
		Name:       tc.Function.Name,
		Output:     output,
	}
	if execErr != nil {
		result.Error = execErr.Error()
	}
	if onResult != nil {
		onResult(tc.Function.Name, output, result.Error)
	}
	return result
}

// Execute dispatches a tool call by name with JSON arguments.
func (e *ExecutorBridge) Execute(name string, args map[string]any) (string, error) {
	result := e.Policy.CheckToolPolicy(name)
	if !result.Allowed {
		return "", fmt.Errorf("policy denied: %s", result.Reason)
	}
	if result.RequiresApproval {
		log.Printf("[agent] tool %s requires confirmation (policy)", name)
	}

	switch name {
	case "read_file":
		return e.ReadFile(
			strArg(args, "path"),
			intArg(args, "offset", 1),
			intArg(args, "limit", 500),
		)
	case "write_file":
		return e.WriteFile(
			strArg(args, "path"),
			strArg(args, "content"),
		)
	case "search_files":
		return e.SearchFiles(
			strArg(args, "pattern"),
			strArg(args, "path"),
			strArg(args, "file_glob"),
		)
	case "patch":
		return e.Patch(
			strArg(args, "path"),
			strArg(args, "old_string"),
			strArg(args, "new_string"),
		)
	case "terminal":
		return e.Terminal(
			strArg(args, "command"),
			intArg(args, "timeout", 120),
		)
	case "memory":
		return e.Memory(
			strArg(args, "action"),
			strArg(args, "content"),
		)
	case "session_search":
		return e.SessionSearch(
			strArg(args, "query"),
			intArg(args, "limit", 10),
		)
	case "manage_work_item":
		return e.ManageWorkItem(
			strArg(args, "action"),
			strArg(args, "title"),
			strArg(args, "priority"),
			strArg(args, "context"),
			strArg(args, "id"),
		)
	case "clarify":
		return e.Clarify(strArg(args, "question"))
	case "web_search":
		return e.WebSearch(
			strArg(args, "query"),
			intArg(args, "limit", 5),
		)
	case "vision_analyze":
		return e.VisionAnalyze(
			strArg(args, "image_url"),
			strArg(args, "question"),
		)
	default:
		return "", fmt.Errorf("unknown tool: %s", name)
	}
}

// ── Typed tool methods ─────────────────────────────────────────

func (e *ExecutorBridge) ReadFile(path string, offset, limit int) (string, error) {
	if path == "" {
		return "", fmt.Errorf("path is required")
	}
	result, _ := executor.Execute("read_file", map[string]any{
		"path": path, "offset": float64(offset), "limit": float64(limit),
	}, e.Workspace)
	return execOutput(result)
}

func (e *ExecutorBridge) WriteFile(path, content string) (string, error) {
	if path == "" || content == "" {
		return "", fmt.Errorf("path and content are required")
	}
	result, _ := executor.Execute("write_file", map[string]any{
		"path": path, "content": content,
	}, e.Workspace)
	return execOutput(result)
}

func (e *ExecutorBridge) SearchFiles(pattern, dir, fileGlob string) (string, error) {
	if pattern == "" {
		return "", fmt.Errorf("pattern is required")
	}
	if dir == "" {
		dir = e.Workspace
	}
	payload := map[string]any{"pattern": pattern, "path": dir}
	if fileGlob != "" {
		payload["file_glob"] = fileGlob
	}
	result, _ := executor.Execute("search_files", payload, e.Workspace)
	return execOutput(result)
}

func (e *ExecutorBridge) Patch(path, oldString, newString string) (string, error) {
	if path == "" || oldString == "" {
		return "", fmt.Errorf("path and old_string are required")
	}
	result, _ := executor.Execute("patch", map[string]any{
		"path": path, "old_string": oldString, "new_string": newString,
	}, e.Workspace)
	return execOutput(result)
}

func (e *ExecutorBridge) Terminal(command string, timeout int) (string, error) {
	if command == "" {
		return "", fmt.Errorf("command is required")
	}
	result, _ := executor.Execute("terminal", map[string]any{
		"sh_c": command, "timeout_sec": float64(timeout),
	}, e.Workspace)
	if errStr, _ := result["error"].(string); errStr != "" {
		return "", fmt.Errorf(errStr)
	}
	stdout, _ := result["stdout"].(string)
	stderr, _ := result["stderr"].(string)
	exitCode, _ := result["exit_code"].(float64)
	out := stdout
	if stderr != "" {
		out += "\n[stderr]\n" + stderr
	}
	if exitCode != 0 {
		out += fmt.Sprintf("\n[exit code: %.0f]", exitCode)
	}
	return out, nil
}

func (e *ExecutorBridge) Memory(action, content string) (string, error) {
	if action == "" || content == "" {
		return "", fmt.Errorf("action and content are required")
	}
	switch action {
	case "add":
		if err := solo.AddMemoryFact(content); err != nil {
			return "", fmt.Errorf("memory save failed: %w", err)
		}
		return "Memory saved.", nil
	case "search", "recall":
		m, err := solo.LoadMemory()
		if err != nil {
			return "", fmt.Errorf("memory read failed: %w", err)
		}
		if len(m.Facts) == 0 {
			return "No memories found.", nil
		}
		var sb strings.Builder
		sb.WriteString("Memories:\n")
		for i, f := range m.Facts {
			if i >= 10 {
				sb.WriteString(fmt.Sprintf("... and %d more", len(m.Facts)-10))
				break
			}
			sb.WriteString(fmt.Sprintf("- %s\n", f.Content))
		}
		return sb.String(), nil
	default:
		return fmt.Sprintf("Memory action '%s' not supported. Use 'add' or 'search'.", action), nil
	}
}

// SessionSearch queries past conversations using FTS5.
func (e *ExecutorBridge) SessionSearch(query string, limit int) (string, error) {
	if query == "" {
		return "", fmt.Errorf("query is required")
	}
	entries, err := solo.SearchSessions(query, limit)
	if err != nil {
		return "", fmt.Errorf("session search failed: %w", err)
	}
	if len(entries) == 0 {
		return "No matching conversations found.", nil
	}
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("Found %d matches:\n", len(entries)))
	for i, e := range entries {
		if i >= limit {
			break
		}
		sb.WriteString(fmt.Sprintf("[%s] %s\n", e.Role, truncateStr(e.Content, 300)))
	}
	return sb.String(), nil
}

// ManageWorkItem handles the local work queue (SOLO mode).
func (e *ExecutorBridge) ManageWorkItem(action, title, priority, context, id string) (string, error) {
	if action == "" {
		return "", fmt.Errorf("action is required: create, list, update, or delete")
	}
	if priority == "" {
		priority = "normal"
	}
	switch action {
	case "create", "add":
		if title == "" {
			return "", fmt.Errorf("title is required for create")
		}
		wi, err := solo.AddWorkItem(title, priority, context)
		if err != nil {
			return "", fmt.Errorf("failed to create work item: %w", err)
		}
		return fmt.Sprintf("Work item created: %s (%s priority)", wi.ID, wi.Priority), nil
	case "list":
		items, err := solo.ListWorkItems("")
		if err != nil {
			return "", fmt.Errorf("failed to list work items: %w", err)
		}
		if len(items) == 0 {
			return "No work items in queue.", nil
		}
		var sb strings.Builder
		sb.WriteString(fmt.Sprintf("Work Queue (%d items):\n", len(items)))
		for _, wi := range items {
			icon := "○"
			if wi.Status == "in_progress" {
				icon = "◉"
			} else if wi.Status == "done" {
				icon = "✓"
			} else if wi.Status == "cancelled" {
				icon = "✗"
			}
			prio := ""
			if wi.Priority == "urgent" || wi.Priority == "high" {
				prio = fmt.Sprintf(" [%s]", wi.Priority)
			}
			sb.WriteString(fmt.Sprintf("  %s %s%s - %s\n", icon, wi.ID, prio, wi.Title))
		}
		return sb.String(), nil
	case "update", "status":
		if id == "" {
			return "", fmt.Errorf("id is required for update")
		}
		status := title // title field reused for status
		if status == "" {
			status = "in_progress"
		}
		if err := solo.UpdateWorkItemStatus(id, status); err != nil {
			return "", fmt.Errorf("failed to update work item: %w", err)
		}
		return fmt.Sprintf("Work item %s updated to %s.", id, status), nil
	case "delete", "remove":
		if id == "" {
			return "", fmt.Errorf("id is required for delete")
		}
		if err := solo.DeleteWorkItem(id); err != nil {
			return "", fmt.Errorf("failed to delete work item: %w", err)
		}
		return fmt.Sprintf("Work item %s deleted.", id), nil
	default:
		return fmt.Sprintf("Unknown action '%s'. Use: create, list, update, delete.", action), nil
	}
}

// Clarify asks the user a question and returns the answer from the chat input.
func (e *ExecutorBridge) Clarify(question string) (string, error) {
	if question == "" {
		return "Please specify a question.", nil
	}
	return fmt.Sprintf("[CLARIFY] %s\nReply in the chat input.", question), nil
}

// WebSearch performs a web search and returns formatted results.
func (e *ExecutorBridge) WebSearch(query string, limit int) (string, error) {
	if query == "" {
		return "", fmt.Errorf("query is required")
	}
	if limit <= 0 {
		limit = 5
	}
	results, err := websearch.Search(query, limit)
	if err != nil {
		return "", fmt.Errorf("search failed: %w", err)
	}
	if len(results) == 0 {
		return fmt.Sprintf("No results found for: %s", query), nil
	}
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("Search results for \"%s\":\n\n", query))
	for i, r := range results {
		sb.WriteString(fmt.Sprintf("%d. %s\n", i+1, r.Title))
		sb.WriteString(fmt.Sprintf("   %s\n", r.URL))
		if r.Snippet != "" {
			sb.WriteString(fmt.Sprintf("   %s\n", r.Snippet))
		}
		sb.WriteString("\n")
	}
	return sb.String(), nil
}

// VisionAnalyze sends an image to the LLM provider for analysis.
func (e *ExecutorBridge) VisionAnalyze(imagePath, question string) (string, error) {
	if imagePath == "" {
		return "", fmt.Errorf("image_url is required")
	}
	if e.Provider == nil {
		return "", fmt.Errorf("no provider configured for vision analysis")
	}
	return e.Provider.AnalyzeImage(imagePath, question)
}

// ── Argument helpers ────────────────────────────────────────────
func strArg(args map[string]any, key string) string {
	s, _ := args[key].(string)
	return s
}

func intArg(args map[string]any, key string, defaultVal int) int {
	switch v := args[key].(type) {
	case float64:
		return int(v)
	case int:
		return v
	case int64:
		return int(v)
	default:
		return defaultVal
	}
}

func execOutput(result map[string]any) (string, error) {
	if errStr, _ := result["error"].(string); errStr != "" {
		return "", fmt.Errorf(errStr)
	}
	out, _ := result["stdout"].(string)
	if out == "" {
		out = "ok"
	}
	return out, nil
}

// ── Plan conversion helpers ──────────────────────────────────────

// planMsgsToInferenceMsgs converts api.InferenceMsg slice to inference.Message slice.
func planMsgsToInferenceMsgs(msgs []api.InferenceMsg) []inference.Message {
	result := make([]inference.Message, len(msgs))
	for i, m := range msgs {
		result[i] = inference.Message{Role: m.Role, Content: m.Content}
	}
	return result
}

// planToolsToToolSchemas converts api.ToolDef slice to inference.ToolSchema slice.
func planToolsToToolSchemas(tools []api.ToolDef) []inference.ToolSchema {
	result := make([]inference.ToolSchema, len(tools))
	for i, t := range tools {
		result[i] = inference.ToolSchema{
			Type: t.Type,
			Function: struct {
				Name        string         `json:"name"`
				Description string         `json:"description"`
				Parameters  map[string]any `json:"parameters"`
			}{
				Name:        t.Function.Name,
				Description: t.Function.Description,
				Parameters:  t.Function.Parameters,
			},
		}
	}
	return result
}
