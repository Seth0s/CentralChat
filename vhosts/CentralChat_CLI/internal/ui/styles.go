package ui

import "github.com/charmbracelet/lipgloss"

var (
	styleAccent    = lipgloss.NewStyle().Foreground(lipgloss.Color("39")).Bold(true)
	styleDim       = lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim))
	styleError     = lipgloss.NewStyle().Foreground(lipgloss.Color("1")).Bold(true)
	styleTabActive = lipgloss.NewStyle().Foreground(lipgloss.Color("15")).Background(lipgloss.Color("62")).Padding(0, 1)
	styleTab       = lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)).Background(lipgloss.Color("235")).Padding(0, 1)
	styleBorder    = lipgloss.NewStyle().Border(lipgloss.NormalBorder()).BorderForeground(lipgloss.Color(ColorBorder)).Background(lipgloss.Color(ColorCanvas))
)

const wordmarkCompact = "CENTRAL"
const wordmarkSub = "approve · audit · workspace"

const wordmarkASCII = `
 ██████╗███████╗███╗   ██╗████████╗██████╗  █████╗ ██╗
██╔════╝██╔════╝████╗  ██║╚══██╔══╝██╔══██╗██╔══██╗██║
██║     █████╗  ██╔██╗ ██║   ██║   ██████╔╝███████║██║
██║     ██╔══╝  ██║╚██╗██║   ██║   ██╔══██╗██╔══██║██║
╚██████╗███████╗██║ ╚████║   ██║   ██║  ██║██║  ██║███████╗
 ╚═════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝`

func applyTheme(name string) {
	themeName := name
	switch themeName {
	case "central-dark", "":
		themeName = "dark"
	case "central-light":
		themeName = "light"
	}
	ApplyCentralTheme(themeName)
}

const wordmarkSessionASCII = `
 ██████╗ ███████╗███╗   ██╗ ████████╗ ██████╗  █████╗ ██╗
 ██╔════╝ ██╔════╝████╗  ██║ ╚══██╔══╝██╔══██╗██╔══██╗██║
 ██║      ███████╗██╔██╗ ██║    ██║   ██████╔╝███████║██║
 ██║      ██╔══██║██║╚██╗██║    ██║   ██╔══██╗██╔══██║██║
 ╚██████╗ ██║  ██║██║ ╚████║    ██║   ██║  ██║██║  ██║███████╗
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝    ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝`

func renderWordmark(width int) string {
	accent := styleAccent.Copy().Background(lipgloss.Color(ColorCanvas))
	dim := styleDim.Copy().Background(lipgloss.Color(ColorCanvas))
	if width < 70 {
		return accent.Render(wordmarkCompact) + "\n" + dim.Render(wordmarkSub)
	}
	return accent.Render(wordmarkASCII) + "\n" + dim.Render(wordmarkSub)
}

func renderSessionWordmarkCompact(width int) string {
	t := Theme()
	accent := t.StyleAccent.Copy().Background(lipgloss.Color(ColorCanvas))
	if width < 44 {
		return accent.Bold(true).Render("CENTRAL")
	}
	if width < 72 {
		return accent.Render(wordmarkSessionASCII)
	}
	return accent.Render(wordmarkASCII)
}
