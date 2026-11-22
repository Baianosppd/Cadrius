# Padrão visual dos diagramas do Cadrius

## 1. Diagnóstico: por que os diagramas antigos eram ilegíveis
As reclamações eram sobre os PNG. A causa não era a resolução, e sim o formato dos desenhos:

| Problema | Efeito |
|---|---|
| **Diagramas grandes demais** | Por exemplo, 30 tabelas num diagrama só ou 20 caixas num fluxo. Para caber na página, a imagem encolhe e a letra vai junto. |
| **Formato errado** | Fluxos compridos de cima para baixo ou fileiras enormes. Em tela 16:9, sobra espaço dos lados e o texto fica minúsculo. |
| **Sem moldura** | Sem título, nível, legenda nem rodapé. Quem recebia a imagem solta não sabia o que estava vendo. |
| **Visual inconsistente** | Tema padrão do Mermaid, cores sem regra e símbolos diferentes entre diagramas. |
| **Banco de dados no motor errado** | O Mermaid empilha na vertical as tabelas sem ligação entre si e usa fonte pequena no diagrama ER. |

**Medição:** na primeira rodada com o controle de legibilidade, 30 das 34 pranchas antigas ficavam com letra abaixo do mínimo. A pior tinha letras de 4 px.

## 2. Pesquisa: o que o mercado usa
- **Modelo C4** (Simon Brown), padrão mais usado para arquitetura de software:
  - níveis de zoom: Contexto → Contêineres → Componentes, mais o diagrama de implantação;
  - cada diagrama tem título e legenda;
  - cada elemento diz o nome, o tipo e a tecnologia;
  - vale mais fazer vários diagramas pequenos do que um só lotado.
- **UML de sequência** para fluxos entre sistemas:
  - passos numerados;
  - poucos participantes;
  - caminhos alternativos (`alt`, `opt`, `loop`).
- **Diagrama entidade-relacionamento em pé de galinha** para o banco:
  - dividido em áreas de assunto, cada uma em volta de uma tabela central;
  - o mínimo possível de linhas cruzando áreas;
  - a mesma notação em todos os diagramas.
- **Legibilidade:**
  - tamanhos de letra em degraus (título, seção, rótulo), não muitos tamanhos parecidos;
  - texto que ainda se lê impresso em A4;
  - legenda explicando cores, linhas e setas;
  - não depender só da cor (pensar em daltonismo e em impressão preto e branco).
- **Contraste:** WCAG AA, com no mínimo 4,5:1 entre texto e fundo.

## 3. Estratégia
1. **Uma prancha por ideia.** Cada diagrama é uma prancha 16:9 (1280×720) com:
   - **cabeçalho:** código, nível (C4, fluxo, dados), título e uma frase do que mostra;
   - **corpo:** o desenho;
   - **rodapé:** legenda dos símbolos, versão, número da página e caminho da fonte.
2. **Controle automático de legibilidade:**
   - o gerador mede o tamanho real das letras depois de encaixar o desenho na prancha;
   - se o 10º percentil ficar abaixo de **12 px** (30 px no PNG, cerca de 8 pt numa folha A4 deitada), a geração **falha**;
   - a regra é dividir o diagrama, nunca diminuir a letra.
3. **Diagramas como código:**
   - **fontes:** Mermaid (`.mmd`) para arquitetura e fluxos; Graphviz (`.dot`) para o banco;
   - **banco gerado dos modelos do Django:** nunca fica desatualizado;
   - **controle:** tudo versionado e revisado em PR como o resto do código.
4. **Três saídas:**
   - PNG em alta resolução, para mensagens e documentos;
   - SVG vetorial, para quem quer ampliar;
   - um **Caderno de Arquitetura em PDF** com capa, sumário e uma prancha por página.

## 4. Regras do padrão

### Tamanho e forma
| Tipo | Limite por prancha |
|---|---|
| Arquitetura (C4) | até cerca de 12 caixas e 6 por fileira; até 3 linhas por caixa |
| Sequência | até 6 participantes e 10 mensagens; o que um participante faz internamente vira **nota**, não seta para si mesmo |
| Fluxo de decisão | até 8 caixas; passou disso, divide em partes (ex.: F04 e F05) |
| Banco de dados | até 8 tabelas e 5 linhas por tabela: chave primária, chaves estrangeiras e os principais campos de negócio |

**Orientação:** da esquerda para a direita quando é uma cadeia; de cima para baixo quando há uma camada de entrada e várias de saída.

### Tipografia
- **Fonte:** Inter em tudo (cabeçalho, desenho, legenda).
- **Degraus:**

  | Elemento | Tamanho |
  |---|---|
  | título | 24 px |
  | nível | 11,5 px, em maiúsculas |
  | descrição | 13 px |
  | texto do desenho | 16 px (15 nas tabelas) |
  | legenda | 12 px |

- **Rótulos curtos:** nome em negrito, o tipo entre colchetes e, no máximo, uma descrição curta.

### Cores (contraste conferido)
| Uso | Fundo | Texto | Contraste |
|---|---|---|---|
| Pessoa | `#0B3D6E` | branco | 11,0:1 |
| Este sistema | `#1F5FAD` | branco | 6,4:1 |
| Contêiner | `#2E6DB4` | branco | 5,3:1 |
| Componente | `#D6E6F7` | `#0B2545` | 12,1:1 |
| Banco ou arquivos | `#24507F` | branco | 8,3:1 |
| Sistema externo | `#5B6573` | branco | 5,9:1 |
| Início ou evento | `#E8F1FB` | `#0B2545` | 13,5:1 |
| Decisão | `#FFF4D6` | `#4A3200` | 11,0:1 |
| Resultado esperado | `#E3F4EA` | `#123B23` | 11,0:1 |
| Interrompido | `#FDE8E8` | `#5C1414` | 11,4:1 |

A cor nunca é a única pista:
- cada caixa também diz o tipo, ex. `[Pessoa]`, `[Contêiner: Django]`;
- decisões são losangos;
- o limite do sistema é uma moldura tracejada.

### Notação
- **Arquitetura:** C4. Seta = "depende de / chama", com o verbo no rótulo; moldura tracejada = limite do sistema ou do contêiner.
- **Sequência:** UML, com setas cheias para chamadas, tracejadas para respostas e passos numerados.
- **Banco de dados:** pé de galinha.
  - `PK` = chave primária, `FK` = chave estrangeira, `UK` = valor único;
  - `cifrado` = campo cifrado em repouso;
  - `(Dxx)` = tabela de outra área.
  - A coluna `organization_id` (escritório) e as de autoria aparecem só em D01, para não poluir.

## 5. Catálogo
| Código | Conteúdo |
|---|---|
| **A01–A07** | Arquitetura: contexto (C4 nível 1), contêineres (nível 2), componentes da API e da aplicação web (nível 3), implantação e entrega contínua |
| **F01–F09** | Fluxos: login, SSO, leitura de documento, automação (em 2 partes), Assistente, pagamento, publicações e importação de pastas |
| **S01–S03** | Segurança e operação: camadas de proteção, ciclo de vida dos dados (LGPD) e rotinas agendadas |
| **D00–D20** | Banco de dados: mapa das áreas, 19 áreas com as 109 tabelas do Cadrius e as filas do Django-Q (D20) |

O índice com todas as pranchas está em [ARQUITETURA_E_DIAGRAMAS.md](ARQUITETURA_E_DIAGRAMAS.md).

## 6. Como gerar de novo
**Requisitos:** Node 20+, Python com as dependências do back-end, Graphviz (`apt-get install graphviz`), a fonte Inter instalada e:

```bash
npm i -g @mermaid-js/mermaid-cli@11 playwright
```

**Passos:**

```bash
# 1. banco de dados (lê os modelos do Django e escreve fontes/D*.dot e gerador/banco.json)
python docs/diagramas/gerador/banco.py

# 2. pranchas PNG, SVG, caderno PDF e o índice ARQUITETURA_E_DIAGRAMAS.md
node docs/diagramas/gerador/render.mjs

# só algumas pranchas, para conferir uma mudança (não gera o PDF nem o índice)
node docs/diagramas/gerador/render.mjs A01 F04
```

**Variáveis opcionais:**
- `CHROMIUM` (navegador);
- `MMDC` (caminho do mermaid-cli);
- `DOT` (caminho do Graphviz);
- `PLAYWRIGHT` (pasta do módulo).

**Se a geração falhar com "texto abaixo de 12px":**
- divida o diagrama ou encurte os rótulos;
- não mexa no limite.

`gerador/legibilidade.json` guarda a medida de cada prancha.

**Arquivos:**

| Arquivo | Conteúdo |
|---|---|
| `fontes/` | os diagramas |
| `gerador/catalogo.json` | títulos e descrições da arquitetura, dos fluxos e da segurança |
| `gerador/banco.py` | as áreas do banco |
| `gerador/tema.json` e `gerador/estilos.mmd` | o tema do Mermaid e as cores |

## Fontes da pesquisa
- **C4 model:**
  - [Notação](https://c4model.com/diagrams/notation)
  - [InfoQ: C4 architecture model](https://www.infoq.com/articles/C4-architecture-model/)
  - [Wikipedia](https://en.wikipedia.org/wiki/C4_model)
- **Consistência e legibilidade:**
  - [draw.io: consistent diagrams](https://www.drawio.com/blog/consistent-diagrams)
  - [Visualization guidelines (Gaudí)](https://www.gaudisite.nl/VisualizationGuidelinesSlides.pdf)
  - [Typography for technical diagrams](https://26fba7053f.geosurge.ai/corpus/gen-2462/typography/typography-for-technical-diagrams.html)
- **Banco de dados:**
  - [Redgate: layout de diagramas de banco e áreas de assunto](https://www.red-gate.com/blog/improve-database-diagram-layout/)
  - [draw.io: notação pé de galinha](https://www.drawio.com/blog/crows-foot-notation)
- **Exportação em alta resolução:**
  - [mermaid-cli](https://tessl.io/registry/tessl/npm-mermaid-js--mermaid-cli/11.6.0/files/docs/cli.md)
