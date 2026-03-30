# 📖 Runbook de Operações

Guia de resposta rápida para incidentes e manutenção.

### 1. Comandos de Emergência
* **Verificar Saúde Total:** `http://localhost:8000/healthz/`
* **Logs em Tempo Real:** Aceder ao Dozzle em `http://localhost:8888`
* **Reiniciar apenas o Worker (Se as tarefas travarem):**
  ```bash
  docker compose restart worker