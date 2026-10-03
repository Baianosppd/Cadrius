# ⚖️ Cadrius AI — Hiperautomação Jurídica

Plataforma SaaS B2B que captura eventos (e-mails, webhooks), extrai dados com IA (sob governança) e executa ações em sistemas externos
(WhatsApp, Trello, webhooks…) para escritórios de advocacia — com **trilha de auditoria imutável**, **LGPD** e controles **ISO 27001/27701**.

## Arquitetura (resumo)
`React (repo separado) → Traefik (TLS) → Django/DRF (uvicorn) ⇄ Postgres · Redis ⇄ Worker Django-Q → IA / WhatsApp / webhooks`.
Apps de domínio: `accounts` `billing` `emails` `extraction` `integrations` `tasks` `workflows` `webhooks`.
Apps de governança: **`audit`** (trilha + anomalias) · **`privacy`** (termos, consentimento, DSR, retenção) · **`aigov`** (política e guarda de IA) ·
**`compliance`** (Centro de Segurança, ISO 27001/27701, LGPD, RoPA). Detalhes: `docs/architecture.md`.

## Desenvolvimento
```bash
cp .env.example .env            # preencha DJANGO_SECRET_KEY/ENCRYPTION_KEY (comandos no próprio arquivo)
docker compose up --build -d    # carrega docker-compose.yml + docker-compose.override.yml (dev)
```
* API: `http://localhost:8000` · Swagger: `/api/docs/` · Admin: `/admin/` · **Centro de Segurança: `/security-center/`** (usuário *staff*)
* Painel do Traefik: `http://localhost:8090` (só local) · Túnel para webhooks: `docker compose --profile tunnel up` (requer `NGROK_AUTHTOKEN`)
* Logs: Dozzle em `http://$DOZZLE_HOST` (Traefik + BasicAuth — `DOZZLE_HOST`/`DOZZLE_BASIC_AUTH`)
* Criar superusuário: `docker compose exec web python manage.py createsu` (variáveis `DJANGO_SUPERUSER_*`)
* Agendar rotinas de segurança/privacidade (uma vez): `docker compose exec web python manage.py setup_security_schedules`

## Testes e qualidade
```bash
python manage.py test                         # 150 testes (SQLite). Com Postgres: DATABASE_URL=postgres://…
coverage run manage.py test && coverage report --fail-under=75
flake8 . --select=E9,F --exclude='*/migrations/*' ; bandit -r . --severity-level medium -x ./scripts,'*/tests*'
pip-audit -r requirements.txt --require-hashes
```
Dependências: edite `requirements.in` e gere o `requirements.txt` pinado com hashes: `pip-compile --generate-hashes --strip-extras requirements.in`.

## Produção
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (TLS Let's Encrypt, HSTS, sem portas administrativas).
O deploy é automático em push na `main` **somente após o CI** (`.github/workflows/deploy.yml`), com *smoke test* em `/readyz/` e rollback.
Secrets exigidos: ver `docs/AUDITORIA_SEGURANCA.md` §4. A aplicação **recusa subir** em produção sem `DJANGO_SECRET_KEY`, `ENCRYPTION_KEY` e `EVOLUTION_API_KEY`.

## Documentação
`docs/ANALISE_PROJETO.md` (análise completa) · `docs/PLANO_EQUIPES.md` (Front/Design/Back) · `docs/CADS_BACKLOG.md` (cards) ·
`docs/AUDITORIA_SEGURANCA.md` · `docs/SECURITY.md` · `docs/runbook.md` (operação e incidentes) · `docs/RIPD_MODELO.md` · `docs/PLANO_AUDITORIA_LGPD.md`.

## Equipe
Jullio Cesar — DevSecOps & Tech Lead · Thales — Back-end · Ryan — Front-end · Allan — Design UX/UI
