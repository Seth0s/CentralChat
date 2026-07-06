package ui

import "github.com/charmbracelet/lipgloss"

// ── Color tokens ──
const (
	ColorCanvas  = "#000000" // chat, screen, main reading surface
	ColorSurface = "#252526" // panel sidebar, input, pickers, interactive surfaces

	ColorText      = "#d4d4d4" // primary text — warm gray, comfortable on black
	ColorTextLabel = "#9cdcfe" // labels — soft light blue, gentle on eyes
	ColorTextTitle = "#4488cc" // titles/accent — darker blue, good on black
	ColorTextDim   = "#808080" // secondary text — medium gray
	ColorBorder    = "#3e3e42" // borders, separators
)

// CentralTheme groups lipgloss styles for the TUI (P4a design system).
type CentralTheme struct {
	Name string

	StyleAccent lipgloss.Style
	StyleDim    lipgloss.Style
	StyleError  lipgloss.Style

	StyleTabActive lipgloss.Style
	StyleTab       lipgloss.Style
	StyleTabHeader lipgloss.Style
	StyleTabHeaderActive lipgloss.Style
	StyleBorder    lipgloss.Style
	StyleCard      lipgloss.Style
	StylePanel     lipgloss.Style

	StyleListActive    lipgloss.Style
	StyleListRow       lipgloss.Style
	StyleSectionHeader lipgloss.Style

	StyleChipPlan  lipgloss.Style
	StyleChipBuild lipgloss.Style
	StyleBarPlan   lipgloss.Style
	StyleBarBuild  lipgloss.Style

	StyleProgressFill  lipgloss.Style
	StyleProgressWarn  lipgloss.Style
	StyleProgressEmpty lipgloss.Style
	StyleMetricLabel   lipgloss.Style

	StyleInput      lipgloss.Style
	StyleInputFocus lipgloss.Style

	StyleMsgUser      lipgloss.Style
	StyleMsgAssistant lipgloss.Style
	StyleUserBubble   lipgloss.Style
	StyleThoughtLink  lipgloss.Style
	StyleBarUser      lipgloss.Style
	StyleInputBox     lipgloss.Style
	StyleSeparator    lipgloss.Style
	StyleLabel        lipgloss.Style
	StyleScreen       lipgloss.Style
}

var currentTheme CentralTheme

// Theme returns the active theme.
func Theme() CentralTheme {
	if currentTheme.Name == "" {
		return ApplyCentralTheme("dark")
	}
	return currentTheme
}

// ApplyCentralTheme loads palette and syncs legacy package-level style vars.
func ApplyCentralTheme(name string) CentralTheme {
	t := buildTheme(name)
	currentTheme = t
	syncLegacyStyles(t)
	return t
}

func buildTheme(name string) CentralTheme {
	if name == "light" {
		return CentralTheme{
			Name:               "light",
			StyleAccent:        lipgloss.NewStyle().Foreground(lipgloss.Color("25")).Bold(true),
			StyleDim:           lipgloss.NewStyle().Foreground(lipgloss.Color("240")),
			StyleError:         lipgloss.NewStyle().Foreground(lipgloss.Color("160")).Bold(true),
			StyleTabActive:     lipgloss.NewStyle().Foreground(lipgloss.Color("255")).Background(lipgloss.Color("33")).Padding(0, 1),
			StyleTab:           lipgloss.NewStyle().Foreground(lipgloss.Color("236")).Padding(0, 1),
			StyleTabHeader:     lipgloss.NewStyle().Foreground(lipgloss.Color("236")).Background(lipgloss.Color("255")).Padding(0, 1),
			StyleTabHeaderActive: lipgloss.NewStyle().Foreground(lipgloss.Color("255")).Background(lipgloss.Color("33")).Padding(0, 1),
			StyleBorder:        lipgloss.NewStyle().Border(lipgloss.NormalBorder()).BorderForeground(lipgloss.Color("250")),
			StyleCard: lipgloss.NewStyle().
				Border(lipgloss.RoundedBorder()).
				BorderForeground(lipgloss.Color("250")).
				Background(lipgloss.Color("255")).
				Padding(1, 2),
			StylePanel:         lipgloss.NewStyle().Background(lipgloss.Color("255")).Padding(0, 1),
			StyleListActive:    lipgloss.NewStyle().Background(lipgloss.Color("33")).Foreground(lipgloss.Color("255")).Bold(true),
			StyleListRow:       lipgloss.NewStyle().Foreground(lipgloss.Color("236")),
			StyleSectionHeader: lipgloss.NewStyle().Foreground(lipgloss.Color("99")).Bold(true),
			StyleChipPlan:      lipgloss.NewStyle().Foreground(lipgloss.Color("208")).Bold(true),
			StyleChipBuild:     lipgloss.NewStyle().Foreground(lipgloss.Color("25")).Bold(true),
			StyleBarPlan:       lipgloss.NewStyle().Foreground(lipgloss.Color("208")).Bold(true),
			StyleBarBuild:      lipgloss.NewStyle().Foreground(lipgloss.Color("25")).Bold(true),
			StyleProgressFill:  lipgloss.NewStyle().Foreground(lipgloss.Color("25")).Background(lipgloss.Color("0")),
			StyleProgressWarn:  lipgloss.NewStyle().Foreground(lipgloss.Color("220")).Background(lipgloss.Color("0")),
			StyleProgressEmpty: lipgloss.NewStyle().Foreground(lipgloss.Color("252")).Background(lipgloss.Color("0")),
			StyleMetricLabel:   lipgloss.NewStyle().Foreground(lipgloss.Color("240")),
			StyleInput: lipgloss.NewStyle().
				Border(lipgloss.NormalBorder()).
				BorderForeground(lipgloss.Color("250")).
				Background(lipgloss.Color("255")).
				Foreground(lipgloss.Color("236")).
				Padding(0, 1),
			StyleInputFocus: lipgloss.NewStyle().
				Border(lipgloss.NormalBorder()).
				BorderForeground(lipgloss.Color("33")).
				Background(lipgloss.Color("255")).
				Foreground(lipgloss.Color("236")).
				Padding(0, 1),
			StyleMsgUser:      lipgloss.NewStyle().Foreground(lipgloss.Color("245")),
			StyleMsgAssistant: lipgloss.NewStyle().Foreground(lipgloss.Color("252")),
			StyleUserBubble: lipgloss.NewStyle().
				Background(lipgloss.Color("252")).
				Foreground(lipgloss.Color("236")).
				Padding(0, 1),
			StyleThoughtLink:  lipgloss.NewStyle().Foreground(lipgloss.Color("208")).Italic(true),
			StyleBarUser:      lipgloss.NewStyle().Foreground(lipgloss.Color("33")).Bold(true),
			StyleInputBox: lipgloss.NewStyle().
				Background(lipgloss.Color("234")).
				Foreground(lipgloss.Color("252")).
				Padding(0, 1),
			StyleSeparator: lipgloss.NewStyle().Foreground(lipgloss.Color("238")),
			StyleLabel:     lipgloss.NewStyle().Foreground(lipgloss.Color("39")).Bold(true),
			StyleScreen:    lipgloss.NewStyle().Background(lipgloss.Color("255")),
		}
	}
	return CentralTheme{
		Name:               "dark",
		StyleAccent:        lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextTitle)).Bold(true),
		StyleDim:           lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)),
		StyleError:         lipgloss.NewStyle().Foreground(lipgloss.Color("1")).Bold(true),
		StyleTabActive:     lipgloss.NewStyle().Foreground(lipgloss.Color("15")).Background(lipgloss.Color("24")).Padding(0, 1),
		StyleTab:           lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)).Background(lipgloss.Color("235")).Padding(0, 1),
		StyleTabHeader:     lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)).Padding(0, 1),
		StyleTabHeaderActive: lipgloss.NewStyle().Foreground(lipgloss.Color("15")).Background(lipgloss.Color("62")).Padding(0, 1),
		StyleBorder:        lipgloss.NewStyle().Border(lipgloss.NormalBorder()).BorderForeground(lipgloss.Color(ColorBorder)).Background(lipgloss.Color(ColorCanvas)),
		StyleCard: lipgloss.NewStyle().
			Border(lipgloss.NormalBorder()).
			BorderForeground(lipgloss.Color(ColorBorder)).
			Background(lipgloss.Color(ColorSurface)).
			Padding(1, 2),
		StylePanel: lipgloss.NewStyle().
			Background(lipgloss.Color(ColorSurface)).
			Foreground(lipgloss.Color(ColorText)).
			Padding(0, 1),
		StyleListActive:    lipgloss.NewStyle().Background(lipgloss.Color("24")).Foreground(lipgloss.Color("255")).Bold(true),
		StyleListRow:       lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)),
		StyleSectionHeader: lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)).Bold(false),
		StyleChipPlan:      lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Bold(true),
		StyleChipBuild:     lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextLabel)).Bold(true),
		StyleBarPlan:       lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Bold(true),
		StyleBarBuild:      lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextTitle)).Bold(true),
		StyleProgressFill:  lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextTitle)).Background(lipgloss.Color("16")),
		StyleProgressWarn:  lipgloss.NewStyle().Foreground(lipgloss.Color("220")).Background(lipgloss.Color("16")),
		StyleProgressEmpty: lipgloss.NewStyle().Foreground(lipgloss.Color(ColorBorder)).Background(lipgloss.Color("16")),
		StyleMetricLabel:   lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)),
		StyleInput: lipgloss.NewStyle().
			Border(lipgloss.NormalBorder()).
			BorderForeground(lipgloss.Color(ColorBorder)).
			Background(lipgloss.Color(ColorSurface)).
			Foreground(lipgloss.Color(ColorText)).
			Padding(0, 1),
		StyleInputFocus: lipgloss.NewStyle().
			Border(lipgloss.NormalBorder()).
			BorderForeground(lipgloss.Color(ColorTextTitle)).
			Background(lipgloss.Color(ColorSurface)).
			Foreground(lipgloss.Color("255")).
			Padding(0, 1),
		StyleMsgUser:      lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)),
		StyleMsgAssistant: lipgloss.NewStyle().Foreground(lipgloss.Color("252")),
		StyleUserBubble: lipgloss.NewStyle().
			Background(lipgloss.Color("236")).
			Foreground(lipgloss.Color(ColorText)).
			Padding(0, 1),
		StyleThoughtLink:  lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Italic(true),
		StyleBarUser:      lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextLabel)).Bold(true),
		StyleInputBox: lipgloss.NewStyle().
			Background(lipgloss.Color(ColorSurface)).
			Foreground(lipgloss.Color(ColorText)).
			Padding(1, 2),
		StyleSeparator: lipgloss.NewStyle().Foreground(lipgloss.Color("238")),
		StyleLabel:     lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextLabel)).Bold(true),
		StyleScreen:    lipgloss.NewStyle().Background(lipgloss.Color(ColorCanvas)),
	}
}

func syncLegacyStyles(t CentralTheme) {
	styleAccent = t.StyleAccent
	styleDim = t.StyleDim
	styleError = t.StyleError
	styleTabActive = t.StyleTabActive
	styleTab = t.StyleTab
	styleBorder = t.StyleBorder
}
