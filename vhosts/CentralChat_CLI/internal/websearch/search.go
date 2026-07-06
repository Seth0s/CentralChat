// Package websearch provides web search capabilities for SOLO mode.
//
// Backends (tried in order):
//   1. Native browser-use (pip install browser-use)  — subprocess, fastest
//   2. Docker container (on-demand via docker run)    — isolated, no host deps
//   3. DuckDuckGo Instant Answer API                  — zero-deps, always available
//
// No persistent processes — native runs on-demand via python3,
// Docker container starts on first search and reuses while running.
package websearch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"strings"
	"time"
)

var httpClient = &http.Client{Timeout: 10 * time.Second}

// SearchResult represents one search result.
type SearchResult struct {
	Title   string `json:"title"`
	URL     string `json:"url"`
	Snippet string `json:"snippet"`
}

// Search performs a web search using the best available backend.
func Search(query string, limit int) ([]SearchResult, error) {
	if limit <= 0 {
		limit = 5
	}

	// 1. Native browser-use (fastest, if installed)
	if NativeAvailable() {
		if results, err := searchNative(query, limit); err == nil && len(results) > 0 {
			return results, nil
		}
	}

	// 2. Docker container (on-demand)
	if DockerAvailable() {
		if results, err := searchWithContainer(query, limit); err == nil && len(results) > 0 {
			return results, nil
		}
	}

	// 3. DuckDuckGo (always available)
	return searchDuckDuckGo(query, limit)
}

// ── Availability checks ────────────────────────────────────────

// NativeAvailable checks if browser-use is installed via pip.
func NativeAvailable() bool {
	return exec.Command("python3", "-c", "import browser_use").Run() == nil
}

// DockerAvailable checks if Docker is installed and runnable.
func DockerAvailable() bool {
	return exec.Command("docker", "version").Run() == nil
}

// ContainerAvailable checks if the browser-use container is reachable.
func ContainerAvailable() bool {
	req, _ := http.NewRequest("POST", "http://127.0.0.1:8081/health", nil)
	resp, err := httpClient.Do(req)
	if err != nil {
		return false
	}
	resp.Body.Close()
	return resp.StatusCode == 200
}

// ── Native browser-use (subprocess) ─────────────────────────────

func searchNative(query string, limit int) ([]SearchResult, error) {
	script := fmt.Sprintf(`import json, sys
try:
    from browser_use import Agent
    from langchain_openai import ChatOpenAI

    task = "Search for: %s. Return up to %d results as a JSON array with keys: title, url, snippet. Respond ONLY with the JSON array."
    llm = ChatOpenAI(model="gpt-4o-mini")
    agent = Agent(task=task, llm=llm)
    result = agent.run()
    text = str(result)

    # Find JSON array in output
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        parsed = json.loads(text[start:end])
        if isinstance(parsed, list):
            print(json.dumps(parsed))
            sys.exit(0)

    # Fallback: extract URLs
    results = []
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith(('http://', 'https://')):
            results.append({"title": "", "url": line, "snippet": ""})
    print(json.dumps(results))
except Exception as e:
    print(json.dumps({"error": str(e)}))
`, query, limit)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "python3", "-c", script)
	cmd.Env = os.Environ()
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("native browser-use: %w", err)
	}

	// Try to parse as results array
	var results []SearchResult
	if err := json.Unmarshal(output, &results); err == nil {
		if limit > 0 && len(results) > limit {
			results = results[:limit]
		}
		return results, nil
	}

	// Try as error object
	var errResp struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(output, &errResp) == nil && errResp.Error != "" {
		return nil, fmt.Errorf("native browser-use: %s", errResp.Error)
	}

	return nil, fmt.Errorf("native browser-use: unexpected output: %s", string(output))
}

// ── Docker container (on-demand) ────────────────────────────────

const containerImage = "centralchat/browser-use:latest"

func searchWithContainer(query string, limit int) ([]SearchResult, error) {
	if ContainerAvailable() {
		return searchContainer(query, limit)
	}

	// Cold start
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx,
		"docker", "run", "--rm",
		"-p", "127.0.0.1:8081:8081",
		"--name", "centralchat-browser-use",
		"-d", containerImage,
	)
	if out, err := cmd.CombinedOutput(); err != nil {
		return nil, fmt.Errorf("docker start: %w (output: %s)", err, string(out))
	}

	// Wait for ready
	for i := 0; i < 10; i++ {
		if ContainerAvailable() { break }
		time.Sleep(500 * time.Millisecond)
	}

	return searchContainer(query, limit)
}

func searchContainer(query string, limit int) ([]SearchResult, error) {
	reqBody := map[string]any{"query": query, "limit": limit}
	body, _ := json.Marshal(reqBody)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "POST", "http://127.0.0.1:8081/search", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("container: %w", err)
	}
	defer resp.Body.Close()

	var result struct {
		Results []SearchResult `json:"results"`
		Error   string         `json:"error"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("container response: %w", err)
	}
	if result.Error != "" {
		return nil, fmt.Errorf("container error: %s", result.Error)
	}
	if limit > 0 && len(result.Results) > limit {
		result.Results = result.Results[:limit]
	}
	return result.Results, nil
}

// ── DuckDuckGo fallback ─────────────────────────────────────────

func searchDuckDuckGo(query string, limit int) ([]SearchResult, error) {
	u := "https://api.duckduckgo.com/?q=" + url.QueryEscape(query) + "&format=json&no_html=1&skip_disambig=1"
	resp, err := httpClient.Get(u)
	if err != nil {
		return nil, fmt.Errorf("ddg: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("ddg: HTTP %d", resp.StatusCode)
	}

	var data ddgResponse
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil, fmt.Errorf("ddg decode: %w", err)
	}

	var results []SearchResult
	if data.AbstractText != "" {
		results = append(results, SearchResult{
			Title:   data.Heading,
			URL:     data.AbstractURL,
			Snippet: strings.TrimSpace(data.AbstractText),
		})
	}
	for _, t := range data.RelatedTopics {
		if t.Text != "" && t.FirstURL != "" {
			title, snippet := splitDDGText(t.Text)
			results = append(results, SearchResult{Title: title, URL: t.FirstURL, Snippet: snippet})
		}
	}
	for _, r := range data.Results {
		if r.Text != "" && r.FirstURL != "" {
			title, snippet := splitDDGText(r.Text)
			results = append(results, SearchResult{Title: title, URL: r.FirstURL, Snippet: snippet})
		}
	}
	if limit > 0 && len(results) > limit {
		results = results[:limit]
	}
	return results, nil
}

type ddgResponse struct {
	Abstract      string     `json:"Abstract"`
	AbstractText  string     `json:"AbstractText"`
	AbstractURL   string     `json:"AbstractURL"`
	Heading       string     `json:"Heading"`
	RelatedTopics []ddgTopic `json:"RelatedTopics"`
	Results       []ddgTopic `json:"Results"`
}

type ddgTopic struct {
	Text     string `json:"Text"`
	FirstURL string `json:"FirstURL"`
}

func splitDDGText(text string) (title, snippet string) {
	parts := strings.SplitN(text, " - ", 2)
	if len(parts) == 2 {
		return parts[0], parts[1]
	}
	return text, ""
}
