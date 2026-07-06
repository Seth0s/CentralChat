package ui

import (
	"github.com/charmbracelet/bubbles/key"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/lipgloss"
)

const (
	sessionInputMinLines = 1
	sessionInputMaxLines = 8
)

// styleSessionInput configures a compact multiline session input (Enter sends, Ctrl+Enter newline).
func styleSessionInput(ta textarea.Model) textarea.Model {
	ta.ShowLineNumbers = false
	ta.Prompt = "> "
	ta.Placeholder = "Mensagem… (/help)"
	ta.CharLimit = 8000
	ta.SetHeight(sessionInputMinLines)
	ta.MaxHeight = sessionInputMaxLines

	ta.KeyMap.InsertNewline = key.NewBinding(key.WithKeys("alt+enter", "ctrl+j"))

	style := textarea.Style{
		Base:        lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)),
		Text:        lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)),
		Placeholder: lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)),
		Prompt:      lipgloss.NewStyle().Foreground(lipgloss.Color("39")),
		CursorLine:  lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)),
	}
	ta.FocusedStyle = style
	ta.BlurredStyle = style
	ta.Focus()
	return ta
}

// styleLoginInput keeps login fields on the same black background as the screen.
func styleLoginInput(ti textinput.Model) textinput.Model {
	inputBg := lipgloss.Color(ColorSurface)
	ti.Prompt = ""
	ti.TextStyle = lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)).Background(inputBg)
	ti.PlaceholderStyle = lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)).Background(inputBg)
	ti.Cursor.Style = lipgloss.NewStyle().
		Background(lipgloss.Color("39")).
		Foreground(lipgloss.Color("15"))
	return ti
}
