# WhatsApp: como o escritório conecta o próprio número (CAD-225)

## O problema
Antes, o escritório precisava de uma Evolution API **própria**: instância, chave e URL do servidor. Para um advogado,
isso é técnico demais. O pedido é: informar o número, receber um link ou código e pronto.

## Opções estudadas

| | A. Evolution hospedada pelo Cadrius | B. API oficial da Meta (Cloud API) com Embedded Signup | C. Provedor oficial (Zenvia, Twilio…) |
|---|---|---|---|
| Como o escritório conecta | Número → código de 8 letras ou QR code no WhatsApp do celular ("Aparelhos conectados") | Clica em "Conectar", faz login no Facebook numa janela da Meta, escolhe o número e confirma por SMS | Contrato com o provedor e cadastro do número lá |
| Usa o número que o escritório já tem no celular | Sim (o app continua funcionando) | Não no mesmo app: o número passa para a plataforma oficial (sai do WhatsApp comum ou do Business do celular) | Igual à B |
| Mensagem ao cliente | Texto livre | Fora da janela de 24 h, só com **modelo aprovado pela Meta** | Igual à B |
| Custo | Servidor do Cadrius (já existe) | Cobrança da Meta por mensagem de modelo | Provedor + Meta |
| O que o Cadrius precisa | Ligar o perfil `whatsapp` do docker compose | Ser *Tech Provider* na Meta (verificação da empresa, app aprovado e análise da Meta) | Contrato |
| Risco | API não oficial: a Meta pode bloquear números com envio em massa ou denúncias | Nenhum risco de bloqueio por uso de API não oficial | Igual à B |

## Recomendação
1. **Agora (lançamento): opção A**, já implementada nesta entrega. É a única que entrega "número e pronto" sem burocracia
   e mantém o número no celular do advogado. O risco de bloqueio fica baixo porque o Cadrius já limita o envio:
   - só para quem autorizou WhatsApp;
   - em horário comercial;
   - com aprovação por padrão;
   - sem disparo em massa.
2. **Em 2 a 3 meses: opção B** como plano "oficial", para escritórios com mais volume. Começa pelo pedido de *Tech
   Provider* na Meta, que leva semanas. A tela já tem o lugar para um segundo botão, "Conectar pela Meta".

## Como ficou (opção A)
**Em Integrações → cartão "WhatsApp do escritório"** (só dono ou administrador):
1. Informa o número com DDD e clica em **Conectar**.
2. A tela mostra:
   - o **código de pareamento**, para digitar no próprio celular: WhatsApp → Aparelhos conectados → Conectar com número de
     telefone;
   - o **QR code**, para ler de outro aparelho.
3. A tela confere sozinha a cada 4 segundos. Quando o celular conecta, mostra "Conectado", e as automações e o aviso ao
   cliente passam a usar esse número.

**Celular longe?** O botão **"Gerar link para o celular"** cria um link de 15 minutos, sem login, para quem está com o
celular do escritório. A página mostra só o código e o passo a passo.

**Para sair:** botão **Desconectar**. Ele encerra a sessão no WhatsApp e apaga a instância.

## Segurança e LGPD
- **Chave do servidor:** a chave do servidor Evolution do Cadrius nunca sai do servidor. A conexão do escritório guarda
  só o nome da instância (`cadrius-<id>`).
- **Link para o celular:**
  - assinado e válido por 15 minutos;
  - mostra só o código e os 4 últimos dígitos do número;
  - o código fica 40 segundos em cache, para a página não gerar um código novo a cada consulta.
- **Auditoria:** conectar, gerar link e desconectar ficam registrados.
- **Separação entre escritórios:** cada escritório tem a sua instância, e as automações de um não enviam pelo número de
  outro.
- **Ajuste técnico:** o envio passou a usar o formato da Evolution v2, a versão que o Cadrius hospeda. Ele manda os dois
  formatos, então continua funcionando com Evolution v1 própria.

## No servidor
1. No `.env` do ambiente:
   - `EVOLUTION_API_GLOBAL_KEY`: uma chave longa e aleatória;
   - `COMPOSE_PROFILES=whatsapp`;
   - `EVOLUTION_API_BASE_URL=http://evolution-api:8080` (padrão).
2. Rodar `docker compose --project-name cadrius-<env> up -d evolution-api web worker`.
3. Conferir: em Integrações aparece o cartão "WhatsApp do escritório". Sem o perfil ligado, o cartão não aparece e vale
   o formulário antigo (Evolution própria).
