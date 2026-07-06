package ui

import (
	"os"
	"path/filepath"
	"strings"
)

type localAgent struct {
	Name        string
	Description string
}

type localSkill struct {
	Name        string
	Description string
}

// loadLocalAgents returns agents available in SOLO mode.
// For now returns default agent; future: read from ~/.config/central/agents.yaml.
func loadLocalAgents() []localAgent {
	return []localAgent{
		{Name: "default", Description: "Default local agent"},
	}
}

// loadLocalSkills reads skill markdown files from ~/.config/central/skills/.
func loadLocalSkills() []localSkill {
	dir, _ := os.UserConfigDir()
	entries, err := os.ReadDir(filepath.Join(dir, "central", "skills"))
	if err != nil {
		return nil
	}

	var skills []localSkill
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		name := strings.TrimSuffix(e.Name(), ".md")
		skills = append(skills, localSkill{Name: name, Description: "Skill: " + e.Name()})
	}
	return skills
}
