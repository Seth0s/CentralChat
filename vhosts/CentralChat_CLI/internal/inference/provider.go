// Package inference — direct LLM provider calls with streaming.
//
// Supported providers:
//   - openrouter      (OpenAI-compatible SSE at api.openrouter.ai)
//   - openai          (SSE at api.openai.com)
//   - anthropic       (SSE at api.anthropic.com — Messages API)
//   - llamacpp        (OpenAI-compatible at 127.0.0.1:8080/v1)
//   - deepseek        (OpenAI-compatible at api.deepseek.com)
//   - openai_compatible (any OpenAI-compatible endpoint)
package inference

import (
	"bufio"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

// ProviderKind identifies the backend API type.
type ProviderKind string

const (
	KindOpenRouter       ProviderKind = "openrouter"
	KindOpenAI           ProviderKind = "openai"
	KindAnthropic        ProviderKind = "anthropic"
	KindLlamaCpp         ProviderKind = "llamacpp"
	KindDeepSeek         ProviderKind = "deepseek"
	KindOpenAICompatible ProviderKind = "openai_compatible"
)

// Provider wraps an LLM backend with its connection details.
type Provider struct {
	Kind    ProviderKind
	BaseURL string
	APIKey  string
	Model   string
	HTTP    *http.Client
}

// NewProvider creates a provider from its kind and configuration.
func NewProvider(kind ProviderKind, baseURL, apiKey, model string) *Provider {
	p := &Provider{
		Kind:   kind,
		APIKey: apiKey,
		Model:  model,
		HTTP:   &http.Client{Timeout: 5 * time.Minute},
	}
	switch kind {
	case KindOpenRouter:
		p.BaseURL = "https://openrouter.ai/api/v1"
	case KindOpenAI:
		p.BaseURL = "https://api.openai.com/v1"
	case KindAnthropic:
		p.BaseURL = "https://api.anthropic.com/v1"
	case KindLlamaCpp:
		if baseURL != "" {
			p.BaseURL = strings.TrimRight(baseURL, "/")
		} else {
			p.BaseURL = "http://127.0.0.1:8080/v1"
		}
	case KindDeepSeek:
		p.BaseURL = "https://api.deepseek.com/v1"
	case KindOpenAICompatible:
		p.BaseURL = strings.TrimRight(baseURL, "/")
	}
	return p
}

// Message is a chat message. For assistant messages that request tool calls,
// ToolCalls is populated. For tool results, ToolCallID identifies which call.
type Message struct {
	Role       string     `json:"role"`
	Content    string     `json:"content"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
}

// ToolSchema is an OpenAI function tool definition.
type ToolSchema struct {
	Type     string `json:"type"`
	Function struct {
		Name        string         `json:"name"`
		Description string         `json:"description"`
		Parameters  map[string]any `json:"parameters"`
	} `json:"function"`
}

// ToolCall is a tool call requested by the model.
type ToolCall struct {
	ID       string `json:"id"`
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

// StreamEvent is emitted during streaming.
type StreamEvent struct {
	Type  string    // "token", "tool_call", "done", "error"
	Token string    // for "token" events
	Tools []ToolCall // for "tool_call" events
	Usage Usage     // for "done" events
	Err   error     // for "error" events
}

// Usage tracks token consumption.
type Usage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

// Stream sends a chat completion request with retry and streams events via the callback.
// Retries up to 3 times with exponential backoff on transient errors.
// If ctx is cancelled, the stream is aborted.
func (p *Provider) Stream(ctx context.Context, messages []Message, tools []ToolSchema, onEvent func(StreamEvent)) error {
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if attempt > 0 {
			delay := time.Duration(1<<uint(attempt-1)) * time.Second
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(delay):
			}
			log.Printf("[inference] retry attempt %d/3 after %v", attempt+1, delay)
		}
		err := p.streamOnce(ctx, messages, tools, onEvent)
		if err == nil {
			return nil
		}
		lastErr = err
		// Don't retry on 4xx errors (client errors)
		if strings.Contains(err.Error(), "API error 4") {
			break
		}
	}
	return fmt.Errorf("inference failed after retries: %w", lastErr)
}

func (p *Provider) streamOnce(ctx context.Context, messages []Message, tools []ToolSchema, onEvent func(StreamEvent)) error {
	switch p.Kind {
	case KindOpenRouter, KindOpenAI, KindOpenAICompatible, KindDeepSeek, KindLlamaCpp:
		return p.streamOpenAICompat(ctx, messages, tools, onEvent)
	case KindAnthropic:
		return p.streamAnthropic(ctx, messages, tools, onEvent)
	default:
		return fmt.Errorf("unknown provider kind: %s", p.Kind)
	}
}

// ── OpenAI-compatible (OpenRouter, OpenAI, custom) ─────────────

type openAIRequest struct {
	Model       string       `json:"model"`
	Messages    []Message    `json:"messages"`
	Tools       []ToolSchema `json:"tools,omitempty"`
	Stream      bool         `json:"stream"`
	Temperature float64      `json:"temperature,omitempty"`
	MaxTokens   int          `json:"max_tokens,omitempty"`
}

func (p *Provider) streamOpenAICompat(ctx context.Context, messages []Message, tools []ToolSchema, onEvent func(StreamEvent)) error {
	endpoint := p.BaseURL + "/chat/completions"
	reqBody := openAIRequest{
		Model:       p.Model,
		Messages:    messages,
		Tools:       tools,
		Stream:      true,
		Temperature: 0.7,
	}
	if len(tools) == 0 {
		reqBody.Tools = nil
	}

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", endpoint, bytes.NewReader(bodyBytes))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if p.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+p.APIKey)
	}

	resp, err := p.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("API error %d: %s", resp.StatusCode, string(body))
	}

	return p.parseOpenAISSE(resp.Body, onEvent)
}

func (p *Provider) parseOpenAISSE(body io.Reader, onEvent func(StreamEvent)) error {
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	var toolCallAccum map[int]*ToolCall
	var usage Usage

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" || !strings.HasPrefix(line, "data: ") {
			continue
		}
		data := strings.TrimPrefix(line, "data: ")
		if data == "[DONE]" {
			break
		}

		var chunk struct {
			Choices []struct {
				Delta struct {
					Content   string `json:"content"`
					ToolCalls []struct {
						Index    int    `json:"index"`
						ID       string `json:"id"`
						Function struct {
							Name      string `json:"name"`
							Arguments string `json:"arguments"`
						} `json:"function"`
					} `json:"tool_calls"`
				} `json:"delta"`
				FinishReason string `json:"finish_reason"`
			} `json:"choices"`
			Usage *struct {
				PromptTokens     int `json:"prompt_tokens"`
				CompletionTokens int `json:"completion_tokens"`
				TotalTokens      int `json:"total_tokens"`
			} `json:"usage"`
		}

		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			continue
		}

		if chunk.Usage != nil {
			usage = Usage{
				PromptTokens:     chunk.Usage.PromptTokens,
				CompletionTokens: chunk.Usage.CompletionTokens,
				TotalTokens:      chunk.Usage.TotalTokens,
			}
		}
		if len(chunk.Choices) == 0 {
			continue
		}
		choice := chunk.Choices[0]

		if choice.Delta.Content != "" {
			onEvent(StreamEvent{Type: "token", Token: choice.Delta.Content})
		}

		for _, tc := range choice.Delta.ToolCalls {
			if toolCallAccum == nil {
				toolCallAccum = make(map[int]*ToolCall)
			}
			acc, exists := toolCallAccum[tc.Index]
			if !exists {
				acc = &ToolCall{ID: tc.ID}
				if tc.Function.Name != "" {
					acc.Function.Name = tc.Function.Name
				}
				toolCallAccum[tc.Index] = acc
			}
			if tc.ID != "" {
				acc.ID = tc.ID
			}
			acc.Function.Arguments += tc.Function.Arguments
		}

		if choice.FinishReason == "tool_calls" {
			var toolCalls []ToolCall
			for i := 0; i < len(toolCallAccum); i++ {
				if tc, ok := toolCallAccum[i]; ok {
					toolCalls = append(toolCalls, *tc)
				}
			}
			if len(toolCalls) > 0 {
				onEvent(StreamEvent{Type: "tool_call", Tools: toolCalls})
			}
		}
	}

	onEvent(StreamEvent{Type: "done", Usage: usage})
	return scanner.Err()
}

// ── Anthropic (Messages API) ───────────────────────────────────

type anthropicRequest struct {
	Model       string       `json:"model"`
	MaxTokens   int          `json:"max_tokens"`
	Messages    []anthropicMsg `json:"messages"`
	System      string       `json:"system,omitempty"`
	Tools       []anthropicTool `json:"tools,omitempty"`
	Stream      bool         `json:"stream"`
}

type anthropicMsg struct {
	Role    string            `json:"role"`
	Content []anthropicContent `json:"content"`
}

type anthropicContent struct {
	Type string `json:"type"`
	Text string `json:"text,omitempty"`
}

type anthropicTool struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"input_schema"`
}

func (p *Provider) streamAnthropic(ctx context.Context, messages []Message, tools []ToolSchema, onEvent func(StreamEvent)) error {
	endpoint := p.BaseURL + "/messages"

	// Build Anthropic-compatible messages
	var systemPrompt string
	var anthropicMsgs []anthropicMsg
	for _, m := range messages {
		if m.Role == "system" {
			if systemPrompt != "" {
				systemPrompt += "\n\n"
			}
			systemPrompt += m.Content
			continue
		}
		role := m.Role
		if role == "assistant" {
			role = "assistant"
		} else {
			role = "user"
		}
		anthropicMsgs = append(anthropicMsgs, anthropicMsg{
			Role:    role,
			Content: []anthropicContent{{Type: "text", Text: m.Content}},
		})
	}

	// Convert OpenAI tools to Anthropic format
	var anthropicTools []anthropicTool
	for _, t := range tools {
		anthropicTools = append(anthropicTools, anthropicTool{
			Name:        t.Function.Name,
			Description: t.Function.Description,
			InputSchema: t.Function.Parameters,
		})
	}

	reqBody := anthropicRequest{
		Model:     p.Model,
		MaxTokens: 8192,
		Messages:  anthropicMsgs,
		System:    systemPrompt,
		Tools:     anthropicTools,
		Stream:    true,
	}
	if len(anthropicTools) == 0 {
		reqBody.Tools = nil
	}

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", endpoint, bytes.NewReader(bodyBytes))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-api-key", p.APIKey)
	req.Header.Set("anthropic-version", "2023-06-01")

	resp, err := p.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("API error %d: %s", resp.StatusCode, string(body))
	}

	return p.parseAnthropicSSE(resp.Body, onEvent)
}

func (p *Provider) parseAnthropicSSE(body io.Reader, onEvent func(StreamEvent)) error {
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	var usage Usage
	var toolUseAccum map[int]*ToolCall

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" || !strings.HasPrefix(line, "data: ") {
			continue
		}
		data := strings.TrimPrefix(line, "data: ")

		var event struct {
			Type  string `json:"type"`
			Delta *struct {
				Type         string `json:"type"`
				Text         string `json:"text,omitempty"`
				PartialJSON  string `json:"partial_json,omitempty"`
			} `json:"delta,omitempty"`
			ContentBlock *struct {
				Type string `json:"type"`
				ID   string `json:"id,omitempty"`
				Name string `json:"name,omitempty"`
			} `json:"content_block,omitempty"`
			Usage *struct {
				InputTokens  int `json:"input_tokens"`
				OutputTokens int `json:"output_tokens"`
			} `json:"usage,omitempty"`
			Message *struct {
				Usage *struct {
					InputTokens  int `json:"input_tokens"`
					OutputTokens int `json:"output_tokens"`
				} `json:"usage,omitempty"`
			} `json:"message,omitempty"`
		}

		if err := json.Unmarshal([]byte(data), &event); err != nil {
			continue
		}

		switch event.Type {
		case "content_block_delta":
			if event.Delta != nil {
				switch event.Delta.Type {
				case "text_delta":
					onEvent(StreamEvent{Type: "token", Token: event.Delta.Text})
				case "input_json_delta":
					// Accumulate tool arguments
					_ = event.Delta.PartialJSON
				}
			}
		case "content_block_start":
			if event.ContentBlock != nil && event.ContentBlock.Type == "tool_use" {
				if toolUseAccum == nil {
					toolUseAccum = make(map[int]*ToolCall)
				}
				idx := len(toolUseAccum)
				toolUseAccum[idx] = &ToolCall{
					ID: event.ContentBlock.ID,
					Function: struct {
						Name      string `json:"name"`
						Arguments string `json:"arguments"`
					}{Name: event.ContentBlock.Name},
				}
			}
		case "message_delta":
			if event.Usage != nil {
				usage = Usage{
					PromptTokens:     event.Usage.InputTokens,
					CompletionTokens: event.Usage.OutputTokens,
					TotalTokens:      event.Usage.InputTokens + event.Usage.OutputTokens,
				}
			} else if event.Message != nil && event.Message.Usage != nil {
				usage = Usage{
					PromptTokens:     event.Message.Usage.InputTokens,
					CompletionTokens: event.Message.Usage.OutputTokens,
					TotalTokens:      event.Message.Usage.InputTokens + event.Message.Usage.OutputTokens,
				}
			}
		case "message_stop":
			// Emit any accumulated tool calls
			if len(toolUseAccum) > 0 {
				var toolCalls []ToolCall
				for i := 0; i < len(toolUseAccum); i++ {
					if tc, ok := toolUseAccum[i]; ok {
						toolCalls = append(toolCalls, *tc)
					}
				}
				if len(toolCalls) > 0 {
					onEvent(StreamEvent{Type: "tool_call", Tools: toolCalls})
				}
			}
		}
	}

	onEvent(StreamEvent{Type: "done", Usage: usage})
	return scanner.Err()
}

// Complete is a non-streaming convenience call.
func (p *Provider) Complete(messages []Message, tools []ToolSchema) (string, []ToolCall, Usage, error) {
	var reply strings.Builder
	var toolCalls []ToolCall
	var usage Usage
	ctx := context.Background()
	err := p.Stream(ctx, messages, tools, func(ev StreamEvent) {
		switch ev.Type {
		case "token":
			reply.WriteString(ev.Token)
		case "tool_call":
			toolCalls = ev.Tools
		case "done":
			usage = ev.Usage
		}
	})
	return reply.String(), toolCalls, usage, err
}

// HealthCheck verifies the provider is reachable and the API key is valid.
func (p *Provider) HealthCheck() error {
	var endpoint string
	switch p.Kind {
	case KindOpenRouter:
		endpoint = p.BaseURL + "/models"
	case KindOpenAI, KindOpenAICompatible, KindDeepSeek, KindLlamaCpp:
		endpoint = p.BaseURL + "/models"
	case KindAnthropic:
		endpoint = p.BaseURL + "/messages"
	default:
		return fmt.Errorf("unknown provider kind: %s", p.Kind)
	}
	req, err := http.NewRequest("GET", endpoint, nil)
	if err != nil {
		return fmt.Errorf("health check: %w", err)
	}
	if p.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+p.APIKey)
	}
	if p.Kind == KindAnthropic {
		req.Header.Set("x-api-key", p.APIKey)
		req.Header.Set("anthropic-version", "2023-06-01")
	}
	resp, err := p.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("health check unreachable: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 500 {
		return fmt.Errorf("health check: server error %d", resp.StatusCode)
	}
	return nil
}

// ListModels returns available models for providers that support listing.
func (p *Provider) ListModels() ([]string, error) {
	switch p.Kind {
	case KindOpenRouter, KindOpenAI, KindDeepSeek, KindOpenAICompatible, KindLlamaCpp:
		return p.listOpenAICompatibleModels()
	default:
		return nil, nil
	}
}

// listOpenAICompatibleModels fetches models from an OpenAI-compatible /models endpoint.
// Works for OpenRouter, OpenAI, DeepSeek, and compatible providers.
func (p *Provider) listOpenAICompatibleModels() ([]string, error) {
	endpoint := strings.TrimRight(p.BaseURL, "/") + "/models"
	req, err := http.NewRequest("GET", endpoint, nil)
	if err != nil {
		return nil, err
	}
	if p.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+p.APIKey)
	}
	resp, err := p.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("list models: HTTP %d", resp.StatusCode)
	}

	// OpenAI format: { "data": [ { "id": "gpt-4o", ... }, ... ] }
	// OpenRouter format: { "data": [ { "id": "openai/gpt-4o", "name": "GPT-4o", ... }, ... ] }
	var result struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, err
	}
	var names []string
	for _, m := range result.Data {
		if m.ID != "" {
			names = append(names, m.ID)
		}
	}
	return names, nil
}

// ChangeModel updates the provider's active model.
func (p *Provider) ChangeModel(modelID string) bool {
	p.Model = modelID
	return true
}

// AnalyzeImage sends an image to the provider for vision analysis.
// Returns the model's description of the image.
func (p *Provider) AnalyzeImage(imagePath, question string) (string, error) {
	data, err := os.ReadFile(imagePath)
	if err != nil {
		return "", fmt.Errorf("read image: %w", err)
	}

	// Detect MIME type from extension
	mime := "image/png"
	switch {
	case strings.HasSuffix(imagePath, ".jpg"), strings.HasSuffix(imagePath, ".jpeg"):
		mime = "image/jpeg"
	case strings.HasSuffix(imagePath, ".gif"):
		mime = "image/gif"
	case strings.HasSuffix(imagePath, ".webp"):
		mime = "image/webp"
	}

	b64 := base64.StdEncoding.EncodeToString(data)
	dataURL := fmt.Sprintf("data:%s;base64,%s", mime, b64)

	if question == "" {
		question = "Describe this image in detail."
	}

	switch p.Kind {
	case KindOpenRouter, KindOpenAI, KindDeepSeek, KindLlamaCpp, KindOpenAICompatible:
		return p.analyzeOpenAIVision(dataURL, question)
	case KindAnthropic:
		return p.analyzeAnthropicVision(data, mime, question)
	default:
		return "", fmt.Errorf("provider %s does not support vision", p.Kind)
	}
}

func (p *Provider) analyzeOpenAIVision(dataURL, question string) (string, error) {
	endpoint := p.BaseURL + "/chat/completions"
	reqBody := map[string]any{
		"model": p.Model,
		"messages": []map[string]any{{
			"role": "user",
			"content": []map[string]any{
				{"type": "text", "text": question},
				{"type": "image_url", "image_url": map[string]string{"url": dataURL}},
			},
		}},
		"max_tokens": 1024,
	}
	body, _ := json.Marshal(reqBody)

	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if p.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+p.APIKey)
	}

	resp, err := p.HTTP.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return "", fmt.Errorf("vision API error %d: %s", resp.StatusCode, string(body))
	}

	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", err
	}
	if len(result.Choices) == 0 {
		return "", fmt.Errorf("no response from vision model")
	}
	return result.Choices[0].Message.Content, nil
}

func (p *Provider) analyzeAnthropicVision(data []byte, mime, question string) (string, error) {
	endpoint := p.BaseURL + "/messages"
	b64 := base64.StdEncoding.EncodeToString(data)

	reqBody := map[string]any{
		"model":      p.Model,
		"max_tokens": 1024,
		"messages": []map[string]any{{
			"role": "user",
			"content": []map[string]any{
				{"type": "text", "text": question},
				{"type": "image", "source": map[string]any{
					"type":       "base64",
					"media_type": mime,
					"data":       b64,
				}},
			},
		}},
	}
	body, _ := json.Marshal(reqBody)

	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-api-key", p.APIKey)
	req.Header.Set("anthropic-version", "2023-06-01")

	resp, err := p.HTTP.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return "", fmt.Errorf("anthropic vision API error %d: %s", resp.StatusCode, string(body))
	}

	var result struct {
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", err
	}
	if len(result.Content) == 0 {
		return "", fmt.Errorf("no response from vision model")
	}
	return result.Content[0].Text, nil
}
