-- M4.5 — Agent icon (emoji) field
-- Adiciona coluna icon para ícone visual do agente no chat
ALTER TABLE user_agents ADD COLUMN IF NOT EXISTS icon TEXT NOT NULL DEFAULT '';
