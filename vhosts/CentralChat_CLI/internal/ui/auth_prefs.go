package ui

import (
	"encoding/json"
	"os"
	"path/filepath"

	"github.com/centralchurch/central-cli/internal/config"
)

const authPrefsFile = "auth_preferences.json"

// AuthPreferences persists login UX defaults (CLI_UX_SPEC §4.1).
type AuthPreferences struct {
	LastMethod string `json:"last_method"` // email | device | api_key
	LastEmail  string `json:"last_email,omitempty"`
}

func LoadAuthPreferences() AuthPreferences {
	p := AuthPreferences{LastMethod: "email"}
	dir, err := config.ConfigDir()
	if err != nil {
		return p
	}
	data, err := os.ReadFile(filepath.Join(dir, authPrefsFile))
	if err != nil {
		return p
	}
	_ = json.Unmarshal(data, &p)
	if p.LastMethod == "" {
		p.LastMethod = "email"
	}
	return p
}

func SaveAuthPreferences(p AuthPreferences) error {
	dir, err := config.ConfigDir()
	if err != nil {
		return err
	}
	data, err := json.MarshalIndent(p, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, authPrefsFile), data, 0o600)
}
