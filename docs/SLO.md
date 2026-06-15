# SLO — CentralChat API (D2.6)

| Serviço | SLO | Janela | Medição |
|---------|-----|--------|---------|
| API HTTP | **99.5%** sucesso (não-5xx) | 30d | `central_http_requests_total` |
| Assistant stream | **98%** conclusão sem erro | 30d | `central_streams_total{status}` |
| Break-glass alerta | **&lt; 60s** | evento | webhook Slack + genérico |
| SIEM críticos | entrega ou dead-letter visível | 24h | `central_siem_outbox_dead_total` |

## Error budget

- API: 0.5% → ~3.6 h/mês de 5xx aceitável
- Streams: 2% → monitorizar `CentralChatStreamErrors` em `deploy/prometheus/alerts.yml`

## Dashboard

Importar `deploy/grafana/centralchat-dashboard.json`.
