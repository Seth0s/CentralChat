package offline

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
)

// D-OFFLINE-1 — read-only cache for audit/sessions when API unreachable.

type Cache struct {
	AuditSessions []byte `json:"audit_sessions,omitempty"`
	WorkItems     []byte `json:"work_items,omitempty"`
	UpdatedAt     string `json:"updated_at,omitempty"`
}

var mu sync.Mutex

func cachePath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(home, ".config", "central")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	return filepath.Join(dir, "offline_cache.json"), nil
}

func Load() (*Cache, error) {
	path, err := cachePath()
	if err != nil {
		return nil, err
	}
	b, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return &Cache{}, nil
		}
		return nil, err
	}
	var c Cache
	if err := json.Unmarshal(b, &c); err != nil {
		return &Cache{}, nil
	}
	return &c, nil
}

func Save(c *Cache) error {
	mu.Lock()
	defer mu.Unlock()
	path, err := cachePath()
	if err != nil {
		return err
	}
	b, err := json.Marshal(c)
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o600)
}

func Enabled() bool {
	v := os.Getenv("CENTRAL_OFFLINE")
	return v == "1" || v == "true" || v == "yes"
}
