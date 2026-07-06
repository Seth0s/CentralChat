package clierrors

import (
	"fmt"
	"strings"
)

// IsAuthError reports expired or invalid bearer credentials.
func IsAuthError(err error) bool {
	if err == nil {
		return false
	}
	lower := strings.ToLower(err.Error())
	return strings.Contains(lower, "401") ||
		strings.Contains(lower, "invalid_access_token") ||
		strings.Contains(lower, "unauthorized")
}

// UserMessage maps common API/CLI errors to actionable PT-BR text (D3.1).
func UserMessage(err error) string {
	if err == nil {
		return ""
	}
	msg := err.Error()
	lower := strings.ToLower(msg)

	switch {
	case strings.Contains(lower, "422") || strings.Contains(lower, "validation"):
		return "Invalid data — check email/password or API key and try again."
	case strings.Contains(lower, "401") || strings.Contains(lower, "invalid_access_token"):
		return "Session expired. Run: central login (or central login --device)"
	case strings.Contains(lower, "403") || strings.Contains(lower, "insufficient_role"):
		return "Sem permissão para esta acção. Verifique o papel (role) no token."
	case strings.Contains(lower, "429") || strings.Contains(lower, "concurrent stream"):
		return "Rate limit reached. Wait a few seconds and try again."
	case strings.Contains(lower, "policy") || strings.Contains(lower, "violation"):
		return "Blocked by policy. Review rules with: central policy show"
	case strings.Contains(lower, "connector offline") || strings.Contains(lower, "daemon"):
		return "Daemon local offline. Noutro terminal: central daemon"
	case strings.Contains(lower, "connection refused") || strings.Contains(lower, "no such host"):
		return "API unreachable. Check CENTRAL_API_URL and: central doctor"
	case strings.Contains(lower, "viewer_read_only"):
		return "Read-only mode — cannot modify the queue."
	default:
		return fmt.Sprintf("Erro: %s", msg)
	}
}
