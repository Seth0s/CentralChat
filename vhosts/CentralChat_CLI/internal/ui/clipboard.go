package ui

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/atotto/clipboard"
)

func (m model) lastAssistantPlainText() string {
	for i := len(m.messages) - 1; i >= 0; i-- {
		if m.messages[i].role == "assistant" && strings.TrimSpace(m.messages[i].content) != "" {
			return m.messages[i].content
		}
	}
	if m.streaming && strings.TrimSpace(m.streamingText) != "" {
		return m.streamingText
	}
	return ""
}

func (m *model) copyLastAssistant() (tea.Model, tea.Cmd) {
	text := m.lastAssistantPlainText()
	if text == "" {
		m.statusLine = "Nada para copiar"
		return m, nil
	}
	if err := clipboard.WriteAll(text); err != nil {
		m.errBar = "Não foi possível copiar"
		return m, nil
	}
	m.errBar = ""
	m.statusLine = "Resposta copiada"
	return m, nil
}
