"""Textos-base (v1.0) dos documentos legais e lista inicial de suboperadores.

ATENÇÃO: são rascunhos técnicos gerados para o projeto — marcados `needs_legal_review=True`.
Devem ser revisados por advogado/encarregado (DPO) antes de uso comercial. Para alterar o texto de
um documento já publicado, crie uma NOVA versão (o texto publicado é imutável).
"""

CIENCIA = """# Termo de Ciência de Tratamento de Dados

## 1. Papéis
O **Cadrius** atua como **operador** dos dados que o escritório (controlador) conecta à plataforma e como
**controlador** dos dados cadastrais de quem usa a plataforma (advogados e equipe).

## 2. Quais dados são utilizados
| Categoria | Exemplos | Origem |
|---|---|---|
| Identificação e contato do usuário | nome, e-mail, CPF, telefone, OAB/UF, área de atuação, foto | você |
| Dados do escritório | razão social, CNPJ, endereço, plano contratado | você |
| Credenciais de integração | senhas IMAP, tokens de API (guardados **cifrados**) | você |
| Conteúdo de comunicações | e-mails lidos via IMAP, mensagens WhatsApp, payloads de webhooks | sistemas conectados |
| Dados extraídos por IA | número de processo, prazos, partes, resumo | derivados do conteúdo |
| Registros técnicos e de segurança | IP, identificador do navegador (hash), data/hora, ações realizadas | uso da plataforma |
| Pagamento | identificador de cliente/assinatura (os dados de cartão ficam com o Stripe) | Stripe |

## 3. Finalidades e bases legais
- Prestar o serviço contratado e executar as automações configuradas (execução de contrato — art. 7º, V).
- Segurança, prevenção a fraudes e auditoria de acessos (legítimo interesse — art. 7º, IX — e obrigação legal).
- Cumprir obrigações legais e atender a direitos dos titulares (art. 7º, II).
- Comunicações opcionais de produto: **somente com consentimento**, que pode ser revogado a qualquer momento.

## 4. Compartilhamento e transferência internacional
Para prestar o serviço, trechos de conteúdo e metadados podem ser enviados a **suboperadores** (provedores de IA,
e-mail, mensageria, pagamentos, monitoramento e backup), alguns **fora do Brasil**. A lista atualizada, com país e
finalidade, está em **/api/v1/legal/subprocessors/** e na tela de Privacidade.

## 5. Inteligência Artificial
A IA lê o conteúdo para sugerir/extrair informações e gerar rascunhos de automações. **Não há decisão automatizada
exclusiva**: automações criadas por IA nascem como **rascunho** e só entram em operação após aprovação de um
Administrador/Dono do escritório.

## 6. Retenção
- Corpo de e-mails processados: 90 dias. Payloads/resultados de execuções: 90 dias. Logs de integração: 30 dias.
- Trilha de auditoria de segurança: 12 meses (online), sem conteúdo pessoal.
- Conta encerrada: dados do escritório mantidos 30 dias para recuperação e depois eliminados.

## 7. Segurança
Criptografia em trânsito e de credenciais em repouso, isolamento entre escritórios, controle de acesso por cargo,
trilha de auditoria imutável e detecção de comportamento anômalo.

## 8. Seus direitos
Confirmação, acesso, correção, anonimização/eliminação, portabilidade, informação sobre compartilhamento e
revogação do consentimento (LGPD, art. 18). Pedidos pela plataforma ou pelo canal do encarregado; resposta em até 15 dias.

## 9. Responsabilidade do escritório (controlador)
O escritório declara possuir **base legal** para tratar os dados de terceiros (clientes, partes, contrapartes) que
conectar ao Cadrius e responde por informá-los conforme a LGPD.
"""

TERMS = """# Termos de Uso

1. **Objeto.** O Cadrius é uma plataforma de hiperautomação com IA para escritórios de advocacia.
2. **Conta e acesso.** Você é responsável por manter suas credenciais em sigilo e pelas ações realizadas na sua conta.
3. **Uso aceitável.** É proibido usar a plataforma para fins ilícitos, tentar burlar limites/segurança, acessar dados de
   outro escritório ou sobrecarregar o serviço (sujeito a bloqueio e a registro na trilha de auditoria).
4. **Conteúdo e dados.** O escritório permanece titular/controlador do conteúdo que conecta e garante ter base legal para
   seu tratamento. O Cadrius o trata somente para prestar o serviço.
5. **IA.** Resultados de IA podem conter imprecisões e devem ser revisados por profissional habilitado antes de uso.
6. **Planos e pagamento.** Limites e valores seguem o plano contratado; cobrança processada pelo Stripe.
7. **Disponibilidade e suporte.** O serviço é prestado com esforço razoável de disponibilidade, sem garantia de operação ininterrupta.
8. **Encerramento.** Você pode encerrar a conta; os dados do escritório são mantidos por 30 dias e então eliminados.
9. **Alterações.** Mudanças relevantes geram nova versão e exigem novo aceite.
"""

PRIVACY = """# Política de Privacidade

Esta política explica como o Cadrius trata dados pessoais, em conformidade com a Lei nº 13.709/2018 (LGPD).

**Encarregado (DPO):** privacidade@cadrius.ia.br

## O que coletamos
Dados cadastrais (nome, e-mail, CPF, telefone, OAB), dados do escritório, credenciais de integração (cifradas),
conteúdo das comunicações conectadas e registros técnicos (IP, data/hora, ações). Detalhes e bases legais:
**Termo de Ciência de Tratamento de Dados**.

## Para que usamos
Prestar o serviço, garantir a segurança, cumprir obrigações legais e, com consentimento, enviar comunicações opcionais.

## Com quem compartilhamos
Suboperadores listados em /api/v1/legal/subprocessors/ (inclusive provedores no exterior, com salvaguardas contratuais).
Não vendemos dados pessoais.

## Por quanto tempo guardamos
Prazos de retenção no Termo de Ciência. Ao fim da finalidade, os dados são eliminados ou anonimizados.

## Seus direitos
Acesso, correção, anonimização/eliminação, portabilidade, informação sobre compartilhamento e revogação de consentimento.
Exerça pela tela de Privacidade ou escreva ao encarregado. Você também pode reclamar à ANPD.

## Cookies e armazenamento local
Usamos apenas o necessário para autenticação e funcionamento (sem cookies de publicidade).
"""

AI_NOTICE = """# Aviso sobre o uso de Inteligência Artificial

- Para extrair informações e sugerir automações, trechos do conteúdo (e-mails, documentos, mensagens) são enviados a
  provedores de IA (**OpenAI, Google Gemini ou Groq**, conforme o perfil de extração), que podem processar os dados **fora do Brasil**.
- O conteúdo enviado é limitado ao necessário; o Cadrius registra **quais provedores/categorias** foram usados (sem o conteúdo) na trilha de auditoria.
- A IA **não toma decisões jurídicas**: automações geradas por IA ficam como **rascunho** até a aprovação de um Administrador/Dono.
- O escritório pode desligar a IA, restringir provedores e definir o nível de autonomia nas configurações de governança.
- Respostas podem conter erros; revise antes de agir.
"""

DOCUMENTS = [
    ('terms', 'Termos de Uso', TERMS),
    ('privacy', 'Política de Privacidade', PRIVACY),
    ('ciencia', 'Termo de Ciência de Tratamento de Dados', CIENCIA),
    ('ai_notice', 'Aviso sobre Inteligência Artificial', AI_NOTICE),
]

SUBPROCESSORS = [
    ('OpenAI', 'Estados Unidos', 'Extração de dados e geração de automações por IA (GPT)', ['conteudo_comunicacao', 'processual']),
    ('Google (Gemini, Login, Sheets)', 'Estados Unidos', 'IA (Gemini), login social (OAuth) e integração com planilhas', ['conteudo_comunicacao', 'identificacao']),
    ('Groq', 'Estados Unidos', 'Inferência de IA (Llama) para extração e geração de automações', ['conteudo_comunicacao', 'processual']),
    ('Microsoft (login social)', 'Estados Unidos', 'Autenticação via conta Microsoft', ['identificacao']),
    ('Stripe', 'Estados Unidos / Irlanda', 'Processamento de pagamentos e assinaturas', ['identificacao', 'pagamento']),
    ('Supabase', 'Estados Unidos', 'Armazenamento de backups cifrados', ['backup_cifrado']),
    ('Sentry', 'Estados Unidos', 'Monitoramento de erros (sem dados pessoais automáticos)', ['registros_tecnicos']),
    ('Meta / WhatsApp (via Evolution API)', 'Estados Unidos', 'Envio e recebimento de mensagens WhatsApp', ['contato', 'conteudo_comunicacao']),
    ('Telegram', 'Reino Unido / EAU', 'Notificações opcionais', ['contato']),
    ('Trello / ClickUp', 'Estados Unidos', 'Criação de cartões/tarefas nas integrações do cliente', ['processual']),
    ('Locaweb (hospedagem)', 'Brasil', 'Hospedagem da aplicação e do banco de dados', ['todas']),
]
