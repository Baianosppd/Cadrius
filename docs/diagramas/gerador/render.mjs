// Gera as pranchas da documentação de arquitetura (padrão em docs/diagramas/PADRAO_VISUAL.md).
//
//   node docs/diagramas/gerador/render.mjs
//
// Precisa de: @mermaid-js/mermaid-cli 11 (comando mmdc) e playwright com Chromium.
// e Graphviz (comando dot) para o banco de dados.
// Variáveis opcionais: MMDC (caminho do mmdc), DOT, CHROMIUM (executável do navegador), PLAYWRIGHT (caminho do módulo).
// Saída: svg/ (diagrama puro), pranchas/ (PNG 3200x1800 com título e legenda) e CADERNO_DE_ARQUITETURA.pdf.
// Falha (código 1) se algum diagrama ficar com texto menor que o mínimo: divida o diagrama em vez de reduzir a fonte.
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync, mkdtempSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const GER = dirname(fileURLToPath(import.meta.url));
const RAIZ = dirname(GER);
const VERSAO = new Date().toISOString().slice(0, 10);
const LARGURA = 1280, ALTURA = 720, ESCALA_PNG = 2.5;
const FONTE_MINIMA = 12;        // px na prancha 1280x720 = 30 px no PNG e cerca de 8 pt numa folha A4 deitada
const AMPLIACAO_MAXIMA = 1.4;   // diagramas pequenos não viram cartaz

const CHROMIUM = process.env.CHROMIUM || '/opt/pw-browsers/chromium';
const MMDC = process.env.MMDC || 'mmdc';
const { chromium } = await import(process.env.PLAYWRIGHT
  ? pathToFileURL(join(process.env.PLAYWRIGHT, 'index.mjs')).href : 'playwright');

const SO = process.argv.slice(2);   // ex.: node render.mjs A01 F04 (só esses, sem o PDF)
const itens = [
  ...JSON.parse(readFileSync(join(GER, 'catalogo.json'), 'utf8')),
  ...JSON.parse(readFileSync(join(GER, 'banco.json'), 'utf8')),
].filter((it) => !SO.length || SO.includes(it.id));
const estilos = readFileSync(join(GER, 'estilos.mmd'), 'utf8');

const LEGENDAS = {
  c4: [['q', '#0B3D6E', 'Pessoa'], ['q', '#1F5FAD', 'Este sistema'], ['q', '#2E6DB4', 'Contêiner (roda separado)'],
    ['q', '#D6E6F7', 'Componente (módulo)'], ['q', '#24507F', 'Banco ou arquivos'], ['q', '#5B6573', 'Sistema externo'],
    ['t', '→', 'depende de / chama'], ['t', '┄', 'limite do sistema']],
  fluxo: [['q', '#E8F1FB', 'Início ou evento'], ['q', '#FFFFFF', 'Passo'], ['q', '#FFF4D6', 'Decisão'],
    ['q', '#E3F4EA', 'Resultado esperado'], ['q', '#FDE8E8', 'Interrompido'], ['t', '→', 'ordem do fluxo']],
  sequencia: [['q', '#0B3D6E', 'Ator ou participante'], ['t', '→', 'chamada'], ['t', '⇢', 'resposta'],
    ['t', '①', 'ordem dos passos'], ['q', '#E8F1FB', 'alt / opt / loop: caminhos alternativos'],
    ['q', '#FFF4D6', 'Nota: o que o participante faz internamente']],
  dados: [['t', 'PK', 'chave primária'], ['t', 'FK', 'chave estrangeira'], ['t', 'UK', 'valor único'],
    ['t', 'cifrado', 'cifrado em repouso'], ['t', '┼ ─ <', 'um para muitos'], ['t', 'o', 'pode ficar vazio'],
    ['t', '(Dxx)', 'tabela de outra área']],
  mapa: [['q', '#1F5FAD', 'Área central (escritório e usuários)'], ['q', '#D6E6F7', 'Área do modelo'],
    ['t', '→', 'chave estrangeira de uma área para outra'], ['t', 'n FK', 'quantas, quando mais de uma']],
  seguranca: [['q', '#FFFFFF', 'Camada de proteção'], ['t', '1 → 8', 'da borda da rede até a continuidade']],
};

function compor(texto) {
  if (!/^\s*flowchart/.test(texto)) return texto;
  const molduras = [...texto.matchAll(/^\s*subgraph\s+([A-Za-z0-9_]+)/gm)].map((m) => m[1]);
  const extra = molduras.map((id) => `    style ${id} fill:#F8FAFC,stroke:#64748B,stroke-width:1.5px,stroke-dasharray:6 4,color:#334155`);
  return `${texto.trimEnd()}\n${estilos}${extra.join('\n')}\n`;
}

function gerarSvg(item) {
  const dot = join(RAIZ, 'fontes', `${item.arquivo}.dot`);
  if (existsSync(dot)) {    // banco de dados: Graphviz (pé de galinha), gerado por banco.py
    // Tabelas soltas: testa arranjos de grade e fica com o que deixa o desenho maior na área útil da prancha
    const area = [LARGURA - 64, ALTURA - 200];
    const modos = ['array_u', 'array_c2', 'array_c3', 'array_r2', 'array_r3', 'graph'];
    const rumos = readFileSync(dot, 'utf8').includes(':e ->') ? ['LR'] : ['LR', 'TB'];   // setas presas em colunas: só LR
    const opcoes = modos.flatMap((modo) => rumos.map((rumo) => [modo, rumo])).map(([modo, rumo]) => {
      const svg = execFileSync(process.env.DOT || 'dot', ['-Tsvg', `-Gpackmode=${modo}`, `-Grankdir=${rumo}`, dot]).toString();
      const [, w, h] = svg.match(/viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"/) || [0, 1, 1];
      return { svg, escala: Math.min(area[0] / w, area[1] / h) };
    }).sort((a, b) => b.escala - a.escala);
    const svg = opcoes[0].svg.replace(/^[\s\S]*?(<svg)/, '$1');
    writeFileSync(join(RAIZ, 'svg', `${item.arquivo}.svg`), svg);
    return svg;
  }
  const tmp = mkdtempSync(join(tmpdir(), 'cadrius-diag-'));
  const entrada = join(tmp, `${item.arquivo}.mmd`);
  writeFileSync(entrada, compor(readFileSync(join(RAIZ, 'fontes', `${item.arquivo}.mmd`), 'utf8')));
  const pp = join(tmp, 'puppeteer.json');
  writeFileSync(pp, JSON.stringify({ executablePath: CHROMIUM, args: ['--no-sandbox'] }));
  const saida = join(RAIZ, 'svg', `${item.arquivo}.svg`);
  execFileSync(MMDC, ['-q', '-p', pp, '-c', join(GER, 'tema.json'), '-b', 'transparent', '-i', entrada, '-o', saida],
    { stdio: ['ignore', 'ignore', 'inherit'] });
  return readFileSync(saida, 'utf8');
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

function legenda(tipo) {
  return (LEGENDAS[tipo] || []).map(([forma, valor, texto]) => forma === 'q'
    ? `<span class="item"><i style="background:${valor}"></i>${esc(texto)}</span>`
    : `<span class="item"><b>${esc(valor)}</b>${esc(texto)}</span>`).join('');
}

function prancha(item, svg, n, total) {
  return `<section class="prancha">
  <header>
    <div class="codigo">${item.id}</div>
    <div class="titulos">
      <div class="nivel">${esc(item.nivel)}</div>
      <h1>${esc(item.titulo)}</h1>
      <p>${esc(item.descricao)}</p>
    </div>
  </header>
  <main><div class="desenho">${svg}</div></main>
  <footer>
    <div class="legenda">${legenda(item.tipo)}</div>
    <div class="meta">Cadrius · Arquitetura · ${VERSAO} · ${n}/${total} · fontes/${item.arquivo}.${existsSync(join(RAIZ, 'fontes', `${item.arquivo}.dot`)) ? 'dot' : 'mmd'}</div>
  </footer>
</section>`;
}

const CSS = `
@page { size: ${LARGURA}px ${ALTURA}px; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #FFFFFF; font-family: Inter, 'Segoe UI', Arial, sans-serif; color: #1E293B; }
.prancha { width: ${LARGURA}px; height: ${ALTURA}px; display: flex; flex-direction: column; overflow: hidden;
  page-break-after: always; break-after: page; position: relative; }
header { display: flex; gap: 16px; align-items: flex-start; padding: 22px 32px 12px; border-bottom: 1px solid #E2E8F0; }
.codigo { background: #0B3D6E; color: #FFF; font-weight: 700; font-size: 18px; border-radius: 8px; padding: 9px 12px; letter-spacing: .5px; }
.nivel { font-size: 11.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: #2E6DB4; }
h1 { margin: 2px 0 4px; font-size: 24px; line-height: 1.2; font-weight: 700; color: #0B2545; }
header p { margin: 0; font-size: 13px; line-height: 1.45; color: #475569; max-width: 1080px; }
main { flex: 1; display: flex; align-items: center; justify-content: center; padding: 10px 32px; min-height: 0; }
.desenho { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; }
.desenho svg { display: block; }
footer { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 10px 32px 14px;
  border-top: 1px solid #E2E8F0; font-size: 12px; color: #334155; }
.legenda { display: flex; flex-wrap: wrap; gap: 6px 16px; }
.item { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.item i { width: 14px; height: 14px; border-radius: 3px; border: 1px solid #64748B; display: inline-block; }
.item b { font-weight: 700; color: #0B2545; font-size: 12px; }
.meta { color: #64748B; font-size: 11px; white-space: nowrap; }
.capa { justify-content: center; padding: 0 96px; background: #0B3D6E; color: #FFF; }
.capa h1 { color: #FFF; font-size: 48px; margin: 0 0 12px; }
.capa p { font-size: 18px; color: #D6E6F7; margin: 0 0 6px; max-width: 900px; line-height: 1.5; }
.sumario { padding: 40px 64px; }
.sumario h2 { margin: 0 0 18px; font-size: 26px; color: #0B2545; }
.sumario ol { columns: 2; column-gap: 48px; margin: 0; padding: 0; list-style: none; font-size: 13.5px; }
.sumario li { break-inside: avoid; padding: 5px 0; border-bottom: 1px dotted #CBD5E1; display: flex; gap: 10px; }
.sumario li b { color: #2E6DB4; min-width: 34px; }
`;

const pagina = (corpo) => `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>${CSS}</style></head><body>${corpo}</body></html>`;

// Ajusta cada desenho ao espaço da prancha e mede o texto como ficou de verdade: devolve o 10º percentil do tamanho
// das letras (px na prancha), para que só sobrem rótulos legíveis. Marcadores de até 3 letras (número do passo,
// "alt", "sim") ficam de fora da medida.
const AJUSTAR = `(() => Array.from(document.querySelectorAll('.desenho')).map((caixa) => {
  const svg = caixa.querySelector('svg');
  // Notas da sequência: o Mermaid mede a caixa com outra fonte; alarga a caixa até caber o texto desenhado
  svg.querySelectorAll('rect.note').forEach((r) => {
    const t = r.parentNode.querySelector('text.noteText');
    if (!t) return;
    const b = t.getBBox(), x = +r.getAttribute('x'), w = +r.getAttribute('width');
    const ini = Math.min(x, b.x - 10), fim = Math.max(x + w, b.x + b.width + 10);
    r.setAttribute('x', ini); r.setAttribute('width', fim - ini);
  });
  const vb = svg.viewBox.baseVal;
  const w = vb && vb.width ? vb.width : svg.getBBox().width;
  const h = vb && vb.height ? vb.height : svg.getBBox().height;
  const escala = Math.min(caixa.clientWidth / w, caixa.clientHeight / h, ${AMPLIACAO_MAXIMA});
  svg.removeAttribute('style');
  svg.setAttribute('width', (w * escala).toFixed(1));
  svg.setAttribute('height', (h * escala).toFixed(1));
  const tamanhos = Array.from(svg.querySelectorAll('text, tspan, foreignObject span, foreignObject div, foreignObject p'))
    .filter((el) => Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim().length > 3))
    .map((el) => parseFloat(getComputedStyle(el).fontSize) * escala).sort((a, b) => a - b);
  const p10 = tamanhos.length ? tamanhos[Math.floor(tamanhos.length * 0.1)] : 0;
  return { escala, fonte: p10 };
}))()`;

mkdirSync(join(RAIZ, 'svg'), { recursive: true });
mkdirSync(join(RAIZ, 'pranchas'), { recursive: true });
const svgs = itens.map((item) => { process.stdout.write(`${item.id} `); return gerarSvg(item); });
process.stdout.write('\n');

const navegador = await chromium.launch({ executablePath: CHROMIUM, args: ['--no-sandbox'] });
const aba = await navegador.newPage({ viewport: { width: LARGURA, height: ALTURA }, deviceScaleFactor: ESCALA_PNG });
const relatorio = [];
for (const [i, item] of itens.entries()) {
  await aba.setContent(pagina(prancha(item, svgs[i], i + 3, itens.length + 2)), { waitUntil: 'load' });
  await aba.evaluate(() => document.fonts.ready);
  const [{ escala, fonte: medida }] = await aba.evaluate(AJUSTAR);
  const fonte = +medida.toFixed(1);
  relatorio.push({ id: item.id, arquivo: item.arquivo, titulo: item.titulo, escala: +escala.toFixed(3), fonte_px: fonte, ok: fonte >= FONTE_MINIMA });
  await aba.screenshot({ path: join(RAIZ, 'pranchas', `${item.arquivo}.png`) });
}

// Caderno em PDF (vetorial): capa, sumário e uma prancha por página
if (!SO.length) {
const capa = `<section class="prancha capa"><p style="letter-spacing:.12em;text-transform:uppercase;font-size:13px">Documentação técnica</p>
  <h1>Cadrius · Caderno de Arquitetura</h1>
  <p>Contexto, contêineres, componentes, implantação, fluxos, segurança e modelo de dados, no padrão C4, UML de sequência e diagramas entidade-relacionamento.</p>
  <p style="margin-top:28px;font-size:14px">Versão ${VERSAO} · ${itens.length} pranchas · gerado de docs/diagramas/fontes</p></section>`;
const sumario = `<section class="prancha sumario"><h2>Sumário</h2><ol>${itens.map((it, i) =>
  `<li><b>${it.id}</b><span>${esc(it.titulo.replace('Banco de dados: ', 'Banco: '))}</span><span style="margin-left:auto;color:#64748B">${i + 3}</span></li>`).join('')}</ol></section>`;
await aba.setContent(pagina(capa + sumario + itens.map((it, i) => prancha(it, svgs[i], i + 3, itens.length + 2)).join('')), { waitUntil: 'load' });
await aba.evaluate(() => document.fonts.ready);
await aba.evaluate(AJUSTAR);
await aba.pdf({ path: join(RAIZ, 'CADERNO_DE_ARQUITETURA.pdf'), width: `${LARGURA}px`, height: `${ALTURA}px`, printBackground: true });
}
await navegador.close();

// Índice em Markdown (o GitHub mostra as pranchas na própria página)
if (!SO.length) {
  const grupos = [['A', 'Arquitetura (modelo C4)'], ['F', 'Fluxos'], ['S', 'Segurança e operação'], ['D', 'Banco de dados']];
  const md = [
    '# Cadrius: arquitetura e diagramas', '',
    `> Gerado por \`gerador/render.mjs\` em ${VERSAO}. Não edite à mão: mude \`fontes/\` ou \`gerador/catalogo.json\` e gere de novo.`, '',
    `- **Caderno em PDF:** [CADERNO_DE_ARQUITETURA.pdf](CADERNO_DE_ARQUITETURA.pdf) (${itens.length} pranchas, vetorial, para imprimir ou apresentar).`,
    '- **Padrão visual, pesquisa e regras:** [PADRAO_VISUAL.md](PADRAO_VISUAL.md).',
    '- **Formatos:** cada prancha está em `pranchas/` (PNG 3200×1800, com título e legenda) e `svg/` (só o desenho, vetorial).', '',
    '## Índice', '',
    ...grupos.flatMap(([letra, nome]) => [`**${nome}**`, '',
      ...itens.filter((it) => it.id[0] === letra).map((it) => `- [${it.id} · ${it.titulo}](#${it.id.toLowerCase()})`), '']),
    ...grupos.flatMap(([letra, nome]) => [`## ${nome}`, '',
      ...itens.filter((it) => it.id[0] === letra).flatMap((it) => {
        const ext = existsSync(join(RAIZ, 'fontes', `${it.arquivo}.dot`)) ? 'dot' : 'mmd';
        return [`<a id="${it.id.toLowerCase()}"></a>`, `### ${it.id} · ${it.titulo}`, '', `*${it.nivel}.* ${it.descricao}`, '',
          `![${it.id}: ${it.titulo}](pranchas/${it.arquivo}.png)`, '',
          `[SVG](svg/${it.arquivo}.svg) · [fonte](fontes/${it.arquivo}.${ext})`, ''];
      })]),
  ];
  writeFileSync(join(RAIZ, 'ARQUITETURA_E_DIAGRAMAS.md'), md.join('\n'));
}
if (!SO.length) writeFileSync(join(GER, 'legibilidade.json'), JSON.stringify(relatorio, null, 2) + '\n');
const ruins = relatorio.filter((r) => !r.ok);
for (const r of relatorio) console.log(`${r.ok ? 'ok  ' : 'RUIM'} ${r.id} fonte ${r.fonte_px}px (escala ${r.escala})`);
if (ruins.length) {
  console.error(`\n${ruins.length} prancha(s) com texto abaixo de ${FONTE_MINIMA}px: divida o diagrama.`);
  process.exit(1);
}
console.log(`\n${relatorio.length} pranchas legíveis.${SO.length ? '' : ' PDF: CADERNO_DE_ARQUITETURA.pdf'}`);
if (!SO.length && !existsSync(join(RAIZ, 'CADERNO_DE_ARQUITETURA.pdf'))) process.exit(1);
