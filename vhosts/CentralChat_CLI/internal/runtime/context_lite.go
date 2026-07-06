// Package runtime — AgentRuntime and backends for SOLO and TEAM modes.
package runtime

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/centralchurch/central-cli/internal/inference"
	"github.com/centralchurch/central-cli/internal/solo"
)

// ContextLite builds a minimal context for SOLO mode.
// No PG, no RAG, no team rules — just what the agent needs locally.
type ContextLite struct {
	// Config
	Workspace    string
	AgentPrompt  string   // loaded from ~/.config/central/agents/
	SkillPrompts []string // loaded from ~/.config/central/skills/
	History      []inference.Message

	// Tool selection
	AvailableTools []string // tool names available (depends on connector/CLI)

	// L0: DLP
	DLPEnabled bool

	// L4: Governance
	Policy *solo.Policy

	// Cache for system messages (invalidated when agent/skills/workspace/policy change)
	cachedSystem []inference.Message
	cacheKey     string
}

// NewContextLite creates a context builder for solo mode.
func NewContextLite(workspace string) *ContextLite {
	return &ContextLite{
		Workspace:      workspace,
		AvailableTools: allToolNames(),
	}
}

// ToolNames returns the full tool catalog for CLI SOLO mode.
func ToolNames() []string {
	return allToolNames()
}

// allToolNames returns the full tool catalog for CLI mode.
func allToolNames() []string {
	return []string{
		"read_file", "write_file", "search_files", "patch",
		"terminal",
		"memory", "session_search", "clarify",
		"manage_work_item",
		"web_search", "vision_analyze",
	}
}

// keyword triggers for tool scoring (same algorithm as backend ToolInjector).
var toolTriggers = map[string][]string{
	"terminal":       {"executar", "comando", "shell", "bash", "run", "cmd", "terminal", "script", "build", "testar", "instalar", "compilar", "git", "npm", "pip", "docker", "podman"},
	"read_file":      {"ler", "ficheiro", "arquivo", "file", "código", "source", "conteúdo", "linhas", "abrir"},
	"write_file":     {"criar", "escrever", "criar ficheiro", "novo ficheiro", "write", "gerar", "output", "salvar"},
	"search_files":   {"procurar", "pesquisar", "buscar", "grep", "find", "search", "localizar", "pattern", "regex"},
	"patch":          {"editar", "alterar", "modificar", "corrigir", "patch", "mudar", "substituir", "replace", "update"},
	"memory":         {"lembrar", "recordar", "memória", "salvar preferência", "remember", "save", "nota"},
	"delegate_task":  {"delegar", "subagente", "spawn", "paralelo", "delegate", "task", "dividir"},
	"web_search":     {"pesquisar web", "internet", "google", "search online", "web", "notícias", "atual"},
	"session_search": {"histórico", "conversa anterior", "session", "passado", "última vez", "conversa passada"},
	"clarify":        {"perguntar", "esclarecer", "dúvida", "confirmar", "qual", "prefere"},
	"vision_analyze": {"imagem", "foto", "screenshot", "print", "captura", "ver imagem", "analisar imagem"},
}

// TIER_0 tools are always injected.
var tier0 = map[string]bool{
	"memory":         true,
	"session_search": true,
	"clarify":        true,
}

// toolSchemas provides the OpenAI function schema for each tool.
var toolSchemas = map[string]inference.ToolSchema{
	"read_file": makeTool("read_file", "Read a file from the workspace. Returns file contents with line numbers.", map[string]any{
		"type": "object",
		"properties": map[string]any{
			"path":   map[string]any{"type": "string", "description": "Path to the file"},
			"offset": map[string]any{"type": "integer", "description": "Line number to start from"},
			"limit":  map[string]any{"type": "integer", "description": "Max lines to return"},
		},
		"required": []string{"path"},
	}),
	"write_file": makeTool("write_file", "Write content to a file, overwriting existing content.", map[string]any{
		"type": "object",
		"properties": map[string]any{
			"path":    map[string]any{"type": "string", "description": "Path to the file"},
			"content": map[string]any{"type": "string", "description": "Complete content to write"},
		},
		"required": []string{"path", "content"},
	}),
	"search_files": makeTool("search_files", "Search file contents or find files by name.", map[string]any{
		"type": "object",
		"properties": map[string]any{
			"pattern":   map[string]any{"type": "string", "description": "Regex or glob pattern"},
			"path":      map[string]any{"type": "string", "description": "Directory to search in"},
			"file_glob": map[string]any{"type": "string", "description": "Filter by file pattern"},
		},
		"required": []string{"pattern"},
	}),
	"patch": makeTool("patch", "Targeted find-and-replace edit in a file.", map[string]any{
		"type": "object",
		"properties": map[string]any{
			"path":       map[string]any{"type": "string", "description": "File to edit"},
			"old_string": map[string]any{"type": "string", "description": "Text to find"},
			"new_string": map[string]any{"type": "string", "description": "Replacement text"},
		},
		"required": []string{"path", "old_string", "new_string"},
	}),
	"terminal": makeTool("terminal", "Execute a shell command in the workspace.", map[string]any{
		"type": "object",
		"properties": map[string]any{
			"command": map[string]any{"type": "string", "description": "The shell command to execute"},
			"timeout": map[string]any{"type": "integer", "description": "Max seconds to wait"},
		},
		"required": []string{"command"},
	}),
	"memory": makeTool("memory", "Save durable information to persistent memory.", map[string]any{
		"type": "object",
		"properties": map[string]any{
			"action":  map[string]any{"type": "string", "description": "add, replace, or remove"},
			"content": map[string]any{"type": "string", "description": "Content to save"},
		},
		"required": []string{"action", "content"},
	}),
	"session_search": makeTool("session_search", "Search past conversation history for relevant information.", map[string]any{
		"type": "object",
		"properties": map[string]any{
			"query": map[string]any{"type": "string", "description": "Search query"},
			"limit": map[string]any{"type": "integer", "description": "Max results (default 10)"},
		},
		"required": []string{"query"},
	}),
	"manage_work_item": makeTool("manage_work_item", "Manage local work queue tasks. Action: create, list, update, delete.", map[string]any{
		"type": "object",
		"properties": map[string]any{
			"action":   map[string]any{"type": "string", "description": "create, list, update, or delete"},
			"title":    map[string]any{"type": "string", "description": "Task title (for create) or new status (for update)"},
			"priority": map[string]any{"type": "string", "description": "low, normal, high, urgent"},
			"context":  map[string]any{"type": "string", "description": "Files, history refs, skills for this task"},
			"id":       map[string]any{"type": "string", "description": "Work item ID (for update/delete)"},
		},
		"required": []string{"action"},
	}),
}

func makeTool(name, desc string, params map[string]any) inference.ToolSchema {
	var ts inference.ToolSchema
	ts.Type = "function"
	ts.Function.Name = name
	ts.Function.Description = desc
	ts.Function.Parameters = params
	return ts
}

// BuildMessages assembles the final message array for the LLM.
// L0–L7 order per ContextEngine plan, adapted for local SOLO mode.
func (c *ContextLite) BuildMessages(userText string) []inference.Message {
	// L0: DLP scan on user input
	if c.DLPEnabled {
		if blocked, reason := scanForSecrets(userText); blocked {
			return []inference.Message{{
				Role:    "system",
				Content: "[SECURITY BLOCK]\nYour message was blocked by local DLP: " + reason + "\nRemove secrets/PII and try again.",
			}}
		}
	}

	// Check cache for system layers
	ck := fmt.Sprintf("%s|%s|%d|%v", c.AgentPrompt, c.Workspace, len(c.SkillPrompts), c.Policy != nil)
	if c.cacheKey != ck || c.cachedSystem == nil {
		c.cachedSystem = c.buildSystemMessages()
		c.cacheKey = ck
	}

	var msgs []inference.Message
	msgs = append(msgs, c.cachedSystem...)

	// L5: Session search — inject relevant past context
	sessionCtx := c.buildSessionContext(userText)
	if sessionCtx != "" {
		msgs = append(msgs, inference.Message{Role: "system", Content: sessionCtx})
	}

	// L6: History with progressive compaction
	compactedHistory := c.compactHistory(userText)
	msgs = append(msgs, compactedHistory...)

	// User text
	msgs = append(msgs, inference.Message{Role: "user", Content: userText})

	return msgs
}

func (c *ContextLite) buildSystemMessages() []inference.Message {
	var msgs []inference.Message

	// L1: System identity (minimal)
	msgs = append(msgs, inference.Message{
		Role:    "system",
		Content: "[ENV] CentralChat SOLO — local agent runtime. Workspace: " + c.Workspace,
	})

	// L2: Workspace context
	wsBlock := c.buildWorkspaceBlock()
	if wsBlock != "" {
		msgs = append(msgs, inference.Message{Role: "system", Content: wsBlock})
	}

	// L3: Agent prompt
	if c.AgentPrompt != "" {
		msgs = append(msgs, inference.Message{Role: "system", Content: c.AgentPrompt})
	}

	// L3: Skills
	for _, skill := range c.SkillPrompts {
		if skill != "" {
			msgs = append(msgs, inference.Message{Role: "system", Content: skill})
		}
	}

	// L4: Governance — policy summary and tool restrictions
	if c.Policy != nil {
		policyBlock := c.buildPolicyBlock()
		if policyBlock != "" {
			msgs = append(msgs, inference.Message{Role: "system", Content: policyBlock})
		}
		// Filter AvailableTools based on policy
		c.AvailableTools = c.filterToolsByPolicy(c.AvailableTools)
	}

	return msgs
}

// ── L0: DLP (Data Loss Prevention) ────────────────────────────

// Secrets patterns — never send these to an LLM.
var secretPatterns = []struct {
	name    string
	pattern *regexp.Regexp
}{
	{name: "OpenAI key", pattern: regexp.MustCompile(`sk-[A-Za-z0-9]{32,}`)},
	{name: "GitHub token", pattern: regexp.MustCompile(`gh[pousr]_[A-Za-z0-9]{36,}`)},
	{name: "AWS key", pattern: regexp.MustCompile(`AKIA[0-9A-Z]{16}`)},
	{name: "Stripe key", pattern: regexp.MustCompile(`(?:sk|pk)_(?:live|test)_[0-9a-zA-Z]{24,}`)},
	{name: "JWT token", pattern: regexp.MustCompile(`eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}`)},
	{name: "private key header", pattern: regexp.MustCompile(`-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----`)},
	{name: "Generic API key", pattern: regexp.MustCompile(`[a-zA-Z0-9_-]{32,60}`)},
	{name: "email", pattern: regexp.MustCompile(`[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`)},
}

// scanForSecrets checks text for known secret patterns.
// Returns true and a reason if a secret is detected.
func scanForSecrets(text string) (bool, string) {
	for _, sp := range secretPatterns {
		if match := sp.pattern.FindString(text); match != "" {
			if sp.name == "Generic API key" {
				// Generic pattern is very broad — only flag if it looks like a token
				// (mixed case + digits, at least 32 chars)
				if len(match) < 40 {
					continue
				}
				upper, lower, digit := 0, 0, 0
				for _, c := range match {
					if c >= 'A' && c <= 'Z' { upper++ }
					if c >= 'a' && c <= 'z' { lower++ }
					if c >= '0' && c <= '9' { digit++ }
				}
				if upper == 0 || lower == 0 || digit == 0 {
					continue
				}
			}
			// Redact the match for the error message
			redacted := match[:len(match)]
			return true, fmt.Sprintf("detected %s (%s)", sp.name, redacted)
		}
	}
	return false, ""
}

// ── L4: Governance / Policy ───────────────────────────────────

func (c *ContextLite) buildPolicyBlock() string {
	if c.Policy == nil {
		return ""
	}
	var parts []string
	parts = append(parts, "[GOVERNANCE — Local Policy]")

	if len(c.Policy.DenyPaths) > 0 {
		parts = append(parts, "Blocked paths: "+strings.Join(c.Policy.DenyPaths, ", "))
	}
	if len(c.Policy.DenyCommands) > 0 {
		parts = append(parts, "Blocked commands: "+strings.Join(c.Policy.DenyCommands, ", "))
	}
	if len(c.Policy.RequireConfirmationFor) > 0 {
		parts = append(parts, "Require confirmation for: "+strings.Join(c.Policy.RequireConfirmationFor, ", "))
	}
	if c.Policy.MaxFileSizeBytes > 0 {
		parts = append(parts, fmt.Sprintf("Max file size: %d bytes", c.Policy.MaxFileSizeBytes))
	}
	if c.Policy.MaxShellTimeoutSec > 0 {
		parts = append(parts, fmt.Sprintf("Max shell timeout: %ds", c.Policy.MaxShellTimeoutSec))
	}

	return strings.Join(parts, "\n")
}

// filterToolsByPolicy removes tools denied by the policy.
func (c *ContextLite) filterToolsByPolicy(tools []string) []string {
	if c.Policy == nil {
		return tools
	}
	var filtered []string
	for _, t := range tools {
		blocked := false
		for _, blockedTool := range c.Policy.RequireConfirmationFor {
			if t == blockedTool {
				blocked = true
				break
			}
		}
		if !blocked {
			filtered = append(filtered, t)
		}
	}
	return filtered
}

// ── L5: Session Search ────────────────────────────────────────

// buildSessionContext searches past conversations for relevant context.
func (c *ContextLite) buildSessionContext(userText string) string {
	// Extract meaningful keywords from user text
	query := extractKeywords(userText)
	if query == "" {
		return ""
	}

	entries, err := solo.SearchSessions(query, 3)
	if err != nil || len(entries) == 0 {
		return ""
	}

	var parts []string
	parts = append(parts, "[CONTEXT_RETRIEVED — session history]")
	for _, e := range entries {
		content := strings.TrimSpace(e.Content)
		if len(content) > 300 {
			content = content[:297] + "..."
		}
		if content != "" {
			parts = append(parts, fmt.Sprintf("[%s]: %s", e.Role, content))
		}
	}
	return strings.Join(parts, "\n")
}

// extractKeywords returns simple keywords from user text for FTS search.
func extractKeywords(text string) string {
	// Remove common stop words and punctuation, keep meaningful terms
	text = strings.ToLower(text)
	stopWords := []string{"the", "a", "an", "is", "are", "was", "were", "o", "a", "os", "as", "de", "da", "do", "em", "no", "na", "um", "uma", "para", "com", "que", "se", "não", "sim"}
	for _, sw := range stopWords {
		text = strings.ReplaceAll(text, " "+sw+" ", " ")
	}
	// Keep only alphanumeric and spaces
	var clean strings.Builder
	for _, c := range text {
		if (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == ' ' || c == '-' || c == '_' {
			clean.WriteRune(c)
		}
	}
	query := strings.TrimSpace(clean.String())
	if len(query) < 5 {
		return ""
	}
	// Take up to 3 words
	words := strings.Fields(query)
	if len(words) > 3 {
		words = words[:3]
	}
	return strings.Join(words, " ")
}

// compactHistory applies progressive summarization based on estimated token count.
// Strategy:
//   ≤ 8000 tokens → keep verbatim
//   8000-16000 tokens → summarize oldest, keep ~4000 tokens recent verbatim
//   > 16000 tokens → summarize all but last ~2000 tokens
func (c *ContextLite) compactHistory(userText string) []inference.Message {
	const (
		verbatimBudget  = 8000 // keep this many tokens verbatim
		compactThreshold = 8000 // start compacting above this
		keepRecent       = 2000 // keep this many tokens recent when heavily compacted
	)

	totalTokens := estimateTokens(c.History)
	if totalTokens <= compactThreshold {
		return c.History
	}

	var result []inference.Message

	if totalTokens <= 16000 {
		// Moderate: summarize oldest messages to fit budget
		split := findSplitPoint(c.History, totalTokens-verbatimBudget)
		if split > 0 {
			summary := c.summarizeMessages(c.History[:split])
			if summary != "" {
				result = append(result, inference.Message{
					Role:    "system",
					Content: "[SUMMARY]\n" + summary,
				})
			}
		}
		result = append(result, c.History[split:]...)
	} else {
		// Heavy: summarize everything except recent
		split := findSplitPointReverse(c.History, keepRecent)
		summary := c.summarizeMessages(c.History[:split])
		if summary != "" {
			result = append(result, inference.Message{
				Role:    "system",
				Content: "[SUMMARY of earlier conversation]\n" + summary,
			})
		}
		result = append(result, c.History[split:]...)
	}

	return result
}

// estimateTokens returns approximate token count (chars/4 for text, chars/2.5 for code).
func estimateTokens(msgs []inference.Message) int {
	total := 0
	for _, m := range msgs {
		chars := len(m.Content)
		// Heuristic: code-heavy messages have more punctuation/symbols
		if looksLikeCode(m.Content) {
			total += chars * 2 / 5 // ≈ chars/2.5
		} else {
			total += chars / 4
		}
	}
	return total
}

func looksLikeCode(s string) bool {
	// Simple heuristic: high density of { } ( ) ; = or indentation
	if len(s) == 0 {
		return false
	}
	symbols := 0
	for _, c := range s {
		switch c {
		case '{', '}', '(', ')', ';', '=', '<', '>', '[', ']', ':', '#':
			symbols++
		}
	}
	// If >15% symbols, probably code
	return float64(symbols)/float64(len(s)) > 0.15
}

// findSplitPoint returns the index where cumulative tokens from the start exceeds target.
func findSplitPoint(msgs []inference.Message, targetTokens int) int {
	cumulative := 0
	for i := range msgs {
		cumulative += len(msgs[i].Content) / 4
		if cumulative > targetTokens {
			return i
		}
	}
	return len(msgs)
}

// findSplitPointReverse returns the index where cumulative tokens from the end exceeds target.
func findSplitPointReverse(msgs []inference.Message, targetTokens int) int {
	cumulative := 0
	for i := len(msgs) - 1; i >= 0; i-- {
		cumulative += len(msgs[i].Content) / 4
		if cumulative > targetTokens {
			return i + 1
		}
	}
	return 0
}

// summarizeMessages creates a brief summary of messages.
// Uses extractive approach: sample user messages and key decisions.
func (c *ContextLite) summarizeMessages(msgs []inference.Message) string {
	if len(msgs) == 0 {
		return ""
	}
	var parts []string
	parts = append(parts, fmt.Sprintf("(Condensed from %d earlier messages)", len(msgs)))

	// Extract user queries (first sentence of each)
	userCount := 0
	for _, m := range msgs {
		if m.Role == "user" && userCount < 10 {
			text := firstSentence(m.Content)
			if len(text) > 10 {
				parts = append(parts, "User: "+text)
				userCount++
			}
		}
	}

	return strings.Join(parts, "\n")
}

func firstSentence(s string) string {
	// Take everything up to first ., !, ?, or newline
	for i, c := range s {
		if c == '.' || c == '!' || c == '?' || c == '\n' {
			return strings.TrimSpace(s[:i+1])
		}
	}
	if len(s) > 200 {
		return s[:197] + "..."
	}
	return s
}

// SelectTools picks tools based on keyword scoring of user text.
func (c *ContextLite) SelectTools(userText string, history []inference.Message) []inference.ToolSchema {
	// Build context for keyword matching
	var ctxBuilder strings.Builder
	recent := history
	if len(recent) > 3 {
		recent = recent[len(recent)-3:]
	}
	for _, m := range recent {
		ctxBuilder.WriteString(m.Content)
		ctxBuilder.WriteString(" ")
	}
	full := strings.ToLower(ctxBuilder.String() + " " + userText)

	// Score tools by keyword matches
	type toolScore struct {
		name  string
		score float64
	}
	var results []toolScore
	for _, name := range c.AvailableTools {
		triggers := toolTriggers[name]
		s := 0.0
		for _, t := range triggers {
			if strings.Contains(full, strings.ToLower(t)) {
				s += 0.3
			}
		}
		if s > 0 {
			results = append(results, toolScore{name: name, score: min(s, 1.0)})
		}
	}

	// Sort by score descending
	for i := 0; i < len(results); i++ {
		for j := i + 1; j < len(results); j++ {
			if results[j].score > results[i].score ||
				(results[j].score == results[i].score && results[j].name < results[i].name) {
				results[i], results[j] = results[j], results[i]
			}
		}
	}

	// Always include TIER_0
	selected := make(map[string]bool)
	for name := range tier0 {
		selected[name] = true
	}

	// Add top-5 keyword matches
	for i := 0; i < len(results) && i < 5; i++ {
		selected[results[i].name] = true
	}

	// Build tool schemas
	var tools []inference.ToolSchema
	for name := range selected {
		if ts, ok := toolSchemas[name]; ok {
			tools = append(tools, ts)
		}
	}
	return tools
}

// buildWorkspaceBlock creates L2 git metadata block.
func (c *ContextLite) buildWorkspaceBlock() string {
	if c.Workspace == "" {
		return ""
	}

	var parts []string
	parts = append(parts, "[WORKSPACE L2]")

	// Git branch
	branch := gitBranch(c.Workspace)
	if branch != "" {
		dirty := ""
		if gitDirty(c.Workspace) {
			dirty = " (dirty)"
		}
		parts = append(parts, "Branch: "+branch+dirty)
	}

	// Path
	parts = append(parts, "Path: "+c.Workspace)

	return strings.Join(parts, "\n")
}

func gitBranch(dir string) string {
	cmd := exec.Command("git", "-C", dir, "rev-parse", "--abbrev-ref", "HEAD")
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func gitDirty(dir string) bool {
	cmd := exec.Command("git", "-C", dir, "diff", "--stat")
	out, _ := cmd.Output()
	return len(out) > 0
}

// LoadAgentPrompt reads an agent prompt from ~/.config/central/agents/<name>.txt
func LoadAgentPrompt(agentName string) string {
	if agentName == "" {
		agentName = "default"
	}
	configDir, err := os.UserConfigDir()
	if err != nil {
		return ""
	}
	path := filepath.Join(configDir, "central", "agents", agentName+".txt")
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

// LoadSkillPrompts reads skill prompts from ~/.config/central/skills/*.txt
func LoadSkillPrompts() []string {
	configDir, err := os.UserConfigDir()
	if err != nil {
		return nil
	}
	skillsDir := filepath.Join(configDir, "central", "skills")
	entries, err := os.ReadDir(skillsDir)
	if err != nil {
		return nil
	}
	var prompts []string
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".txt") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(skillsDir, entry.Name()))
		if err != nil {
			continue
		}
		content := strings.TrimSpace(string(data))
		if content != "" {
			name := strings.TrimSuffix(entry.Name(), ".txt")
			prompts = append(prompts, "[SKILL: "+name+"]\n"+content)
		}
	}
	return prompts
}
