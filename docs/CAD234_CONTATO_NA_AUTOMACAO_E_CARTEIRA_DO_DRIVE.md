# CAD-234: contato na automação, APIs públicas e carteira de clientes do Drive

## 1. Automação ou mensagem para quem ainda não é contato (uma confirmação só)

**Antes**, se a pessoa pedia ao Assistente "todo dia 5, mande o fechamento para o João, nosso contador", o fluxo travava:
- o João precisava estar nos contatos;
- a regra só conseguia mandar mensagem ao cliente ou contato **do evento**.

**Agora:**

| Parte | O que mudou |
|---|---|
| **Destinatário fixo** | As ações de mensagem (WhatsApp, e-mail, "melhor canal") aceitam `contato:<id>`: sempre a mesma pessoa, em qualquer gatilho (inclusive mensais e agendados). No editor de regras: **Para → "Um contato específico…"**, com busca pelo nome. |
| **Variável nova** | `{{destinatario.nome}}` e `{{destinatario.primeiro_nome}}`: quem vai receber. |
| **Assistente** | `criar_regra` e `enviar_mensagem_cliente` aceitam `novo_contato` (nome, e-mail, telefone, CPF/CNPJ). Na confirmação, o contato é cadastrado e a regra (ou o envio) usa ele. |
| **Reaproveitamento** | Mesmo e-mail, CPF/CNPJ ou telefone = o mesmo contato: não duplica. |
| **Autorização (LGPD)** | Só é registrada quando a pessoa diz que o contato autorizou WhatsApp ou e-mail. Fica gravado quem informou e quando (`consent_source`). Sem isso, o cartão avisa que o envio fica bloqueado até registrar. |

**Exemplo de cartão de confirmação:**
> Criar automação — Primeiro cadastra o contato "João Contador" (joao@contab.com); registra que ele(a) autorizou e-mail (informado por você). Depois: Quando "Acompanhamento da meta do mês" → Avisar o cliente (melhor canal autorizado). Nasce DESLIGADA: simule e ligue em Automações.

**Arquivos:**
- `contacts/quick.py`;
- `assistant/tools.py`;
- `assistant/engine.py` (regra 7 do Assistente);
- `automations/catalog.py`;
- `automations/engine.py`.

## 2. APIs públicas para deixar o sistema mais esperto

- **Base:** a BrasilAPI (lista public-apis; gratuita, sem chave) já completava o cadastro pelo CNPJ (CAD-223).
- **Assistente:** usa duas ferramentas novas, `consultar_cnpj` (dados da Receita Federal) e `consultar_cep`.
- **Contato novo com CNPJ:** quando o Assistente cadastra uma empresa, nome, e-mail e telefone que faltarem vêm da Receita.

## 3. Carteira de clientes em pastas no Google Drive

**Caso:** o escritório guarda os clientes no Drive assim:
- uma pasta-mãe;
- dentro dela, uma pasta por cliente (o nome da pasta é o nome do cliente);
- dentro de cada pasta, os documentos.

**Onde:** **Configurações → Importar dados → Pastas de clientes (Drive)**. Há duas origens, com o mesmo resultado:

| Origem | Como | Precisa de |
|---|---|---|
| **Google Drive** | Cola o link da pasta-mãe | Autorizar a **leitura do Drive** (pedida só nesse momento, na própria tela) |
| **Arquivo .zip** | No Drive: botão direito na pasta-mãe → **Fazer download**, depois envia o .zip | Nada |

**Passos:**
1. **Ver as pastas:** prévia sem gravar nada. Para cada pasta mostra o nome do cliente, CPF/CNPJ achado no nome, número de arquivos e se ele já é contato. Também diz o que fica de fora.
2. **Conferir:** desmarque o que não quiser. Opcional: "Ler os documentos com a IA" (usa créditos).
3. **Importar:** roda em segundo plano, com progresso na tela.

**O que acontece em cada pasta:**
- cria o contato (cliente, origem "Importação", etiqueta `drive`) ou reaproveita o existente (pelo CPF/CNPJ do nome da pasta ou pelo mesmo nome);
- cada arquivo vira um documento do cliente, cifrado como todos os documentos, com o caminho da subpasta no nome ("Processo 123/Petição inicial.docx");
- o tipo do documento é sugerido pelo nome do arquivo (procuração, contrato, petição);
- Google Docs vira PDF e Planilhas vira .xlsx;
- formulários e atalhos ficam de fora.

**Regras do nome da pasta:**
- "Maria Souza - 529.982.247-25" → nome "Maria Souza" + CPF (só se o CPF ou CNPJ for válido);
- "02 - José Lima" → "José Lima" (a numeração da pasta sai).

**Reimportar é seguro:** documento com o mesmo nome no mesmo contato não duplica. Dá para importar de novo depois para trazer os clientes e arquivos novos.

**No contato:** a ficha do contato mostra os **Documentos** dele (`/api/v1/documentos/?contato=<id>`).

**Limites e segurança:**
- **Arquivos aceitos:** PDF, Office/LibreOffice, imagens, texto, e-mail (.eml/.msg) e áudio/vídeo comuns, até `DOCUMENT_MAX_BYTES` (25 MB) cada.
- **Arquivos recusados:** programas, arquivos de sistema, `..` no caminho.
- **Proteção do .zip:** índice lido sem descompactar tudo; limite de 4 GB descompactado.
- **Tamanhos máximos:** 2 GB por .zip (`FOLDER_IMPORT_MAX_ZIP_BYTES`); até 2.000 pastas e 20.000 arquivos por vez.
- **Onde o .zip fica:** numa pasta privada do servidor (permissão 0600, volume comum web/worker). É apagado ao terminar; prévias abandonadas são limpas em 48 h pela rotina diária `purge_import_rows`. A prévia fica cifrada e é zerada ao concluir.
- **Etapas:** a importação trabalha em etapas de 40 s, abaixo do limite de 60 s da fila, e continua sozinha de onde parou.
- **Auditoria:** `data.import` (início e fim, com os totais) e `contact.created`.

**Google:**
- **Escopo:** a leitura do Drive usa `drive.readonly`. É um escopo **restrito** do Google: para uso público, o app OAuth precisa passar pela verificação do Google. Até lá, só os "usuários de teste" cadastrados no app conseguem autorizar.
- **Sem verificação:** use o caminho do **.zip** (funciona sem nada) ou `GOOGLE_DRIVE_IMPORT_ENABLED=false` para esconder o botão de autorização.
- **Pedido incremental:** o escopo extra é pedido só quando a pessoa clica "Autorizar leitura do Drive" (o Google devolve a pessoa para a tela Importar). A conexão normal do Google continua só com `drive.file`.

**Arquivos:**
- `imports/folders.py`;
- `imports/folders_api.py`;
- `imports/models.py` (`FolderImport`);
- `documents/models.py` (`Document.contact`);
- `gcal/google_api.py` (`download`);
- `gcal/platform.py`;
- `gcal/api.py`.

## 4. Servidor

- **Migrações:** `documents 0010_cad234` e `imports 0002_cad234`. Rodam no deploy.
- **`.env` (opcionais):**
  - `GOOGLE_DRIVE_IMPORT_ENABLED=true`;
  - `FOLDER_IMPORT_MAX_ZIP_BYTES=2147483648`;
  - `FOLDER_IMPORT_TMP_DIR=` (vazio = `MEDIA_ROOT/imports-tmp`).
- **Traefik:** o proxy limitava **toda** a API a 2 MB. Isso também barrava documentos de 2 a 25 MB. Agora há duas rotas com limite próprio, e o resto continua em 2 MB:
  - `/api/v1/documentos/` e `/api/v1/minutas/`: até 30 MB;
  - `/api/v1/imports/pastas/zip/`: até 2 GB.

  O corpo grande vai para o disco do proxy, não para a memória. O kit novo chega pelo `deploy.sh`. Depois do deploy, confira se o Traefik recarregou o `dynamic.yml`; se não, `docker restart` no Traefik.
- **Google Cloud (só para o caminho do Drive):** na tela de consentimento do app, adicione o escopo `.../auth/drive.readonly` e os usuários de teste, ou peça a verificação do Google.

## 5. Testes

- `assistant/tests_cad234.py`: contato novo na regra e na mensagem, reaproveitamento, autorização, contato fixo e simulação.
- `imports/tests_folders.py`:
  - nome da pasta, prévia do .zip e lixo ignorado;
  - importação, reimportação sem duplicar e só as pastas marcadas;
  - IA opcional, etapas, cancelamento e isolamento entre escritórios;
  - Drive com exportação do Google Docs e escopo extra no conectar.
