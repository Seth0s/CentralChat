package api

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

func New(baseURL, token string) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		Token:   token,
		HTTP:    &http.Client{Timeout: 120 * time.Second},
	}
}

func (c *Client) do(method, path string, body any, headers map[string]string) (*http.Response, error) {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.BaseURL+path, rdr)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	return c.HTTP.Do(req)
}

type LoginResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
}

func (c *Client) Health() error {
	resp, err := c.do(http.MethodGet, "/health", nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("health failed (%d)", resp.StatusCode)
	}
	return nil
}

func (c *Client) HealthReady() (string, error) {
	resp, err := c.do(http.MethodGet, "/health/ready", nil, nil)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("ready failed (%d)", resp.StatusCode)
	}
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", err
	}
	st, _ := out["status"].(string)
	if st == "" {
		st = "ok"
	}
	return st, nil
}

func (c *Client) PublicConfig() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/auth/public-config", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("public-config failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) Refresh(refreshToken string) (*LoginResponse, error) {
	resp, err := c.do(http.MethodPost, "/auth/refresh", map[string]string{
		"refresh_token": refreshToken,
	}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("refresh failed (%d): %s", resp.StatusCode, string(b))
	}
	var out LoginResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) Logout() error {
	resp, err := c.do(http.MethodPost, "/auth/logout", nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 && resp.StatusCode != 404 {
		return fmt.Errorf("logout failed (%d)", resp.StatusCode)
	}
	return nil
}

func (c *Client) GetConfig() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/config", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("config failed (%d): %s", resp.StatusCode, string(b))
	}
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return out, nil
}

func (c *Client) Login(email, password string) (*LoginResponse, error) {
	resp, err := c.do(http.MethodPost, "/auth/login", map[string]string{
		"email":    email,
		"password": password,
	}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("login failed (%d): %s", resp.StatusCode, string(b))
	}
	var out LoginResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) StartDeviceAuth(clientLabel string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/auth/device/start", map[string]string{
		"client_label": clientLabel,
	}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("device start failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) PollDeviceToken(deviceCode string) (*LoginResponse, error) {
	resp, err := c.do(http.MethodPost, "/auth/device/token", map[string]string{
		"device_code": deviceCode,
	}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 428 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("authorization_pending (%d): %s", resp.StatusCode, string(b))
	}
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("device token failed (%d): %s", resp.StatusCode, string(b))
	}
	var out LoginResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) ExchangeApiKey(apiKey string) (*LoginResponse, error) {
	resp, err := c.do(http.MethodPost, "/auth/api-key/exchange", map[string]string{
		"api_key": apiKey,
	}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("api-key exchange failed (%d): %s", resp.StatusCode, string(b))
	}
	var out LoginResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) BindWorkspace(path string) error {
	resp, err := c.do(http.MethodPost, "/ui/workspace", map[string]string{"path": path}, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("workspace bind failed (%d): %s", resp.StatusCode, string(b))
	}
	return nil
}

type WorkspaceItem struct {
	ID          string `json:"id"`
	Path        string `json:"path"`
	Label       string `json:"label"`
	ConnectorID string `json:"connector_id,omitempty"`
}

func (c *Client) GetWorkspaces() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/workspaces", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("workspaces get failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) PutWorkspaces(items []WorkspaceItem, activeID string) (map[string]any, error) {
	body := map[string]any{
		"workspaces": items,
	}
	if activeID != "" {
		body["active_workspace_id"] = activeID
	}
	resp, err := c.do(http.MethodPost, "/ui/workspaces", body, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("workspaces put failed (%d): %s", resp.StatusCode, string(b))
	}
	return out, nil
}

func (c *Client) ListApprovals(status string) (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/approvals?status="+status, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("approvals list failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ApprovalDiff(id string) (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/approvals/"+id+"/diff", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("diff failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) Approve(id string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/approvals/"+id+"/approve", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("approve failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) Deny(id, reason string) error {
	body := map[string]string{}
	if reason != "" {
		body["reason"] = reason
	}
	resp, err := c.do(http.MethodPost, "/approvals/"+id+"/deny", body, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("deny failed (%d)", resp.StatusCode)
	}
	return nil
}

func (c *Client) ListSessions() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/chat-sessions", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("sessions failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) GetWorkspace() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/workspace", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("workspace get failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) GetPreferences() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/preferences", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("preferences failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) SetProfile(letter string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/ui/profile", map[string]string{"profile": letter}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("profile failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) GetCloudModels() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/cloud-models", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("cloud-models failed (%d): %s", resp.StatusCode, string(b))
	}
	return out, nil
}

func (c *Client) SetPreferences(patch map[string]any) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/ui/preferences", patch, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	var out map[string]any
	_ = json.Unmarshal(body, &out)
	if resp.StatusCode >= 400 {
		detail, _ := out["detail"].(string)
		if detail == "" {
			detail = string(body)
		}
		return nil, fmt.Errorf("%s", detail)
	}
	if out == nil {
		out = map[string]any{}
	}
	return out, nil
}

func (c *Client) GetInferenceCatalog() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/inference_catalog", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("inference catalog failed (%d)", resp.StatusCode)
	}
	return out, nil
}

type MediaAttachment struct {
	Kind       string `json:"kind"`
	Mime       string `json:"mime"`
	DataBase64 string `json:"data_base64"`
}

type ClarifyResponse struct {
	InterruptID string `json:"interrupt_id"`
	Choice      string `json:"choice,omitempty"`
	Custom      string `json:"custom,omitempty"`
}

type AskRequest struct {
	Text             string            `json:"text"`
	UseAgentTools    bool              `json:"use_agent_tools"`
	ChatSessionID    string            `json:"chat_session_id,omitempty"`
	ModelOverride    string            `json:"model_override,omitempty"`
	WorkspaceID      string            `json:"-"`
	MediaAttachments []MediaAttachment `json:"media_attachments,omitempty"`
	ClarifyResponse  *ClarifyResponse  `json:"clarify_response,omitempty"`
}

func (c *Client) CreateSession(title string) (map[string]any, error) {
	body := map[string]string{}
	if title != "" {
		body["title"] = title
	}
	resp, err := c.do(http.MethodPost, "/ui/chat-sessions", body, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("create session failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) DeleteSession(sessionID string) error {
	resp, err := c.do(http.MethodDelete, "/ui/chat-sessions/"+sessionID, nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("delete session failed (%d)", resp.StatusCode)
	}
	return nil
}

func (c *Client) PatchSession(sessionID, title string) (map[string]any, error) {
	resp, err := c.do(http.MethodPatch, "/ui/chat-sessions/"+sessionID, map[string]string{
		"title": title,
	}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("patch session failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) UndoRequest(requestID string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/assistant/undo", map[string]string{
		"request_id": requestID,
	}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("undo failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) PinSession(sessionID string, pinned bool) (map[string]any, error) {
	resp, err := c.do(http.MethodPatch, "/ui/chat-sessions/"+sessionID, map[string]bool{
		"pinned": pinned,
	}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("pin session failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) GetSurface(sessionID string) (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/sessions/"+sessionID+"/surface", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("surface failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) RespondInterrupt(sessionID, interruptID, choice, custom string) (map[string]any, error) {
	body := map[string]string{}
	if choice != "" {
		body["choice"] = choice
	}
	if custom != "" {
		body["custom"] = custom
	}
	path := fmt.Sprintf("/ui/sessions/%s/interrupts/%s/respond", sessionID, interruptID)
	resp, err := c.do(http.MethodPost, path, body, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("interrupt respond failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) AskStream(req AskRequest, workspace string, onEvent func(event, data string) error) error {
	reqBody := req
	if !reqBody.UseAgentTools {
		reqBody.UseAgentTools = true
	}
	headers := map[string]string{}
	if workspace != "" {
		headers["X-Central-Workspace"] = workspace
	}
	if req.WorkspaceID != "" {
		headers["X-Central-Workspace-Id"] = req.WorkspaceID
	}
	resp, err := c.do(http.MethodPost, "/assistant/text/stream", reqBody, headers)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("stream failed (%d): %s", resp.StatusCode, string(b))
	}
	sc := bufio.NewScanner(resp.Body)
	var eventType string
	for sc.Scan() {
		line := sc.Text()
		if strings.HasPrefix(line, "event:") {
			eventType = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
			continue
		}
		if strings.HasPrefix(line, "data:") {
			data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			if eventType != "" && onEvent != nil {
				if err := onEvent(eventType, data); err != nil {
					return err
				}
			}
		}
	}
	return sc.Err()
}

func (c *Client) ListTeamAgents(status string) (map[string]any, error) {
	path := "/ui/team/agents"
	if status != "" {
		path += "?status=" + status
	}
	resp, err := c.do(http.MethodGet, path, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("team agents failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ListTeamSkills(status string) (map[string]any, error) {
	path := "/ui/team/skills"
	if status != "" {
		path += "?status=" + status
	}
	resp, err := c.do(http.MethodGet, path, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("team skills failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) CreateTeamAgent(name, prompt, modelID string) (map[string]any, error) {
	body := map[string]any{"name": name, "prompt": prompt}
	if modelID != "" {
		body["model_id"] = modelID
	}
	resp, err := c.do(http.MethodPost, "/ui/team/agents", body, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("create agent failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) SubmitTeamAgentReview(agentID string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/ui/team/agents/"+agentID+"/submit-review", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("submit review failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) PublishTeamAgent(agentID string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/ui/team/agents/"+agentID+"/publish", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("publish agent failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ListTeamRules(status string) (map[string]any, error) {
	path := "/ui/team/rules"
	if status != "" {
		path += "?status=" + status
	}
	resp, err := c.do(http.MethodGet, path, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("team rules failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ApproveTeamRule(ruleID string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/ui/team/rules/"+ruleID+"/approve", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("approve rule failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ListAuditEvents(since, userID, action string, limit int) (map[string]any, error) {
	q := fmt.Sprintf("/admin/audit/events?limit=%d", limit)
	if since != "" {
		q += "&since=" + since
	}
	if userID != "" {
		q += "&user_id=" + userID
	}
	if action != "" {
		q += "&action=" + action
	}
	resp, err := c.do(http.MethodGet, q, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("audit list failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ExportAudit(format, since string, limit int) ([]byte, error) {
	q := fmt.Sprintf("/admin/audit/export?format=%s&limit=%d", format, limit)
	if since != "" {
		q += "&since=" + since
	}
	resp, err := c.do(http.MethodGet, q, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("audit export failed (%d): %s", resp.StatusCode, string(b))
	}
	return io.ReadAll(resp.Body)
}

func (c *Client) ShowPolicies() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/admin/policies", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("policy show failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ListWorkItems(status string) (map[string]any, error) {
	path := "/ui/work-items"
	if status != "" {
		path += "?status=" + status
	}
	resp, err := c.do(http.MethodGet, path, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("work items list failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) GetWorkItem(id string) (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/work-items/"+id, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("work item get failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) CreateWorkItem(title, description, priority, sessionID, workspace string) (map[string]any, error) {
	return c.CreateWorkItemBody(map[string]any{
		"title":          title,
		"description":    description,
		"priority":       priority,
		"session_id":     sessionID,
		"workspace_path": workspace,
	})
}

// CreateWorkItemBody posts a work item with full body control (agent_name, skills, etc.).
func (c *Client) CreateWorkItemBody(body map[string]any) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/ui/work-items", body, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("work item create failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) PatchWorkItem(id string, patch map[string]any) (map[string]any, error) {
	resp, err := c.do(http.MethodPatch, "/ui/work-items/"+id, patch, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("work item patch failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) WorkWorkItem(id string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/ui/work-items/"+id+"/work", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("work item work failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) LinkWorkItem(id, externalURL, externalID string) (map[string]any, error) {
	body := map[string]any{"external_url": externalURL}
	if externalID != "" {
		body["external_id"] = externalID
	}
	resp, err := c.do(http.MethodPost, "/ui/work-items/"+id+"/link", body, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("work item link failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) PostComment(workItemID, body string) (map[string]any, error) {
	req := map[string]any{"body": body}
	resp, err := c.do(http.MethodPost, "/ui/work-items/"+workItemID+"/comments", req, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("comment failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ConnectorRegister(connectorID string) error {
	resp, err := c.do(http.MethodPost, "/connector/register", map[string]any{
		"connector_id":      connectorID,
		"capabilities":      []string{"file.read", "file.write", "file.patch", "shell.exec"},
		"protocol_version":  "1",
		"device_label":      "central-cli",
	}, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("register failed (%d): %s", resp.StatusCode, string(b))
	}
	return nil
}

func (c *Client) ConnectorHeartbeat(connectorID string) error {
	resp, err := c.do(http.MethodPost, "/connector/heartbeat", map[string]string{
		"connector_id": connectorID,
	}, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 404 {
		return fmt.Errorf("connector_not_registered")
	}
	if resp.StatusCode >= 400 {
		return fmt.Errorf("heartbeat failed (%d)", resp.StatusCode)
	}
	return nil
}

func (c *Client) PollJobs(connectorID string) ([]map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/connector/jobs?connector_id="+connectorID+"&limit=10", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out struct {
		Items []map[string]any `json:"items"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("poll jobs failed (%d)", resp.StatusCode)
	}
	return out.Items, nil
}

func (c *Client) SubmitJobResult(jobID, connectorID, status string, result map[string]any) error {
	resp, err := c.do(http.MethodPost, "/connector/jobs/"+jobID+"/result", map[string]any{
		"status":       status,
		"result":       result,
		"connector_id": connectorID,
	}, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("job result failed (%d): %s", resp.StatusCode, string(b))
	}
	return nil
}

func (c *Client) ExportAuditReport(format, since, pathPrefix string, limit int) ([]byte, error) {
	q := fmt.Sprintf("/admin/audit/report?format=%s&limit=%d", format, limit)
	if since != "" {
		q += "&since=" + since
	}
	if pathPrefix != "" {
		q += "&path_prefix=" + pathPrefix
	}
	resp, err := c.do(http.MethodGet, q, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("audit report failed (%d): %s", resp.StatusCode, string(b))
	}
	return io.ReadAll(resp.Body)
}

func (c *Client) ListCompliancePacks() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/admin/compliance/packs", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("compliance list failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ShowCompliancePack(packID string) (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/admin/compliance/packs/"+packID, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("compliance show failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ApplyCompliancePack(packID string) (map[string]any, error) {
	resp, err := c.do(http.MethodPost, "/admin/compliance/apply", map[string]string{"pack_id": packID}, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("compliance apply failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) ListBreakGlass(userID string) (map[string]any, error) {
	path := "/admin/break-glass/active"
	if userID != "" {
		path += "?user_id=" + userID
	}
	resp, err := c.do(http.MethodGet, path, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("break-glass list failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) GrantBreakGlass(pathPattern, reason, userID string, ttlHours float64) (map[string]any, error) {
	body := map[string]any{
		"path_pattern": pathPattern,
		"reason":       reason,
	}
	if userID != "" {
		body["user_id"] = userID
	}
	if ttlHours > 0 {
		body["ttl_hours"] = ttlHours
	}
	resp, err := c.do(http.MethodPost, "/admin/break-glass/grant", body, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("break-glass grant failed (%d)", resp.StatusCode)
	}
	return out, nil
}

func (c *Client) RevokeBreakGlass(grantID string) error {
	resp, err := c.do(http.MethodDelete, "/admin/break-glass/"+grantID, nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("break-glass revoke failed (%d)", resp.StatusCode)
	}
	return nil
}

func (c *Client) DeployResidency() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/admin/deploy/residency", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("deploy residency failed (%d)", resp.StatusCode)
	}
	return out, nil
}

// GetUsage returns per-tenant usage stats (tokens + cost) for the current hour.
func (c *Client) GetUsage() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/usage", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("usage failed (%d)", resp.StatusCode)
	}
	return out, nil
}

// GetSidebar returns consolidated sidebar data (Phase 4 — single call).
func (c *Client) GetSidebar() (map[string]any, error) {
	resp, err := c.do(http.MethodGet, "/ui/sidebar", nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("sidebar failed (%d)", resp.StatusCode)
	}
	return out, nil
}

// ImportSession imports messages into a VPS session (for SOLO→TEAM sync).
func (c *Client) ImportSession(sessionID string, messages []map[string]string) error {
	body := map[string]any{
		"messages": messages,
	}
	resp, err := c.do(http.MethodPost, "/ui/chat-sessions/"+sessionID+"/import", body, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("import session failed (%d)", resp.StatusCode)
	}
	return nil
}

// GetTeamRules fetches approved team rules from the VPS.
func (c *Client) GetTeamRules(tenant string) ([]map[string]any, error) {
	path := "/ui/team-rules"
	if tenant != "" {
		path += "?tenant=" + tenant
	}
	resp, err := c.do(http.MethodGet, path, nil, nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("team rules failed (%d)", resp.StatusCode)
	}
	rules, _ := out["rules"].([]any)
	var result []map[string]any
	for _, r := range rules {
		if m, ok := r.(map[string]any); ok {
			result = append(result, m)
		}
	}
	return result, nil
}
