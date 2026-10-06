# Fóruns, tribunais e cartórios — o que o Cadrius pode fazer pela rotina (CAD-223)

**Pergunta do Jullio:** "Para serviços como fórum, tem algo que podemos fazer que ajude na rotina desses locais?"

**Resposta curta:** sim, por dois caminhos.
1. **Agora, pelo lado do advogado:** cortar idas ao fórum e ligações ao cartório. Prazos certos (suspensões e
   indisponibilidades), Balcão Virtual na mão, aviso de processo parado e guias e certidões organizadas.
2. **Depois, com contrato:** integrações oficiais com os sistemas do Judiciário e dos cartórios. São elas:
   - Jus.br / PDPJ-Br;
   - MNI;
   - Domicílio Judicial Eletrônico;
   - e-Notariado / ONR / CRC.

Vender sistema para o próprio fórum **não** é o caminho. Os tribunais usam sistemas definidos pelo CNJ (PJe, eproc,
e-SAJ) e compram por licitação. O valor que o Cadrius consegue entregar está em tirar trabalho repetitivo **do
advogado e da secretaria do escritório** na relação com o fórum. Isso também alivia o balcão do fórum: menos ligações
e menos "qual o andamento?".

## 1. O que a pesquisa encontrou

| Serviço | O que é | Acesso para sistemas | Uso no Cadrius |
|---|---|---|---|
| **Balcão Virtual** (Res. CNJ 372/2021) | Videochamada com a secretaria da vara no horário de expediente, sem agendamento | Não tem API; cada tribunal publica o link | Link do Balcão Virtual por tribunal na ficha do processo e na tarefa "processo parado" (**feito no CAD-223**) |
| **Juízo 100% Digital** (Res. CNJ 345/2020) | Todos os atos por meio eletrônico; atendimento pelo magistrado a pedido do advogado, resposta em até 48 h | Pedido por e-mail/sistema da unidade | Modelo de pedido de atendimento (minuta) + tarefa de acompanhamento das 48 h (**fase 2**) |
| **Suspensão de prazos / indisponibilidade** | Portarias e certidões de cada tribunal (ex.: TRF3, TRT4 e TJRJ publicam listas) | Sem API nacional: páginas e PDFs de cada tribunal | Calendário forense nacional mantido pela equipe Cadrius (área Jurídico), que entra na contagem de prazos e avisa os escritórios (**feito no CAD-223**) |
| **DataJud** (API pública do CNJ) | Metadados e movimentos dos processos | Chave pública | Já usado no monitoramento; serve de base do gatilho "processo sem andamento" (**feito**) |
| **Comunica/DJEN** | Comunicações processuais publicadas | API pública | Já usado na captura de publicações (CAD-173) |
| **Jus.br / PDPJ-Br** | Portal único do Judiciário: consulta unificada e peticionamento intercorrente (e inicial, em expansão) | Login gov.br (nível ouro) ou certificado; APIs do PDPJ ainda para tribunais e parceiros | Atalho "abrir no Jus.br" e acompanhar a abertura das APIs da PDPJ (**fase 3**) |
| **MNI** (Modelo Nacional de Interoperabilidade) | Web service do PJe para peticionar, consultar e receber intimações | Certificado ICP-Brasil do advogado/escritório (CPF/CNPJ do certificado) | Peticionamento e recebimento de intimações direto do Cadrius, com o certificado do escritório (**fase 3** — exige homologação por tribunal) |
| **Domicílio Judicial Eletrônico** | Caixa única de citações e intimações para pessoas jurídicas | API para empresas (CNPJ); credenciais novas obrigatórias desde 31/03/2026 | Para escritórios com clientes empresa: importar as comunicações do cliente e criar prazos (**fase 3**, com o cliente concedendo acesso) |
| **Guias de custas** (DARE-SP, GRERJ, guias do TJDFT/TJCE…) | Emissão em portais próprios de cada tribunal, com código de barras/Pix | Sem API pública padronizada | Registrar a guia como despesa reembolsável do processo, lembrar o vencimento e anexar o comprovante; link do portal de custas por tribunal (**fase 2**) |
| **e-Notariado, ONR (RI Digital), CRC Nacional** | Atos notariais eletrônicos, matrículas de imóveis e certidões de registro civil | Plataformas próprias; integrações em andamento (ONR + e-Notariado, 2026) | Checklist de certidões por tipo de caso (inventário, divórcio, usucapião) com links oficiais e prazos de validade (**fase 2**) |

## 2. O que já entrou no CAD-223
1. **Calendário forense nacional**
   - A área Jurídico da Gestão Cadrius cadastra a suspensão de prazos, a falta de expediente ou a
     indisponibilidade de sistema de cada tribunal, sempre com o link do ato oficial.
   - Esses dias deixam de contar nos prazos calculados pelo Cadrius.
   - Os escritórios com processo naquele tribunal recebem o gatilho **"Suspensão de prazos no tribunal"**.
   - Modelo pronto: aviso no sino com o link oficial.
2. **Dados dos tribunais:** Balcão Virtual, portal de serviços, pauta e horário, mantidos com links oficiais.
3. **Gatilho "Processo sem andamento"**
   - Dispara quando o processo fica parado há N dias.
   - Modelo pronto: tarefa para consultar a secretaria pelo Balcão Virtual e dar notícia ao cliente, o que reduz
     ligações ao cartório.
4. **Pedido de parametrização** com a área "Tribunais / prazos": o escritório pede rotinas específicas da comarca
   dele.

## 3. Plano das próximas fases

### Fase 2 (próximo ciclo, sem dependência externa)

**Guias de custas**
- O que entra:
  - "Nova guia" no processo (tribunal, tipo, valor, vencimento);
  - a guia vira despesa reembolsável;
  - lembrete antes do vencimento;
  - anexar o comprovante;
  - link do portal de custas do tribunal.
- Critério de pronto: nenhuma guia vence sem aviso, e o reembolso aparece na cobrança do cliente.

**Juízo 100% Digital**
- O que entra:
  - modelo de pedido de atendimento ao magistrado (processo, nome e OAB);
  - tarefa de acompanhamento de 48 h;
  - marcação "100% Digital" no processo, para que as audiências virem compromisso com link.
- Critério de pronto: pedido gerado em menos de 1 minuto e acompanhado.

**Checklist de certidões**
- O que entra: certidões por tipo de caso, com o órgão emissor, o link oficial, a validade e o alerta de vencimento.
- Critério de pronto: inventário e divórcio extrajudicial com checklist completo.

**Pauta de audiências**
- O que entra: importar a pauta publicada pelo tribunal, quando houver página oficial estruturada, e cruzar com os
  processos do escritório.
- Critério de pronto: audiência na pauta vira compromisso e alerta ao cliente.

### Fase 3 (exige credenciamento, contrato ou homologação)

**MNI / PJe**
- Pré-requisitos:
  - certificado ICP-Brasil do escritório guardado com segurança (HSM ou certificado A1 cifrado);
  - homologação em cada tribunal (endpoints variam por TRT/TJ/TRF).
- Risco ou cuidado: responsabilidade pelo protocolo. Começar só pelo **recebimento de intimações**, com o
  peticionamento depois.

**Domicílio Judicial Eletrônico**
- Pré-requisitos: credencial de API do cliente empresa, concedida por ele (Res. CNJ 455/2022 e normas do Domicílio).
- Risco ou cuidado: dado de terceiro, que exige contrato com o cliente e base legal LGPD.

**Jus.br / PDPJ-Br**
- Pré-requisitos: abertura de APIs a parceiros (acompanhar o CNJ e o Programa Justiça 4.0).
- Risco ou cuidado: hoje só login gov.br, sem API para terceiros.

**Cartórios (e-Notariado, ONR, CRC)**
- Pré-requisitos: convênio com as centrais.
- Risco ou cuidado: custos por certidão; cobrar o cliente pelo próprio Cadrius (despesa reembolsável).

## 4. Riscos e regras
- **Fonte oficial sempre:** suspensão sem link do ato oficial não é aceita. Prazo calculado continua "sugestão:
  confira o calendário do tribunal".
- **Responsabilidade profissional:** protocolo automático (MNI) só com confirmação humana e registro de quem
  protocolou.
- **LGPD:** dados de partes (Domicílio, pesquisas por CPF) só com finalidade e base legal definidas. A equipe Cadrius
  não acessa dados do escritório sem acesso assistido.
- **OAB:** nada de captação. Os avisos ao cliente são informativos e sobre o processo dele.

## Fontes
- [Balcão Virtual — Res. CNJ 372/2021 (compilado)](https://atos.cnj.jus.br/files/compilado2033002021070160de267c1a5d8.pdf) · [Manual TJSC](https://tjsc.jus.br/documents/10181/7541852/Balca%C2%BFo+Virtual+-+Manual+do+Usua%C2%BFrio+Externo/b1e6f15c-dc97-6dbd-1831-bb9aec4fad1d)
- [Juízo 100% Digital — AASP/CNJ](https://www.aasp.org.br/?p=35472) · [Res. CNJ 345/2020](https://atos.cnj.jus.br/atos/detalhar/3512)
- [TRF3 — suspensão de prazos por indisponibilidade do PJe](https://www.trf3.jus.br/pje/suspensao-de-prazos-por-indisponibilidade-do-sistema-pje) · [TRT4 — períodos de indisponibilidade](https://www.trt4.jus.br/portais/trt4/pje-indisponibilidade) · [TJRJ — suspensões 2026](https://www.tjrj.jus.br/documents/d/portal-conhecimento/suspensao-prazos-1a-e-2a-instancia_2026_seesc) · [TRT2 — quando a indisponibilidade prorroga prazos](https://ww2.trt2.jus.br/noticias/noticias/noticia/saiba-quando-a-indisponibilidade-no-pje-resulta-em-prorrogacao-de-prazos-processuais)
- [Domicílio Judicial Eletrônico — atualização obrigatória até 31/03/2026](https://www.rotajuridica.com.br/?p=168412) · [CNJ — conheça o Domicílio](https://www.cnj.jus.br/wp-content/uploads/2024/02/conheca-domicilio-judicial-eletronico.pdf)
- [API pública do DataJud](https://www.ibdp.org.br/?p=12523) · [Comparativo DataJud x APIs privadas (Judit)](https://judit.io/blog/legislacao-atualizacoes-regulatorias/datajud-cnj-api-publica-x-privada-comparacao/)
- [Jus.br — folder OAB 2025](https://cnj.jus.br/wp-content/uploads/2025/03/folder-jus-br-oab-2025-ajustado.pdf) · [TRF3 — Jus.br com jurisprudência](https://web.trf3.jus.br/noticias/Noticiar/ExibirNoticia/435738-jusbr-passa-a-oferecer-servico-de-busca-de-jurisprudencia)
- [MNI no PJe — TJMG](https://www.tjmg.jus.br/portal-tjmg/acoes-e-programas/gestao-de-primeira/processo-judicial-eletronico-fluxo-unificado-civel/modelo-nacional-de-interoperabilidade-mni-pje.htm) · [CSJT — petição por MNI](https://www.csjt.jus.br/web/csjt/-/mni-permite-que-procuradores-realizem-peticoes-no-pje-jt-em-apenas-alguns-segundos)
- [TJSP — Portal de Custas (DARE-SP)](https://tjsp.jus.br/Download/Portal/PortalCustas/PETIC-2.1-PORTAL-CUSTAS-Publico-Externo-TIMBRADO-Emissao-de-Guias-de-Custas_05.09.24.pdf) · [TJDFT — guias online](https://www.cnj.jus.br/tjdft-disponibiliza-emissao-de-todos-os-tipos-de-guia-de-custas-pela-internet/)
- [e-Notariado, CRC e ONR — Anoreg/CNB](https://cnbsp.org.br/2025/10/09/anoreg-br-cartorio-na-palma-da-mao-como-a-digitalizacao-revoluciona-servicos-notariais-e-registrais-no-brasil/)
