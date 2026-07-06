// Package solo — SQLite-backed local storage for SOLO mode.
package solo

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// ── Database ────────────────────────────────────────────────────

var db *sql.DB

// fts5Available is true when the SQLite was compiled with FTS5 support.
var fts5Available bool

// Prepared statements (initialized in DB())
var (
	stmtInsertMsg     *sql.Stmt
	stmtUpdateSession *sql.Stmt
	stmtInsertMemory  *sql.Stmt
	stmtInsertAudit   *sql.Stmt
)

// DB returns the shared SQLite database, initializing it if needed.
func DB() (*sql.DB, error) {
	if db != nil {
		return db, nil
	}
	dir, err := configDir()
	if err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "central.db")
	d, err := sql.Open("sqlite3", path+"?_journal_mode=WAL&_busy_timeout=5000")
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}
	d.SetMaxOpenConns(1)
	if err := migrate(d); err != nil {
		d.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}
	// Prepare reusable statements
	stmtInsertMsg, _ = d.Prepare("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)")
	stmtUpdateSession, _ = d.Prepare("UPDATE sessions SET updated_at=datetime('now') WHERE id=?")
	stmtInsertMemory, _ = d.Prepare("INSERT INTO memory (content) VALUES (?)")
	stmtInsertAudit, _ = d.Prepare("INSERT INTO audit (event, details) VALUES (?, ?)")
	db = d
	return db, nil
}

func migrate(d *sql.DB) error {
	// Core tables — always created
	_, err := d.Exec(`
		CREATE TABLE IF NOT EXISTS sessions (
			id         TEXT PRIMARY KEY,
			title      TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		);
		CREATE TABLE IF NOT EXISTS messages (
			id         INTEGER PRIMARY KEY AUTOINCREMENT,
			session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
			role       TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
			content    TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		);
		CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
		
		CREATE TABLE IF NOT EXISTS memory (
			id         INTEGER PRIMARY KEY AUTOINCREMENT,
			content    TEXT NOT NULL,
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		);
		
		CREATE TABLE IF NOT EXISTS audit (
			id         INTEGER PRIMARY KEY AUTOINCREMENT,
			event      TEXT NOT NULL,
			details    TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		);
		CREATE INDEX IF NOT EXISTS idx_audit_event ON audit(event);
		CREATE INDEX IF NOT EXISTS idx_audit_created ON audit(created_at);
		
		-- Work queue (local tasks)
		CREATE TABLE IF NOT EXISTS work_items (
			id         TEXT PRIMARY KEY,
			title      TEXT NOT NULL DEFAULT '',
			status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','done','cancelled')),
			priority   TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
			context    TEXT NOT NULL DEFAULT '',  -- files, history refs, skill names
			created_at TEXT NOT NULL DEFAULT (datetime('now')),
			updated_at TEXT NOT NULL DEFAULT (datetime('now'))
		);
		CREATE TABLE IF NOT EXISTS work_item_comments (
			id           INTEGER PRIMARY KEY AUTOINCREMENT,
			work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
			body         TEXT NOT NULL DEFAULT '',
			created_at   TEXT NOT NULL DEFAULT (datetime('now'))
		);
		CREATE INDEX IF NOT EXISTS idx_wic_work_item ON work_item_comments(work_item_id);
	`)
	if err != nil {
		return fmt.Errorf("core migration: %w", err)
	}

	// FTS5 — optional; graceful fallback if not compiled in
	if err := migrateFTS5(d); err != nil {
		// Logged to stderr so user knows search will use LIKE fallback
		fmt.Fprintf(os.Stderr, "solo: FTS5 not available, session search will use LIKE fallback (%v)\n", err)
	}

	_, err = d.Exec(`
		PRAGMA journal_mode=WAL;
		PRAGMA foreign_keys=ON;
	`)
	return err
}

func migrateFTS5(d *sql.DB) error {
	_, err := d.Exec(`
		CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
			content, content='messages', content_rowid='id'
		);
	`)
	if err != nil {
		return err
	}
	fts5Available = true

	// Triggers to keep FTS in sync
	_, err = d.Exec(`
		CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
			INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
		END;
		CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
			INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
		END;
		CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
			INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
			INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
		END;
	`)
	return err
}

func CloseDB() {
	if db != nil {
		db.Close()
		db = nil
	}
}

// ── Sessions ────────────────────────────────────────────────────

type SessionEntry struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type SessionMeta struct {
	ID           string    `json:"id"`
	Title        string    `json:"title"`
	MessageCount int       `json:"message_count"`
	UpdatedAt    time.Time `json:"updated_at"`
}

func CreateSession(title string) (string, error) {
	d, err := DB()
	if err != nil {
		return "", err
	}
	id := fmt.Sprintf("solo-%d", time.Now().UnixMilli())
	_, err = d.Exec("INSERT INTO sessions (id, title) VALUES (?, ?)", id, title)
	return id, err
}

func LoadSession(sessionID string) ([]SessionEntry, error) {
	d, err := DB()
	if err != nil {
		return nil, err
	}
	rows, err := d.Query(
		"SELECT role, content FROM messages WHERE session_id=? ORDER BY id ASC", sessionID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var entries []SessionEntry
	for rows.Next() {
		var e SessionEntry
		if err := rows.Scan(&e.Role, &e.Content); err != nil {
			continue
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

func AppendTurn(sessionID, userText, assistantText string) error {
	d, err := DB()
	if err != nil {
		return err
	}
	tx, err := d.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	txStmtInsertMsg := tx.Stmt(stmtInsertMsg)
	txStmtUpdateSession := tx.Stmt(stmtUpdateSession)

	if _, err := txStmtInsertMsg.Exec(sessionID, "user", userText); err != nil {
		return err
	}
	if assistantText != "" {
		if _, err := txStmtInsertMsg.Exec(sessionID, "assistant", assistantText); err != nil {
			return err
		}
	}
	if _, err := txStmtUpdateSession.Exec(sessionID); err != nil {
		return err
	}
	return tx.Commit()
}

func ListSessions() ([]SessionMeta, error) {
	d, err := DB()
	if err != nil {
		return nil, err
	}

	// Clean up empty sessions (created but never used)
	d.Exec("DELETE FROM sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM messages)")

	rows, err := d.Query(`
		SELECT s.id, s.title, COUNT(m.id) as msg_count, s.updated_at
		FROM sessions s
		LEFT JOIN messages m ON m.session_id = s.id
		GROUP BY s.id
		HAVING COUNT(m.id) > 0
		ORDER BY s.updated_at DESC
		LIMIT 100
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var sessions []SessionMeta
	for rows.Next() {
		var m SessionMeta
		var updatedStr string
		if err := rows.Scan(&m.ID, &m.Title, &m.MessageCount, &updatedStr); err != nil {
			continue
		}
		m.UpdatedAt, _ = time.Parse("2006-01-02 15:04:05", updatedStr)
		if m.Title == "" && m.MessageCount > 0 {
			// Get first user message as title
			var firstMsg string
			d.QueryRow(
				"SELECT content FROM messages WHERE session_id=? AND role='user' ORDER BY id LIMIT 1",
				m.ID,
			).Scan(&firstMsg)
			m.Title = truncateStr(firstMsg, 80)
		}
		if m.Title == "" {
			m.Title = "(empty)"
		}
		sessions = append(sessions, m)
	}
	return sessions, rows.Err()
}

func DeleteSession(sessionID string) error {
	d, err := DB()
	if err != nil {
		return err
	}
	_, err = d.Exec("DELETE FROM sessions WHERE id=?", sessionID)
	return err
}

// ── Memory ──────────────────────────────────────────────────────

type MemoryItem struct {
	Content   string `json:"content"`
	CreatedAt string `json:"created_at"`
}

type MemoryStore struct {
	Facts []MemoryItem `json:"facts"`
}

func LoadMemory() (*MemoryStore, error) {
	d, err := DB()
	if err != nil {
		return nil, err
	}
	rows, err := d.Query("SELECT content, created_at FROM memory ORDER BY id DESC LIMIT 100")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var m MemoryStore
	for rows.Next() {
		var item MemoryItem
		if err := rows.Scan(&item.Content, &item.CreatedAt); err != nil {
			continue
		}
		m.Facts = append(m.Facts, item)
	}
	return &m, rows.Err()
}

func AddMemoryFact(content string) error {
	if stmtInsertMemory == nil {
		if _, err := DB(); err != nil {
			return err
		}
	}
	_, err := stmtInsertMemory.Exec(strings.TrimSpace(content))
	return err
}

// ListMemory returns recent memory entries.
func ListMemory() ([]string, error) {
	d, err := DB()
	if err != nil {
		return nil, err
	}
	rows, err := d.Query("SELECT content FROM memory ORDER BY id DESC LIMIT 20")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var entries []string
	for rows.Next() {
		var content string
		if err := rows.Scan(&content); err != nil {
			continue
		}
		entries = append(entries, content)
	}
	return entries, rows.Err()
}

// ── Audit ───────────────────────────────────────────────────────

func AppendAudit(event string, details map[string]any) error {
	if stmtInsertAudit == nil {
		if _, err := DB(); err != nil {
			return err
		}
	}
	detailsJSON := "{}"
	if details != nil {
		b, _ := jsonMarshal(details)
		detailsJSON = string(b)
	}
	_, err := stmtInsertAudit.Exec(event, detailsJSON)
	return err
}

func jsonMarshal(v any) ([]byte, error) {
	// Avoid import cycle — use fmt.Sprintf for simple maps
	var parts []string
	for k, val := range v.(map[string]any) {
		parts = append(parts, fmt.Sprintf(`"%s":"%v"`, k, val))
	}
	return []byte("{" + strings.Join(parts, ",") + "}"), nil
}

// ── Session search (FTS5) ──────────────────────────────────────

func SearchSessions(query string, limit int) ([]SessionEntry, error) {
	d, err := DB()
	if err != nil {
		return nil, err
	}

	if !fts5Available {
		return searchSessionsLike(d, query, limit)
	}

	rows, err := d.Query(`
		SELECT m.role, m.content
		FROM messages_fts fts
		JOIN messages m ON m.id = fts.rowid
		WHERE messages_fts MATCH ?
		ORDER BY rank
		LIMIT ?
	`, query, limit)
	if err != nil {
		// If FTS query syntax error, fall back to LIKE
		return searchSessionsLike(d, query, limit)
	}
	defer rows.Close()

	var entries []SessionEntry
	for rows.Next() {
		var e SessionEntry
		if err := rows.Scan(&e.Role, &e.Content); err != nil {
			continue
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

func searchSessionsLike(d *sql.DB, query string, limit int) ([]SessionEntry, error) {
	pattern := "%" + query + "%"
	rows, err := d.Query(`
		SELECT role, content FROM messages
		WHERE content LIKE ? 
		ORDER BY id DESC
		LIMIT ?
	`, pattern, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var entries []SessionEntry
	for rows.Next() {
		var e SessionEntry
		if err := rows.Scan(&e.Role, &e.Content); err != nil {
			continue
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

// ── Work Queue (local) ──────────────────────────────────────────

type WorkItem struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	Status    string `json:"status"`
	Priority  string `json:"priority"`
	Context   string `json:"context"`
	CreatedAt string `json:"created_at"`
	UpdatedAt string `json:"updated_at"`
}

func AddWorkItem(title, priority, context string) (*WorkItem, error) {
	d, err := DB()
	if err != nil {
		return nil, err
	}
	id := fmt.Sprintf("WI-%d", time.Now().UnixMilli())
	_, err = d.Exec(
		"INSERT INTO work_items (id, title, priority, context) VALUES (?, ?, ?, ?)",
		id, title, priority, context,
	)
	if err != nil {
		return nil, err
	}
	return &WorkItem{ID: id, Title: title, Status: "open", Priority: priority, Context: context}, nil
}

func ListWorkItems(status string) ([]WorkItem, error) {
	d, err := DB()
	if err != nil {
		return nil, err
	}
	query := "SELECT id, title, status, priority, context, created_at, updated_at FROM work_items"
	args := []any{}
	if status != "" {
		query += " WHERE status = ?"
		args = append(args, status)
	}
	query += " ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, created_at DESC LIMIT 50"
	rows, err := d.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var items []WorkItem
	for rows.Next() {
		var wi WorkItem
		if err := rows.Scan(&wi.ID, &wi.Title, &wi.Status, &wi.Priority, &wi.Context, &wi.CreatedAt, &wi.UpdatedAt); err != nil {
			continue
		}
		items = append(items, wi)
	}
	return items, rows.Err()
}

func UpdateWorkItemStatus(id, status string) error {
	d, err := DB()
	if err != nil {
		return err
	}
	_, err = d.Exec("UPDATE work_items SET status=?, updated_at=datetime('now') WHERE id=?", status, id)
	return err
}

func DeleteWorkItem(id string) error {
	d, err := DB()
	if err != nil {
		return err
	}
	_, err = d.Exec("DELETE FROM work_items WHERE id=?", id)
	return err
}

func AddWorkItemComment(workItemID, body string) error {
	d, err := DB()
	if err != nil {
		return err
	}
	_, err = d.Exec("INSERT INTO work_item_comments (work_item_id, body) VALUES (?, ?)", workItemID, body)
	return err
}

// ── Old JSON fallback (for migration) ───────────────────────────

func migrateFromJSONL() {
	// Check if old sessions directory exists with JSONL files
	dir, err := configDir()
	if err != nil {
		return
	}
	oldDir := filepath.Join(dir, "sessions")
	entries, err := os.ReadDir(oldDir)
	if err != nil {
		return
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".jsonl") {
			continue
		}
		sid := strings.TrimSuffix(e.Name(), ".jsonl")
		// Check if already in SQLite
		d, err := DB()
		if err != nil {
			return
		}
		var exists int
		d.QueryRow("SELECT COUNT(*) FROM sessions WHERE id=?", sid).Scan(&exists)
		if exists > 0 {
			continue
		}
		// Read JSONL and migrate
		data, err := os.ReadFile(filepath.Join(oldDir, e.Name()))
		if err != nil {
			continue
		}
		_, _ = d.Exec("INSERT INTO sessions (id, title) VALUES (?, '')", sid)
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			// Parse simple JSON: {"role":"user","content":"..."}
			role := extractJSONField(line, "role")
			content := extractJSONField(line, "content")
			if role != "" && content != "" {
				_, _ = d.Exec(
					"INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
					sid, role, content,
				)
			}
		}
		// Remove old file after successful migration
		os.Remove(filepath.Join(oldDir, e.Name()))
	}
}

func truncateStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}

func extractJSONField(line, field string) string {
	// Simple extraction: "field":"value"
	search := `"` + field + `":"`
	idx := strings.Index(line, search)
	if idx < 0 {
		return ""
	}
	start := idx + len(search)
	end := strings.Index(line[start:], `"`)
	if end < 0 {
		return ""
	}
	return line[start : start+end]
}
