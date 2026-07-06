package ui

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/config"
)

// WorkspaceTab is a persisted workspace binding (CLI_UX_SPEC §5.3).
// Path is the local directory path (Phase 1).
// ConnectorID links to a remote connector when backend is on a different machine (Phase 2+).
type WorkspaceTab struct {
	ID          string    `json:"id"`
	Path        string    `json:"path"`
	Label       string    `json:"label"`
	ConnectorID string    `json:"connector_id,omitempty"`
	LastUsedAt  time.Time `json:"last_used_at"`
}

type workspacesFile struct {
	Tabs             []WorkspaceTab `json:"tabs"`
	ActiveWorkspaceID string        `json:"active_workspace_id"`
}

func LoadWorkspaces() workspacesFile {
	dir, err := config.ConfigDir()
	if err != nil {
		return workspacesFile{}
	}
	data, err := os.ReadFile(filepath.Join(dir, "workspaces.json"))
	if err != nil {
		return workspacesFile{}
	}
	var wf workspacesFile
	if err := json.Unmarshal(data, &wf); err != nil {
		return workspacesFile{}
	}
	return wf
}

func SaveWorkspaces(wf workspacesFile) error {
	dir, err := config.ConfigDir()
	if err != nil {
		return err
	}
	data, err := json.MarshalIndent(wf, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "workspaces.json"), data, 0o600)
}

func workspaceLabel(path string) string {
	base := filepath.Base(path)
	if base == "." || base == "/" || base == "" {
		return path
	}
	return base
}

func newTabID() string {
	var b [8]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

func AddOrActivateWorkspace(path string) (workspacesFile, WorkspaceTab, error) {
	wf := LoadWorkspaces()
	path = filepath.Clean(path)
	for i, t := range wf.Tabs {
		if t.Path == path {
			wf.Tabs[i].LastUsedAt = time.Now().UTC()
			wf.ActiveWorkspaceID = t.ID
			_ = SaveWorkspaces(wf)
			_ = config.SaveWorkspace(path)
			return wf, wf.Tabs[i], nil
		}
	}
	tab := WorkspaceTab{
		ID:         newTabID(),
		Path:       path,
		Label:      workspaceLabel(path),
		LastUsedAt: time.Now().UTC(),
	}
	wf.Tabs = append(wf.Tabs, tab)
	wf.ActiveWorkspaceID = tab.ID
	if err := SaveWorkspaces(wf); err != nil {
		return wf, tab, err
	}
	_ = config.SaveWorkspace(path)
	return wf, tab, nil
}

func ActiveWorkspace(wf workspacesFile) *WorkspaceTab {
	if wf.ActiveWorkspaceID == "" {
		return nil
	}
	for i := range wf.Tabs {
		if wf.Tabs[i].ID == wf.ActiveWorkspaceID {
			return &wf.Tabs[i]
		}
	}
	return nil
}

func CloseWorkspaceTab(id string) workspacesFile {
	wf := LoadWorkspaces()
	out := make([]WorkspaceTab, 0, len(wf.Tabs))
	for _, t := range wf.Tabs {
		if t.ID != id {
			out = append(out, t)
		}
	}
	wf.Tabs = out
	if wf.ActiveWorkspaceID == id {
		wf.ActiveWorkspaceID = ""
		if len(out) > 0 {
			wf.ActiveWorkspaceID = out[len(out)-1].ID
		}
	}
	_ = SaveWorkspaces(wf)
	return wf
}

func WorkspacesToAPIItems(wf workspacesFile) []api.WorkspaceItem {
	out := make([]api.WorkspaceItem, 0, len(wf.Tabs))
	for _, t := range wf.Tabs {
		out = append(out, api.WorkspaceItem{
			ID:          t.ID,
			Path:        t.Path,
			Label:       t.Label,
			ConnectorID: t.ConnectorID,
		})
	}
	return out
}

func MergeWorkspacesFromServer(wf workspacesFile, server map[string]any) workspacesFile {
	raw, _ := server["items"].([]any)
	if len(raw) == 0 {
		return wf
	}
	var tabs []WorkspaceTab
	for _, item := range raw {
		row, ok := item.(map[string]any)
		if !ok {
			continue
		}
		id, _ := row["id"].(string)
		path, _ := row["path"].(string)
		label, _ := row["label"].(string)
		if id == "" || path == "" {
			continue
		}
		if label == "" {
			label = workspaceLabel(path)
		}
		connectorID, _ := row["connector_id"].(string)
		tabs = append(tabs, WorkspaceTab{
			ID:          id,
			Path:        path,
			Label:       label,
			ConnectorID: connectorID,
			LastUsedAt:  time.Now().UTC(),
		})
	}
	if len(tabs) == 0 {
		return wf
	}
	active, _ := server["active_workspace_id"].(string)
	if active == "" {
		active = tabs[len(tabs)-1].ID
	}
	wf.Tabs = tabs
	wf.ActiveWorkspaceID = active
	_ = SaveWorkspaces(wf)
	if tab := ActiveWorkspace(wf); tab != nil {
		_ = config.SaveWorkspace(tab.Path)
	}
	return wf
}

func SyncWorkspacesToServer(client *api.Client, wf workspacesFile) error {
	if client == nil || len(wf.Tabs) == 0 {
		return nil
	}
	_, err := client.PutWorkspaces(WorkspacesToAPIItems(wf), wf.ActiveWorkspaceID)
	return err
}

func SyncWorkspacesFromServer(client *api.Client) (workspacesFile, error) {
	wf := LoadWorkspaces()
	if client == nil {
		return wf, nil
	}
	out, err := client.GetWorkspaces()
	if err != nil {
		return wf, err
	}
	if items, ok := out["items"].([]any); ok && len(items) > 0 {
		return MergeWorkspacesFromServer(wf, out), nil
	}
	if len(wf.Tabs) > 0 {
		_ = SyncWorkspacesToServer(client, wf)
	}
	return wf, nil
}

func ActivateWorkspaceTab(wf workspacesFile, id string) (workspacesFile, *WorkspaceTab) {
	for i, t := range wf.Tabs {
		if t.ID == id {
			wf.Tabs[i].LastUsedAt = time.Now().UTC()
			wf.ActiveWorkspaceID = id
			_ = SaveWorkspaces(wf)
			_ = config.SaveWorkspace(t.Path)
			tab := wf.Tabs[i]
			return wf, &tab
		}
	}
	return wf, nil
}

func NextTabID(wf workspacesFile, delta int) string {
	if len(wf.Tabs) == 0 {
		return ""
	}
	idx := 0
	for i, t := range wf.Tabs {
		if t.ID == wf.ActiveWorkspaceID {
			idx = i
			break
		}
	}
	idx = (idx + delta + len(wf.Tabs)) % len(wf.Tabs)
	return wf.Tabs[idx].ID
}
