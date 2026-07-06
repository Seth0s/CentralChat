# Postgres 16 + pgvector para ambiente de testes / dev local (Central).
# Extensões aplicadas no primeiro arranque via /docker-entrypoint-initdb.d/.
FROM pgvector/pgvector:pg16-bookworm

COPY init/ /docker-entrypoint-initdb.d/
