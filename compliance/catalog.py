"""Catálogo de controles: ISO/IEC 27001:2022 (Anexo A, 93), ISO/IEC 27701:2019 (PIMS) e LGPD (Lei 13.709/2018).

Cada controle pode ter verificações AUTOMÁTICAS (nomes em ``compliance.checks.CHECKS``) que olham a
configuração e os dados reais do sistema em execução. Controles sem verificação automática
(organizacionais/físicos: política assinada, treinamento, contratos…) são avaliados manualmente
(``ControlAssessment``) com responsável e evidência.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Control:
    framework: str
    id: str
    theme: str
    title: str
    checks: tuple = ()
    evidence: str = ''           # onde o sistema atende / o que um auditor deve ver
    manual_hint: str = ''        # o que precisa ser evidenciado manualmente


FRAMEWORKS = {
    'iso27001': 'ISO/IEC 27001:2022 — Anexo A',
    'iso27701': 'ISO/IEC 27701:2019 — Gestão de privacidade (PIMS)',
    'lgpd': 'LGPD — Lei 13.709/2018',
}

# ----------------------------------------------------------------------------- ISO 27001:2022 Anexo A
_ORG = 'Controles organizacionais'
_PEOPLE = 'Controles de pessoas'
_PHYS = 'Controles físicos'
_TECH = 'Controles tecnológicos'

_ISO27001 = [
    # 5 — Organizacionais
    ('5.1', _ORG, 'Políticas de segurança da informação'), ('5.2', _ORG, 'Papéis e responsabilidades de segurança da informação'),
    ('5.3', _ORG, 'Segregação de funções'), ('5.4', _ORG, 'Responsabilidades da direção'),
    ('5.5', _ORG, 'Contato com autoridades'), ('5.6', _ORG, 'Contato com grupos de interesse especial'),
    ('5.7', _ORG, 'Inteligência de ameaças'), ('5.8', _ORG, 'Segurança da informação no gerenciamento de projetos'),
    ('5.9', _ORG, 'Inventário de informações e outros ativos associados'), ('5.10', _ORG, 'Uso aceitável de informações e ativos'),
    ('5.11', _ORG, 'Devolução de ativos'), ('5.12', _ORG, 'Classificação das informações'),
    ('5.13', _ORG, 'Rotulagem de informações'), ('5.14', _ORG, 'Transferência de informações'),
    ('5.15', _ORG, 'Controle de acesso'), ('5.16', _ORG, 'Gestão de identidade'),
    ('5.17', _ORG, 'Informações de autenticação'), ('5.18', _ORG, 'Direitos de acesso'),
    ('5.19', _ORG, 'Segurança da informação nas relações com fornecedores'),
    ('5.20', _ORG, 'Segurança da informação nos acordos com fornecedores'),
    ('5.21', _ORG, 'Segurança da informação na cadeia de suprimentos de TIC'),
    ('5.22', _ORG, 'Monitoramento e gestão de mudanças dos serviços de fornecedores'),
    ('5.23', _ORG, 'Segurança da informação para uso de serviços em nuvem'),
    ('5.24', _ORG, 'Planejamento e preparação da gestão de incidentes'), ('5.25', _ORG, 'Avaliação e decisão sobre eventos de segurança'),
    ('5.26', _ORG, 'Resposta a incidentes de segurança da informação'), ('5.27', _ORG, 'Aprendizado com incidentes'),
    ('5.28', _ORG, 'Coleta de evidências'), ('5.29', _ORG, 'Segurança da informação durante a disrupção'),
    ('5.30', _ORG, 'Prontidão de TIC para continuidade de negócios'),
    ('5.31', _ORG, 'Requisitos legais, estatutários, regulamentares e contratuais'),
    ('5.32', _ORG, 'Direitos de propriedade intelectual'), ('5.33', _ORG, 'Proteção de registros'),
    ('5.34', _ORG, 'Privacidade e proteção de dados pessoais (DP)'),
    ('5.35', _ORG, 'Análise crítica independente da segurança da informação'),
    ('5.36', _ORG, 'Conformidade com políticas, regras e normas'), ('5.37', _ORG, 'Procedimentos operacionais documentados'),
    # 6 — Pessoas
    ('6.1', _PEOPLE, 'Seleção'), ('6.2', _PEOPLE, 'Termos e condições de contratação'),
    ('6.3', _PEOPLE, 'Conscientização, educação e treinamento em segurança'), ('6.4', _PEOPLE, 'Processo disciplinar'),
    ('6.5', _PEOPLE, 'Responsabilidades após encerramento ou mudança da contratação'),
    ('6.6', _PEOPLE, 'Acordos de confidencialidade ou não divulgação'), ('6.7', _PEOPLE, 'Trabalho remoto'),
    ('6.8', _PEOPLE, 'Relato de eventos de segurança da informação'),
    # 7 — Físicos
    ('7.1', _PHYS, 'Perímetros de segurança física'), ('7.2', _PHYS, 'Entrada física'),
    ('7.3', _PHYS, 'Segurança de escritórios, salas e instalações'), ('7.4', _PHYS, 'Monitoramento de segurança física'),
    ('7.5', _PHYS, 'Proteção contra ameaças físicas e ambientais'), ('7.6', _PHYS, 'Trabalho em áreas seguras'),
    ('7.7', _PHYS, 'Mesa limpa e tela limpa'), ('7.8', _PHYS, 'Localização e proteção de equipamentos'),
    ('7.9', _PHYS, 'Segurança de ativos fora das instalações'), ('7.10', _PHYS, 'Mídias de armazenamento'),
    ('7.11', _PHYS, 'Serviços de infraestrutura'), ('7.12', _PHYS, 'Segurança do cabeamento'),
    ('7.13', _PHYS, 'Manutenção de equipamentos'), ('7.14', _PHYS, 'Descarte seguro ou reutilização de equipamentos'),
    # 8 — Tecnológicos
    ('8.1', _TECH, 'Dispositivos endpoint do usuário'), ('8.2', _TECH, 'Direitos de acesso privilegiado'),
    ('8.3', _TECH, 'Restrição de acesso à informação'), ('8.4', _TECH, 'Acesso ao código-fonte'),
    ('8.5', _TECH, 'Autenticação segura'), ('8.6', _TECH, 'Gestão de capacidade'),
    ('8.7', _TECH, 'Proteção contra malware'), ('8.8', _TECH, 'Gestão de vulnerabilidades técnicas'),
    ('8.9', _TECH, 'Gestão de configuração'), ('8.10', _TECH, 'Exclusão de informações'),
    ('8.11', _TECH, 'Mascaramento de dados'), ('8.12', _TECH, 'Prevenção de vazamento de dados'),
    ('8.13', _TECH, 'Backup das informações'), ('8.14', _TECH, 'Redundância dos recursos de processamento'),
    ('8.15', _TECH, 'Log (registro de eventos)'), ('8.16', _TECH, 'Atividades de monitoramento'),
    ('8.17', _TECH, 'Sincronização do relógio'), ('8.18', _TECH, 'Uso de programas utilitários privilegiados'),
    ('8.19', _TECH, 'Instalação de software em sistemas operacionais'), ('8.20', _TECH, 'Segurança de redes'),
    ('8.21', _TECH, 'Segurança dos serviços de rede'), ('8.22', _TECH, 'Segregação de redes'),
    ('8.23', _TECH, 'Filtragem da web'), ('8.24', _TECH, 'Uso de criptografia'),
    ('8.25', _TECH, 'Ciclo de vida de desenvolvimento seguro'), ('8.26', _TECH, 'Requisitos de segurança da aplicação'),
    ('8.27', _TECH, 'Princípios de arquitetura e engenharia de sistemas seguros'), ('8.28', _TECH, 'Codificação segura'),
    ('8.29', _TECH, 'Testes de segurança em desenvolvimento e aceitação'), ('8.30', _TECH, 'Desenvolvimento terceirizado'),
    ('8.31', _TECH, 'Separação dos ambientes de desenvolvimento, teste e produção'), ('8.32', _TECH, 'Gestão de mudanças'),
    ('8.33', _TECH, 'Informações de teste'), ('8.34', _TECH, 'Proteção de sistemas durante testes de auditoria'),
]

# controle -> (verificações automáticas, evidência no sistema)
_ISO27001_AUTO = {
    '5.1': ((), 'docs/SECURITY.md, docs/AUDITORIA_SEGURANCA.md — falta aprovação formal pela direção (manual).'),
    '5.7': (('dependency_scanning',), 'pip-audit no CI + Dependabot semanal.'),
    '5.9': (('processing_inventory',), 'Registro das operações de tratamento (RoPA) na tela "RoPA".'),
    '5.14': (('transport_security',), 'TLS no Traefik (docker-compose.prod.yml), HSTS e cookies Secure.'),
    '5.15': (('rbac', 'tenant_isolation'), 'RBAC por cargo (OrgRolePermission) e isolamento por escritório (TenantQuerysetMixin).'),
    '5.16': (('sso_verified_email', 'email_verification'), 'JWT + SSO com e-mail verificado; verificação de e-mail no cadastro.'),
    '5.17': (('password_policy', 'bruteforce'), 'Validadores de senha, django-axes e rate limit em login/cadastro.'),
    '5.18': (('rbac',), 'Cargos OWNER/ADMIN/MEMBER/VIEWER; revisão periódica de acessos (manual).'),
    '5.19': (('subprocessors',), 'Lista de suboperadores com contrato/DPA verificado.'),
    '5.20': (('subprocessors',), 'DPA com cada suboperador (campo contract_verified).'),
    '5.21': (('dependency_scanning',), 'requirements.txt pinado com hashes; imagem escaneada (Trivy).'),
    '5.23': (('subprocessors', 'readiness'), 'Hospedagem Locaweb + serviços em nuvem listados e avaliados.'),
    '5.24': (('audit_trail', 'security_schedules'), 'Trilha de auditoria + alertas de anomalia; runbook em docs/runbook.md.'),
    '5.25': (('anomaly_detection',), 'Alertas com severidade e fila de triagem (Centro de Segurança → Alertas).'),
    '5.26': (('audit_trail', 'open_critical_alerts'), 'Resposta a alertas críticos; sem alertas críticos/altos abertos há mais de 24 h.'),
    '5.28': (('audit_trail', 'audit_immutable'), 'Eventos imutáveis, encadeados por hash e exportáveis em CSV (evidência).'),
    '5.29': (('backup',), 'Backups diários cifrados + restauro documentado.'),
    '5.30': (('backup', 'readiness'), 'Healthchecks, restart automático e backups.'),
    '5.31': (('legal_docs', 'consent_records'), 'Documentos legais versionados e consentimentos comprovados.'),
    '5.33': (('audit_immutable', 'retention_policy'), 'Registros imutáveis com política de retenção.'),
    '5.34': (('legal_docs', 'dsr_sla', 'retention_policy'), 'Módulo de privacidade (termos, consentimento, DSR, retenção).'),
    '5.36': (('ci_pipeline',), 'Pipeline de CI bloqueia merge/deploy com falhas de lint, SAST, CVEs e testes.'),
    '5.37': ((), 'docs/runbook.md e este Centro de Segurança; ampliar procedimentos (manual).'),
    '6.8': (('audit_trail',), 'Eventos e alertas visíveis ao escritório; canal de relato (manual).'),
    '8.2': (('admin_audited', 'mfa'), 'Acesso de staff ao Admin é auditado; MFA para staff recomendado (pendente).'),
    '8.3': (('tenant_isolation', 'rbac'), 'Filtros por organização em todos os viewsets; testes de vazamento entre escritórios.'),
    '8.4': ((), 'Repositórios GitHub privados, branch protegida e revisão de PR (manual).'),
    '8.5': (('bruteforce', 'jwt_revocation', 'mfa'), 'Throttle, bloqueio por IP/usuário, logout com revogação; MFA pendente.'),
    '8.8': (('dependency_scanning',), 'pip-audit bloqueante no CI, Dependabot e Trivy.'),
    '8.9': (('secret_key', 'debug_off', 'hosts', 'encryption_key'), 'A aplicação recusa subir em produção sem segredos/chaves seguras.'),
    '8.10': (('retention_policy',), 'enforce_retention agendado (e-mails 90d, payloads 90d, logs 30d, organizações 30d).'),
    '8.11': (('data_masking',), 'Redação de PII/segredos na trilha e nos logs; e-mail mascarado.'),
    '8.12': (('data_masking', 'ai_governance'), 'IA recebe só o necessário; conteúdo nunca vai à trilha; CSV à prova de injeção.'),
    '8.13': (('backup',), 'db-backup diário + backup_to_supabase cifrado (Fernet).'),
    '8.14': (('readiness',), 'Healthchecks e restart; redundância/HA ainda não implementada (manual).'),
    '8.15': (('audit_trail', 'logging_structured'), 'AuditEvent imutável + logging estruturado com request_id.'),
    '8.16': (('anomaly_detection', 'sentry_privacy'), 'Detectores A1–A12 a cada 5 min, Sentry e Dozzle protegido.'),
    '8.17': (('time_sync',), 'UTC/USE_TZ; NTP do host (manual).'),
    '8.20': (('transport_security',), 'Traefik como único ponto de entrada; DB/Redis em rede interna.'),
    '8.21': (('transport_security',), 'TLS/HSTS e headers de segurança.'),
    '8.22': ((), 'proxy_net x backend_net (docker-compose) — verificar em auditoria de infraestrutura (manual).'),
    '8.24': (('encryption_key', 'credentials_encrypted', 'transport_security'), 'Fernet em repouso para credenciais; TLS em trânsito.'),
    '8.25': (('ci_pipeline',), 'CI com SAST, testes e revisão de PR.'),
    '8.26': (('csp', 'bruteforce', 'tenant_isolation'), 'CSP, rate limit, isolamento por tenant, validação de entrada (SSRF/JSON).'),
    '8.27': (('tenant_isolation', 'rbac', 'ai_governance'), 'Arquitetura com defesa em profundidade (docs/AUDITORIA_SEGURANCA.md).'),
    '8.28': (('ci_pipeline',), 'flake8/bandit no CI; testes de regressão de segurança.'),
    '8.29': (('ci_pipeline',), 'Suíte de testes de segurança (cadrius/tests_security.py) e check --deploy.'),
    '8.31': (('debug_off',), 'Compose de dev separado do de produção; DEBUG desligado em produção.'),
    '8.32': (('ci_pipeline',), 'Deploy só após CI verde, com rollback automático.'),
    '8.33': ((), 'Dados de teste sintéticos; backups reais fora do git (manual).'),
}

# ----------------------------------------------------------------------------- ISO/IEC 27701:2019
_P_CTRL = 'Controlador (7.x)'
_P_PROC = 'Operador (8.x)'
_ISO27701 = [
    ('7.2.1', _P_CTRL, 'Identificar e documentar a finalidade', ('processing_inventory',), 'RoPA com finalidade por tratamento.'),
    ('7.2.2', _P_CTRL, 'Identificar a base legal', ('processing_inventory',), 'RoPA com base legal por tratamento.'),
    ('7.2.3', _P_CTRL, 'Determinar quando e como o consentimento é obtido', ('consent_records',), 'Termos/aceite no cadastro (428 até aceitar).'),
    ('7.2.4', _P_CTRL, 'Obter e registrar o consentimento', ('consent_records',), 'ConsentRecord append-only com hash do texto.'),
    ('7.2.5', _P_CTRL, 'Avaliação de impacto à privacidade (RIPD/DPIA)', ('ripd',), 'Documento RIPD (docs/) — pendente de elaboração/assinatura.'),
    ('7.2.6', _P_CTRL, 'Contratos com operadores de DP', ('subprocessors',), 'DPA com suboperadores (contract_verified).'),
    ('7.2.7', _P_CTRL, 'Controlador conjunto', (), 'Aplicável apenas se houver controladoria conjunta (manual).'),
    ('7.2.8', _P_CTRL, 'Registros relacionados ao tratamento de DP', ('processing_inventory', 'audit_trail'), 'RoPA + trilha de auditoria.'),
    ('7.3.1', _P_CTRL, 'Determinar e cumprir obrigações perante os titulares', ('dsr_sla',), 'Módulo de direitos do titular.'),
    ('7.3.2', _P_CTRL, 'Determinar informações a fornecer aos titulares', ('legal_docs',), 'Termo de Ciência e Política de Privacidade.'),
    ('7.3.3', _P_CTRL, 'Fornecer informações aos titulares', ('legal_docs',), 'API pública de documentos e suboperadores.'),
    ('7.3.4', _P_CTRL, 'Mecanismo para modificar ou retirar o consentimento', ('consent_records',), 'POST /api/v1/legal/consents/ (granted=false).'),
    ('7.3.5', _P_CTRL, 'Mecanismo para contestar o tratamento', ('dsr_sla',), 'Pedidos do titular (tipos variados).'),
    ('7.3.6', _P_CTRL, 'Acesso, correção e/ou eliminação', ('dsr_sla',), 'Exportação, perfil editável e anonimização.'),
    ('7.3.7', _P_CTRL, 'Informar terceiros sobre correção/eliminação', (), 'Processo com suboperadores (manual).'),
    ('7.3.8', _P_CTRL, 'Fornecer cópia dos dados tratados', ('dsr_sla',), 'GET /api/v1/privacy/me/export/.'),
    ('7.3.9', _P_CTRL, 'Tratamento de solicitações', ('dsr_sla',), 'SLA de 15 dias monitorado.'),
    ('7.3.10', _P_CTRL, 'Tomada de decisão automatizada', ('ai_governance', 'ai_human_review'), 'Sem decisão automatizada exclusiva: humano no circuito.'),
    ('7.4.1', _P_CTRL, 'Limitar a coleta', ('data_masking',), 'Coleta restrita aos campos necessários.'),
    ('7.4.2', _P_CTRL, 'Limitar o tratamento', ('ai_governance',), 'Finalidade registrada; IA com política por escritório.'),
    ('7.4.3', _P_CTRL, 'Precisão e qualidade', (), 'Validação por Pydantic e revisão humana (manual).'),
    ('7.4.4', _P_CTRL, 'Objetivos de minimização de DP', ('data_masking', 'retention_policy'), 'Trilha sem conteúdo; retenção curta.'),
    ('7.4.5', _P_CTRL, 'Anonimização e eliminação ao fim do tratamento', ('retention_policy',), 'enforce_retention + anonimização de conta.'),
    ('7.4.6', _P_CTRL, 'Arquivos temporários', (), 'Dumps em diretório temporário 0700 e removidos (manual).'),
    ('7.4.7', _P_CTRL, 'Retenção', ('retention_policy',), 'Prazos configuráveis por settings.'),
    ('7.4.8', _P_CTRL, 'Descarte', ('retention_policy',), 'Expurgo e eliminação de organizações.'),
    ('7.4.9', _P_CTRL, 'Controles de transmissão de DP', ('transport_security',), 'TLS e HSTS.'),
    ('7.5.1', _P_CTRL, 'Base para transferência entre jurisdições', ('subprocessors',), 'Salvaguardas registradas por suboperador.'),
    ('7.5.2', _P_CTRL, 'Países/organizações para os quais a DP pode ser transferida', ('subprocessors',), 'Lista pública de suboperadores com país.'),
    ('7.5.3', _P_CTRL, 'Registros de transferência de DP', ('ai_governance',), 'AIActionLog: provedor e categorias por chamada.'),
    ('7.5.4', _P_CTRL, 'Registros de divulgação a terceiros', ('audit_trail',), 'ai.request/integration.call na trilha.'),
    ('8.2.1', _P_PROC, 'Acordo com o cliente', ('legal_docs',), 'Termos de Uso + cláusula do controlador.'),
    ('8.2.2', _P_PROC, 'Finalidades da organização', ('processing_inventory',), 'RoPA do operador.'),
    ('8.2.3', _P_PROC, 'Uso para marketing e publicidade', (), 'Sem uso de dados de clientes para marketing (declaração, manual).'),
    ('8.2.4', _P_PROC, 'Instrução que infringe a legislação', (), 'Procedimento de recusa (manual).'),
    ('8.2.5', _P_PROC, 'Obrigações do cliente', ('legal_docs',), 'Cláusula de responsabilidade do escritório (controlador).'),
    ('8.2.6', _P_PROC, 'Registros de tratamento', ('processing_inventory', 'audit_trail'), 'RoPA + trilha.'),
    ('8.3.1', _P_PROC, 'Obrigações perante os titulares', ('dsr_sla',), 'Ferramentas de exportação/eliminação para o controlador.'),
    ('8.4.1', _P_PROC, 'Arquivos temporários', (), 'Manual.'),
    ('8.4.2', _P_PROC, 'Devolução, transferência ou descarte de DP', ('retention_policy',), 'Encerramento de organização: 30 dias e eliminação.'),
    ('8.4.3', _P_PROC, 'Controles de transmissão de DP', ('transport_security',), 'TLS.'),
    ('8.5.1', _P_PROC, 'Base para transferência entre jurisdições', ('subprocessors',), 'Salvaguardas por suboperador.'),
    ('8.5.2', _P_PROC, 'Países e organizações de destino', ('subprocessors',), 'Lista pública.'),
    ('8.5.3', _P_PROC, 'Registros de divulgação a terceiros', ('ai_governance',), 'AIActionLog / trilha.'),
    ('8.5.4', _P_PROC, 'Notificação de pedidos de divulgação', (), 'Procedimento jurídico (manual).'),
    ('8.5.5', _P_PROC, 'Divulgações juridicamente vinculantes', (), 'Procedimento jurídico (manual).'),
    ('8.5.6', _P_PROC, 'Divulgação de subcontratados', ('subprocessors',), 'Lista pública de suboperadores.'),
    ('8.5.7', _P_PROC, 'Contratação de subcontratado', ('subprocessors',), 'DPA antes de ativar suboperador.'),
    ('8.5.8', _P_PROC, 'Mudança de subcontratado', ('subprocessors',), 'Nova versão do documento + aviso ao controlador.'),
]

# ----------------------------------------------------------------------------- LGPD
_LGPD_P = 'Princípios (art. 6º)'
_LGPD_D = 'Bases legais e consentimento (arts. 7º–11)'
_LGPD_T = 'Direitos do titular (arts. 17–22)'
_LGPD_G = 'Governança e segurança (arts. 33–50)'
_LGPD = [
    ('6-I', _LGPD_P, 'Finalidade', ('processing_inventory',), 'Finalidades no RoPA e no Termo de Ciência.'),
    ('6-II', _LGPD_P, 'Adequação', ('processing_inventory',), 'Tratamento compatível com a finalidade informada.'),
    ('6-III', _LGPD_P, 'Necessidade (minimização)', ('data_masking', 'retention_policy'), 'Trilha sem conteúdo; retenção curta.'),
    ('6-IV', _LGPD_P, 'Livre acesso', ('dsr_sla',), 'Exportação dos próprios dados.'),
    ('6-V', _LGPD_P, 'Qualidade dos dados', (), 'Perfil editável; revisão humana (manual).'),
    ('6-VI', _LGPD_P, 'Transparência', ('legal_docs', 'subprocessors'), 'Documentos e suboperadores públicos.'),
    ('6-VII', _LGPD_P, 'Segurança', ('secret_key', 'encryption_key', 'credentials_encrypted', 'transport_security', 'bruteforce'), 'Medidas técnicas (ver ISO 27001).'),
    ('6-VIII', _LGPD_P, 'Prevenção', ('anomaly_detection', 'dependency_scanning'), 'Detecção de anomalias e varredura de vulnerabilidades.'),
    ('6-IX', _LGPD_P, 'Não discriminação', (), 'Sem tratamento discriminatório (declaração, manual).'),
    ('6-X', _LGPD_P, 'Responsabilização e prestação de contas', ('audit_trail', 'processing_inventory'), 'Trilha imutável e RoPA.'),
    ('7', _LGPD_D, 'Bases legais documentadas por tratamento', ('processing_inventory',), 'RoPA.'),
    ('8', _LGPD_D, 'Consentimento: forma, prova e revogação', ('consent_records',), 'ConsentRecord com versão/hash; revogação por API.'),
    ('9', _LGPD_D, 'Acesso facilitado às informações sobre o tratamento', ('legal_docs',), 'Endpoints públicos de documentos.'),
    ('11', _LGPD_D, 'Dados sensíveis / processuais sob sigilo', ('ripd',), 'Avaliar no RIPD (conteúdo processual pode conter dados sensíveis).'),
    ('15-16', _LGPD_D, 'Término do tratamento e eliminação', ('retention_policy',), 'enforce_retention e anonimização.'),
    ('18', _LGPD_T, 'Direitos do titular (confirmação, acesso, correção, eliminação, portabilidade, revogação)', ('dsr_sla',), 'Módulo privacy (DSR).'),
    ('19', _LGPD_T, 'Resposta em até 15 dias', ('dsr_sla',), 'due_at = abertura + 15 dias; fila com SLA.'),
    ('20', _LGPD_T, 'Revisão de decisões automatizadas', ('ai_governance', 'ai_human_review'), 'Aprovação humana de workflows e execuções de origem IA.'),
    ('33', _LGPD_G, 'Transferência internacional', ('subprocessors',), 'Países, finalidade e salvaguardas por suboperador.'),
    ('37', _LGPD_G, 'Registro das operações de tratamento (RoPA)', ('processing_inventory',), 'Tela RoPA + exportação CSV.'),
    ('38', _LGPD_G, 'Relatório de impacto (RIPD)', ('ripd',), 'Elaborar com o encarregado (docs/RIPD_MODELO.md).'),
    ('39', _LGPD_G, 'Operador segue instruções do controlador', ('legal_docs',), 'Termos e DPA.'),
    ('41', _LGPD_G, 'Encarregado (DPO) nomeado e canal público', ('dpo_contact',), 'Canal PRIVACY_CONTACT_EMAIL; nomeação formal (manual).'),
    ('42', _LGPD_G, 'Responsabilidade e ressarcimento (contratos)', ('legal_docs',), 'Cláusulas contratuais (revisão jurídica).'),
    ('46', _LGPD_G, 'Medidas de segurança técnicas e administrativas', ('secret_key', 'encryption_key', 'bruteforce', 'audit_immutable', 'rbac'), 'Ver ISO 27001.'),
    ('48', _LGPD_G, 'Comunicação de incidentes à ANPD e titulares', ('audit_trail', 'incident_process'), 'Trilha + alertas; procedimento formal (docs/runbook.md) a completar.'),
    ('49', _LGPD_G, 'Sistemas estruturados para atender à lei', ('audit_trail', 'dsr_sla'), 'Módulos audit/privacy/aigov.'),
    ('50', _LGPD_G, 'Boas práticas e governança', ('ci_pipeline',), 'Programa de governança (este Centro de Segurança).'),
]


def _build() -> dict[str, list[Control]]:
    iso27001 = []
    for cid, theme, title in _ISO27001:
        checks, evidence = _ISO27001_AUTO.get(cid, ((), ''))
        iso27001.append(Control('iso27001', cid, theme, title, tuple(checks), evidence))
    iso27701 = [Control('iso27701', cid, theme, title, tuple(checks), evidence)
                for cid, theme, title, checks, evidence in _ISO27701]
    lgpd = [Control('lgpd', cid, theme, title, tuple(checks), evidence)
            for cid, theme, title, checks, evidence in _LGPD]
    return {'iso27001': iso27001, 'iso27701': iso27701, 'lgpd': lgpd}


CATALOG = _build()


def get_control(framework: str, control_id: str) -> Control | None:
    return next((c for c in CATALOG.get(framework, []) if c.id == control_id), None)
