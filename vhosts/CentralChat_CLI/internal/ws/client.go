package ws

import (
	"encoding/json"
	"fmt"
	"log"
	"net/url"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// ── Client ──────────────────────────────────────────────────────

// Client is a WebSocket client for the TEAM hybrid mode connector.
// It maintains a single persistent connection to the VPS and
// automatically reconnects with exponential backoff on disconnect.
type Client struct {
	baseURL  string
	token    string
	conn     *websocket.Conn
	mu       sync.Mutex
	done     chan struct{}
	closed   bool

	// Reconnect state
	reconnecting bool
	reconnectMu  sync.Mutex

	// Callback invoked on each received message (optional).
	OnMessage func(Message)

	// Callback invoked when the connection is lost (before reconnect).
	OnDisconnect func(err error)
}

// Connect dials the WebSocket endpoint and returns a ready Client.
// The token is passed as a ?token= query parameter on the WS URL.
//
// Endpoint: wss://{baseURL}/connector/v1/ws?token={token}
func Connect(baseURL string, token string) (*Client, error) {
	parsed, err := url.Parse(baseURL)
	if err != nil {
		return nil, fmt.Errorf("ws connect: invalid base URL %q: %w", baseURL, err)
	}

	wsURL := url.URL{
		Scheme:   "wss",
		Host:     parsed.Host,
		Path:     "/connector/v1/ws",
		RawQuery: url.Values{"token": {token}}.Encode(),
	}

	// If baseURL uses http:// (local dev), use ws://
	if parsed.Scheme == "http" {
		wsURL.Scheme = "ws"
	}

	c := &Client{
		baseURL: baseURL,
		token:   token,
		done:    make(chan struct{}),
	}

	conn, _, err := websocket.DefaultDialer.Dial(wsURL.String(), nil)
	if err != nil {
		return nil, fmt.Errorf("ws connect: dial %s: %w", wsURL.String(), err)
	}

	c.conn = conn
	log.Printf("[ws] connected to %s", wsURL.String())

	return c, nil
}

// ── Send methods ────────────────────────────────────────────────

// sendJSON serializes msg and writes it to the WebSocket.
func (c *Client) sendJSON(v interface{}) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.conn == nil {
		return fmt.Errorf("ws: not connected")
	}

	w, err := c.conn.NextWriter(websocket.TextMessage)
	if err != nil {
		return fmt.Errorf("ws: next writer: %w", err)
	}
	defer w.Close()

	enc := json.NewEncoder(w)
	if err := enc.Encode(v); err != nil {
		return fmt.Errorf("ws: encode: %w", err)
	}

	return nil
}

// SendTurn sends an assistant_turn message to the VPS.
func (c *Client) SendTurn(msg AssistantTurn) error {
	msg.MessageType = "assistant_turn"
	return c.sendJSON(msg)
}

// SendToolResult sends a tool_result message to the VPS.
func (c *Client) SendToolResult(msg ToolResult) error {
	msg.MessageType = "tool_result"
	return c.sendJSON(msg)
}

// SendTurnComplete sends a turn_complete message to the VPS.
func (c *Client) SendTurnComplete(msg TurnComplete) error {
	msg.MessageType = "turn_complete"
	return c.sendJSON(msg)
}

// SendHeartbeat sends a heartbeat keepalive message.
func (c *Client) SendHeartbeat(connectorID string) error {
	msg := Heartbeat{
		MessageType: "heartbeat",
		ConnectorID: connectorID,
		Timestamp:   float64(time.Now().UnixMilli()) / 1000.0,
	}
	return c.sendJSON(msg)
}

// SendContextPush sends an L2 context update to the VPS.
func (c *Client) SendContextPush(msg ContextPush) error {
	msg.MessageType = "context_push"
	return c.sendJSON(msg)
}

// ── Receive loop ────────────────────────────────────────────────

// Receive blocks reading a single message from the WebSocket.
// It returns a typed Message interface value. Callers should
// type-switch on the result.
//
// For long-lived listeners, use Listen() instead.
func (c *Client) Receive() (Message, error) {
	c.mu.Lock()
	conn := c.conn
	c.mu.Unlock()

	if conn == nil {
		return nil, fmt.Errorf("ws: not connected")
	}

	_, raw, err := conn.ReadMessage()
	if err != nil {
		return nil, fmt.Errorf("ws: read: %w", err)
	}

	return parseMessage(raw)
}

// Listen starts a blocking read loop that dispatches each message
// to c.OnMessage. It handles reconnection automatically.
// Returns when Close() is called or an unrecoverable error occurs.
func (c *Client) Listen() error {
	for {
		// Check if closed
		select {
		case <-c.done:
			return nil
		default:
		}

		msg, err := c.Receive()
		if err != nil {
			if c.isClosed() {
				return nil
			}

			log.Printf("[ws] read error: %v — reconnecting...", err)
			if c.OnDisconnect != nil {
				c.OnDisconnect(err)
			}

			if reconnectErr := c.reconnect(); reconnectErr != nil {
				return fmt.Errorf("ws: reconnect failed: %w", reconnectErr)
			}
			continue
		}

		if c.OnMessage != nil {
			c.OnMessage(msg)
		}
	}
}

// ── Reconnect ───────────────────────────────────────────────────

// reconnect attempts to re-establish the WebSocket with exponential
// backoff (1s, 2s, 4s, 8s, ... max 30s).
func (c *Client) reconnect() error {
	c.reconnectMu.Lock()
	defer c.reconnectMu.Unlock()

	if c.reconnecting {
		return fmt.Errorf("ws: already reconnecting")
	}
	c.reconnecting = true
	defer func() { c.reconnecting = false }()

	backoff := 1 * time.Second
	maxBackoff := 30 * time.Second

	parsed, err := url.Parse(c.baseURL)
	if err != nil {
		return fmt.Errorf("ws reconnect: invalid base URL: %w", err)
	}

	wsURL := url.URL{
		Scheme:   "wss",
		Host:     parsed.Host,
		Path:     "/connector/v1/ws",
		RawQuery: url.Values{"token": {c.token}}.Encode(),
	}
	if parsed.Scheme == "http" {
		wsURL.Scheme = "ws"
	}

	for {
		select {
		case <-c.done:
			return fmt.Errorf("ws: closed during reconnect")
		default:
		}

		log.Printf("[ws] reconnecting in %v...", backoff)
		time.Sleep(backoff)

		conn, _, dialErr := websocket.DefaultDialer.Dial(wsURL.String(), nil)
		if dialErr != nil {
			log.Printf("[ws] reconnect dial failed: %v", dialErr)
			backoff *= 2
			if backoff > maxBackoff {
				backoff = maxBackoff
			}
			continue
		}

		// Success — replace the connection
		c.mu.Lock()
		if c.conn != nil {
			c.conn.Close() // best-effort close of old conn
		}
		c.conn = conn
		c.mu.Unlock()

		log.Printf("[ws] reconnected to %s", wsURL.String())
		return nil
	}
}

// ── Lifecycle ───────────────────────────────────────────────────

// Close shuts down the WebSocket connection and stops the Listen loop.
func (c *Client) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.closed {
		return nil
	}
	c.closed = true
	close(c.done)

	if c.conn != nil {
		// Send close frame (best-effort)
		_ = c.conn.WriteMessage(
			websocket.CloseMessage,
			websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""),
		)
		_ = c.conn.Close()
		c.conn = nil
	}

	return nil
}

// isClosed returns true if Close() has been called (non-blocking).
func (c *Client) isClosed() bool {
	select {
	case <-c.done:
		return true
	default:
		return false
	}
}

// ── Message parser ──────────────────────────────────────────────

// parseMessage decodes a raw JSON frame into a typed Message.
func parseMessage(raw []byte) (Message, error) {
	var header rawMessage
	if err := json.Unmarshal(raw, &header); err != nil {
		return nil, fmt.Errorf("ws: parse message type: %w", err)
	}

	switch header.Type {
	case "inference_plan":
		var m InferencePlanMessage
		if err := json.Unmarshal(raw, &m); err != nil {
			return nil, fmt.Errorf("ws: decode inference_plan: %w", err)
		}
		return m, nil

	case "approval_required":
		var m ApprovalRequired
		if err := json.Unmarshal(raw, &m); err != nil {
			return nil, fmt.Errorf("ws: decode approval_required: %w", err)
		}
		return m, nil

	case "policy_denied":
		var m PolicyDenied
		if err := json.Unmarshal(raw, &m); err != nil {
			return nil, fmt.Errorf("ws: decode policy_denied: %w", err)
		}
		return m, nil

	case "stale_diff_warning":
		var m StaleDiffWarning
		if err := json.Unmarshal(raw, &m); err != nil {
			return nil, fmt.Errorf("ws: decode stale_diff_warning: %w", err)
		}
		return m, nil

	case "ping":
		// Return a raw ping acknowledged message
		return pingMessage{}, nil

	case "welcome", "tool_result_ack", "turn_complete_ack", "context_push_ack":
		// Acknowledgment messages — return as generic ack
		return ackMessage{msgType: header.Type}, nil

	case "error":
		var m PolicyDenied
		_ = json.Unmarshal(raw, &m)
		if m.MessageType == "" {
			m.MessageType = "error"
		}
		return m, nil

	default:
		log.Printf("[ws] unknown message type: %s (raw=%s)", header.Type, string(raw))
		return unknownMessage{msgType: header.Type, raw: raw}, nil
	}
}

// ── System message helpers ──────────────────────────────────────

// pingMessage represents a server ping (requires pong response).
type pingMessage struct{}

func (pingMessage) Type() string { return "ping" }

// ackMessage represents a generic server acknowledgment.
type ackMessage struct{ msgType string }

func (m ackMessage) Type() string { return m.msgType }

// unknownMessage wraps an unrecognized message type.
type unknownMessage struct {
	msgType string
	raw     []byte
}

func (m unknownMessage) Type() string { return m.msgType }
func (m unknownMessage) Raw() []byte  { return m.raw }
