# 🛡️ Política de Segurança - Cadrius AI

A segurança é o pilar central do Cadrius AI. Implementamos múltiplas camadas de proteção para garantir a integridade dos dados e a conformidade com a LGPD.

## 1. Criptografia de Dados em Repouso (AES-128)
Todas as credenciais de terceiros (Tokens de API, senhas de IMAP, chaves de integração) são encriptadas antes de serem gravadas no banco de dados utilizando a biblioteca `cryptography` (Fernet).
* **Localização:** `core/utils.py` (`EncryptedTextField`, `EncryptedJSONField`) — aplicados a `MailBox.password` e `AppConnection.credentials`.
* **Implementação:** Fernet com chave definida em `ENCRYPTION_KEY` (obrigatória em produção). Rotação: `ENCRYPTION_KEY="nova,antiga"`.



## 2. Isolamento de Rede (Docker Networking)
O banco de dados PostgreSQL e o Redis residem em uma rede privada chamada `backend_net`.
* **Regra:** Estes serviços **não possuem** portas expostas para o host (Windows/Linux). 
* **Acesso:** Apenas o container da aplicação (`web`) e o `worker` possuem permissão para se comunicar com o banco de dados.

## 3. Proteção contra Força Bruta (Django Axes)
Utilizamos o `django-axes` para monitorar tentativas de login falhas.
* **Política:** Após 5 tentativas consecutivas de erro, o IP do atacante é bloqueado temporariamente (Cool-off de 1 hora).
* **Audit Log:** Todas as tentativas de acesso são registradas para auditoria posterior.
* **Rate limit:** login 10/min, cadastro 5/h, refresh 30/min (por IP); bloqueio por IP ou utilizador.
* **Sessões:** logout revoga o refresh token (`POST /api/v1/auth/logout/`).

## 4. Segurança de Cabeçalhos (CSP)
Implementamos **Content Security Policy (CSP)** para mitigar ataques de Cross-Site Scripting (XSS).
* **Restrição:** Apenas scripts de domínios confiáveis e do próprio servidor são executados.
* **Anti-Clickjacking:** Cabeçalhos `X-Frame-Options` configurados como `DENY` para impedir que o sistema seja incorporado em sites maliciosos.

---

## 5. Proteções adicionais
* **SSRF:** ações de webhook não chamam redes privadas/loopback/metadados (`integrations/ssrf.py`).
* **Segredos:** a aplicação recusa arrancar em produção sem `SECRET_KEY`, `ENCRYPTION_KEY` e chave da Evolution API.
* **LGPD:** Sentry sem PII automática; ver `docs/AUDITORIA_SEGURANCA.md` e `docs/PLANO_AUDITORIA_LGPD.md`.

---

**Responsável pela Segurança:** Jullio Cesar Godoi Dutra