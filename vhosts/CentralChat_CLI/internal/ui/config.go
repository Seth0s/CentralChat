package ui

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/centralchurch/central-cli/internal/config"
)

// TUIConfig mirrors ~/.config/central/tui.toml (D2: reasoning collapsed by default).
type TUIConfig struct {
	Theme               string // dark | light
	ReasoningPanel      string // open | collapsed | hidden
	ReasoningWidthCols  int
	ReasoningSyncScroll bool
	SidebarWidthCols    int
}

func DefaultTUIConfig() TUIConfig {
	return TUIConfig{
		Theme:              "dark",
		ReasoningPanel:     "collapsed",
		ReasoningWidthCols: 24,
		SidebarWidthCols:   26,
	}
}

func LoadTUIConfig() TUIConfig {
	cfg := DefaultTUIConfig()
	dir, err := config.ConfigDir()
	if err != nil {
		return cfg
	}
	data, err := os.ReadFile(filepath.Join(dir, "tui.toml"))
	if err != nil {
		return cfg
	}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, "[") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		val := strings.Trim(strings.TrimSpace(parts[1]), `"`)
		switch key {
		case "theme":
			switch val {
			case "light", "dark", "central-dark", "central-light":
				cfg.Theme = val
			}
		case "panel":
			cfg.ReasoningPanel = val
		case "width_cols":
			if n, err := parseInt(val); err == nil && n > 8 {
				cfg.ReasoningWidthCols = n
			}
		case "sidebar_width_cols":
			if n, err := parseInt(val); err == nil && n > 12 {
				cfg.SidebarWidthCols = n
			}
		case "sync_scroll":
			cfg.ReasoningSyncScroll = val == "true"
		}
	}
	if cfg.ReasoningPanel == "" {
		cfg.ReasoningPanel = "collapsed"
	}
	return cfg
}

func parseInt(s string) (int, error) {
	var n int
	_, err := fmt.Sscanf(s, "%d", &n)
	return n, err
}
