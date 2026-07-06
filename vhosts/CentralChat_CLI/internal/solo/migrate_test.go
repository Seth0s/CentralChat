package solo

import (
	"testing"
)

func TestMigrateAndCRUD(t *testing.T) {
	db, err := DB()
	if err != nil {
		t.Fatalf("DB(): %v", err)
	}
	defer func() {
		db.Close()
		db = nil  // reset package-level var
	}()

	// Verify tables exist
	tables := []string{"sessions", "messages", "memory", "audit", "work_items"}
	for _, name := range tables {
		var count int
		err := db.QueryRow(
			"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
			name,
		).Scan(&count)
		if err != nil {
			t.Errorf("check table %s: %v", name, err)
		} else if count == 0 {
			t.Errorf("table %s missing", name)
		} else {
			t.Logf("table %s exists", name)
		}
	}

	// Verify FTS5 if available
	if fts5Available {
		t.Log("FTS5 is available")
		var count int
		db.QueryRow(
			"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='messages_fts'",
		).Scan(&count)
		if count == 0 {
			t.Error("FTS5 table missing despite flag")
		}
	} else {
		t.Log("FTS5 not available (LIKE fallback active)")
	}
}
