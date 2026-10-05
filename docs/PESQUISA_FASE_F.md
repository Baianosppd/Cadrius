# Fase F (CAD-175) — carteira de clientes, finanças do escritório, portal do cliente e Fiscal fases 2–3

Critério: cobrir o que os ERPs jurídicos já entregam e o escritório espera (funil, contrato de honorários, financeiro, portal),
sem prometer o que não dá para validar agora. O que depende de contador/prefeitura ficou **configurável e marcado [VALIDAR]**.

## 1. O que entrou

| Área | O que o Cadrius faz | Onde |
|---|---|---|
| **Funil de captação** | Oportunidade por cliente (origem, valor estimado, próxima ação com data, responsável); etapas Novo → Entendendo o caso → Reunião → Proposta → Fechado/Perdido; motivo obrigatório ao perder; conversão em 90 dias, ações atrasadas, motivos de perda e origem que mais converte | Carteira de clientes → Funil |
| **Contrato de honorários** | À vista, parcelado, mensal (partido), êxito (% do proveito) e entrada + êxito; gera as parcelas sozinho (sobra de centavos na 1ª, meses curtos tratados); "Registrar êxito" lança o % do proveito; cancelar cancela as parcelas em aberto | Carteira → Contratos |
| **Finanças do escritório** | A receber/vencidos/pagos, baixa manual (forma e valor), cancelar/reabrir, despesas e custas por processo/cliente (reembolsável vira lançamento a receber), painel com inadimplência, previsão de 30 dias, resultado, recebido × despesas por mês e margem por cliente | Finanças (dono/admin; membros lançam despesas) |
| **Cobrança + baixa automática** | Lançamento → boleto/Pix no Asaas; webhook com token próprio (`asaas-access-token`, comparação em tempo constante) dá baixa sozinho; idempotente pelo id do evento (o Asaas entrega "pelo menos uma vez"); estorno reabre | Finanças → A receber |
| **Régua de cobrança** | Novo gatilho de automação "Honorário vencendo ou vencido" (N dias antes/depois) + 2 modelos prontos (lembrete por e-mail 3 dias antes, com aprovação; aviso à equipe + tarefa 5 dias após) | Automações → Regras |
| **Portal do cliente** | Link pessoal (token de 256 bits; só o hash fica guardado), validade de 1 a 365 dias, até 3 ativos por cliente, revogação na hora, contador de acessos e auditoria (1 por hora). O cliente vê os processos vinculados a ele com **andamentos em linguagem simples** (tabela própria, sem IA: não gasta crédito nem envia dados a terceiros, e não inventa significado) e, se o escritório quiser, os honorários em aberto com o botão Pagar | Contatos → Ficha e portal do cliente; página pública `/portal/<token>` |
| **Fiscal fase 2 (Cadrius)** | Conferência da NFS-e antes de emitir (tomador, valores, ISS, retenções para tomador PJ, CBS/IBS informativos e o que falta configurar); emissão pela Focus NFe com referência única; consulta automática a cada hora; cancelamento com justificativa; e-mail da nota ao cliente. Sem emissor configurado, continua o registro manual da fase 1 | Gestão → Fiscal → Recebimentos e notas |
| **Fiscal fase 3 (Cadrius)** | Calendário de obrigações (PGDAS-D/DAS, DCTFWeb, EFD-Reinf, ISS, FGTS Digital, eSocial, DEFIS) com regra de dia útil (feriados nacionais), "marcar como feita" por competência e aviso à equipe Fiscal 5 dias e 1 dia antes e no atraso. Tudo editável | Gestão → Fiscal → Obrigações |

## 2. [VALIDAR] antes de produção

- **NFS-e**: item da lista de serviços/código de tributação do SaaS, alíquota de ISS, regime e município da Cadrius
  (`CADRIUS_FISCAL_*` no `.env` do servidor); caminho do endpoint na Focus NFe (`FOCUSNFE_NFSE_PATH`: `nfse` municipal ou `nfsen`
  padrão nacional) e teste em **homologação** (`FOCUSNFE_BASE`). Retenções de tomador PJ (`FISCAL_RETENCOES_PJ`) só com o contador.
- **Reforma tributária**: em 2026 CBS 0,9% e IBS 0,1% são alíquotas-teste; para o Simples o destaque é exigido a partir de 2027
  (os valores aparecem só como informação na conferência).
- **Obrigações**: dias e regra de dia útil de cada obrigação (mudam por norma e por município) — editar na tela.
- **Asaas**: cadastrar o webhook no painel do Asaas com a URL e o token mostrados em Finanças → A receber.

## 3. Ficou para depois (e por quê)

| Ideia | Motivo |
|---|---|
| Timesheet / honorários por hora | Pouco uso em escritórios pequenos (prioridade P3 na pesquisa); entra se houver demanda |
| Conta digital / conciliação bancária (OFX/Open Finance) | Asaas já entrega boleto/Pix com baixa automática; conciliação de outros bancos exige Open Finance |
| Portal com documentos e mensagens | Aumenta superfície de vazamento (LGPD); começar só com processos e honorários e medir uso |
| Tradução de andamentos por IA | A tabela cobre os andamentos mais comuns sem custo nem risco; IA pode entrar como opção do escritório |
| Módulo fiscal para os escritórios (NFS-e dos honorários) | Depende de validar a emissão da própria Cadrius primeiro |

## Fontes
- Asaas: [eventos de cobrança](https://docs.asaas.com/docs/webhook-para-cobrancas) · [receber eventos e validar o token](https://docs.asaas.com/docs/receba-eventos-do-asaas-no-seu-endpoint-de-webhook) · [criar webhook pela API](https://docs.asaas.com/docs/criar-novo-webhook-pela-api) · [dúvidas sobre webhooks (entrega "pelo menos uma vez")](https://docs.asaas.com/docs/duvidas-frequentes-webhooks)
- NFS-e: [Focus NFe — guia NFS-e (padrão nacional, token)](https://focusnfe.com.br/guides/nfse/municipios-integrados/porto-nacional-to/) · [NFS-e Nacional em 2026](https://www.meucontadoronline.com.br/blog/nfs-e-nacional-2026-mudancas/) · [Reforma tributária e NFS-e — o que muda em 2026](https://actana.com.br/reforma-tributaria-nfse) · [Reforma tributária: Simples Nacional em 2026](https://www.meucontadoronline.com.br/blog/reforma-tributaria-em-2026/) · [Nota sem IBS/CBS e conformidade (LegisWeb)](https://www.legisweb.com.br/noticia/?id=34401)
- Obrigações: [Calendário fiscal 2026](https://www.contabilidadezen.com.br/blog/calendario-fiscal-2026-prazos-empresas/) · [Obrigações acessórias 2026](https://rolmyjuncontabilidade.com.br/fiscal-e-tributario/obrigacoes-acessorias-2026/) · [Agenda do contador 2026](https://simplifique.contmatic.com.br/blogs/agenda-para-contador-obrigacoes-acessorias-2026)
- Portal e financeiro jurídico: [EasyJur — portal do cliente](https://easyjur.com/blog/a-nova-easyjur/) · [LegJur — meu escritório (portal + honorários)](https://www.legjur.com/meu-escritorio) · [ADVBOX CRM](https://advbox.com.br/crm)
