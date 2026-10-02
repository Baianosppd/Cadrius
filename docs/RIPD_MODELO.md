# Relatório de Impacto à Proteção de Dados Pessoais (RIPD) — Modelo

> LGPD art. 5º, XVII e art. 38 · ISO/IEC 27701 7.2.5. **Modelo a ser preenchido e assinado** pelo encarregado (DPO) e pela
> direção. O tratamento por IA de conteúdo processual (podendo incluir dados sensíveis e dados de terceiros) é de **alto risco**
> e exige RIPD antes de uso comercial em escala. Esta primeira versão já traz o mapeamento técnico; o parecer é do DPO.

| Campo | Conteúdo |
|---|---|
| Controlador / Operador | Cadrius (controlador dos dados dos usuários; operador dos dados dos escritórios) |
| Encarregado (DPO) | _nome, contato (PRIVACY_CONTACT_EMAIL)_ |
| Versão / data / responsável | _v1.0 · __/__/____ · __________ _ |

## 1. Descrição do tratamento
Ver **RoPA** (`/security-center/ropa/`, `compliance/ropa.py`): 9 operações (PA-01 … PA-09). Operações de maior risco:
PA-03 (e-mails IMAP), PA-04 (IA), PA-05 (envio de mensagens), PA-08 (backups).

## 2. Necessidade e proporcionalidade
| Pergunta | Resposta técnica atual | Parecer do DPO |
|---|---|---|
| A finalidade é legítima e específica? | Triagem de intimações, extração de prazos, comunicação com clientes | |
| Os dados são o mínimo necessário? | Trilha sem conteúdo; IA recebe até 20 mil caracteres; payload expurgado em 90 dias | |
| Base legal por operação? | RoPA (execução de contrato; legítimo interesse; obrigação legal; definida pelo controlador p/ dados de terceiros) | |
| Há dados sensíveis (art. 11)? | Possível em conteúdo processual (saúde, vida sexual, convicção…) — **avaliar** | |
| Qualidade/exatidão | Validação por Pydantic + revisão humana | |

## 3. Riscos identificados (probabilidade × impacto)
| # | Risco | P | I | Medidas existentes | Risco residual | Ação |
|---|---|---|---|---|---|---|
| R1 | Vazamento entre escritórios | B | A | Isolamento por tenant + testes de vazamento | Baixo | Pentest |
| R2 | Envio de conteúdo a provedor de IA no exterior sem base | M | A | Política por escritório, aviso de IA, DPA, kill switch | Médio | Formalizar DPAs (art. 33) |
| R3 | Decisão/ação automática incorreta (alucinação, prompt injection) | M | A | Humano no circuito, rascunho inativo, delimitação do texto, validação da saída | Médio | Monitorar taxa de rejeição |
| R4 | Acesso indevido por conta comprometida | M | A | Rate limit, bloqueio, anomalias, trilha imutável | Médio | **MFA** (CAD-083) |
| R5 | Vazamento de credenciais de integração | B | A | Cifra Fernet + rotação de chave | Baixo | Cofre de segredos |
| R6 | Retenção além do necessário | M | M | `enforce_retention` agendado | Baixo | Revisar prazos |
| R7 | Incidente sem comunicação à ANPD no prazo | B | A | Alertas + runbook | Médio | Treinar equipe; simulação |
| R8 | Backup exposto | B | A | Dump cifrado antes do upload | Baixo | Teste de restauração |

## 4. Medidas, salvaguardas e mecanismos de mitigação
Ver `docs/AUDITORIA_SEGURANCA.md` e o **Centro de Segurança** (`/security-center/`): controles ISO 27001/27701 e LGPD com evidências.

## 5. Parecer e aprovação
| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Encarregado (DPO) | | | |
| Direção | | | |
| Revisão jurídica | | | |
