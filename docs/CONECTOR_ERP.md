# Conector de ERP jurídico (CAD-167)

Conector **declarativo**: cada ERP é um conjunto de *operações* (método, caminho, mapeamento de campos) guardado como dado,
não como código. O modelo do **Projuris** (`erp/presets.py`) é um ponto de partida — **[VALIDAR]** todos os caminhos/campos
e o método de autenticação com o fornecedor/contrato antes de ativar. Quem corrige é o dono/admin (campo `operations`), sem deploy.

## Segurança
- Nasce **só simulação** (`live_enabled=false`). Simular nunca sai da rede: mostra o pedido exato (sem token).
- Ativar execução real: dono/administrador (`PATCH /api/v1/erp/connectors/<id>/ {"live_enabled": true}`), auditado.
- Operação que **altera** o ERP exige `confirm: true` (decisão humana, R4) além de `live_enabled`. Perfil leitura só simula.
- Caminho sempre relativo à URL base (sem trocar de host), parâmetros codificados, HTTPS, SSRF validado, sem redirecionamento,
  timeout 20 s, resposta ≤ 1 MB. Token cifrado em repouso e write-only. Chamadas reais vão à trilha (`integration.call`) e a `ErpCallLog`.

## Uso
1. `POST /api/v1/erp/connectors/` `{name, preset:"PROJURIS", base_url, token, operations?}`
2. `POST .../run/` `{operation:"criar_tarefa", data:{titulo:"..."}}` → simulação (padrão).
3. Após conferir: ativar `live_enabled` e `POST .../run/` com `dry_run:false, confirm:true`.

## Próximos passos
Validar Projuris (e Astrea) com credenciais de teste; ligar operações a tarefas/andamentos do Cadrius (sincronização) e à matriz de
autonomia (R3 com aprovação do advogado).
