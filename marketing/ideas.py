"""Ideias de pauta (CAD-174): datas do calendário jurídico/cívico + temas sempre úteis por área + ideias da Cadrius.

Sem IA: funciona para todo escritório. Os temas são explicativos (o que o Provimento 205/2021 incentiva: informar, não captar).
"""
from __future__ import annotations

from datetime import date

# (mês, dia, data, tema sugerido, áreas relacionadas — vazio = todas)
DATES = [
    (1, 24, 'Dia Nacional dos Aposentados', 'O que muda na aposentadoria por idade e por tempo de contribuição', ['previdenciario']),
    (3, 8, 'Dia Internacional da Mulher', 'Direitos da mulher no trabalho e na família: o que a lei garante', ['trabalhista', 'familia']),
    (3, 15, 'Dia do Consumidor', 'Produto com defeito: prazos para reclamar segundo o CDC', ['consumidor', 'civel']),
    (4, 7, 'Dia Mundial da Saúde', 'Plano de saúde negou cobertura? Entenda seus direitos', ['saude', 'consumidor']),
    (5, 1, 'Dia do Trabalho', 'Direitos básicos do trabalhador: férias, 13º e FGTS', ['trabalhista']),
    (5, 15, 'Dia Internacional da Família', 'Guarda compartilhada: como funciona na prática', ['familia']),
    (6, 5, 'Dia do Meio Ambiente', 'Responsabilidade ambiental de empresas: o básico', ['empresarial', 'administrativo']),
    (7, 13, 'Aniversário do ECA', 'Pensão alimentícia: quem tem direito e como é calculada', ['familia']),
    (8, 7, 'Aniversário da Lei Maria da Penha', 'Medidas protetivas: o que são e como pedir', ['familia', 'criminal']),
    (8, 11, 'Dia do Advogado', 'Como funciona o trabalho de um advogado e quando procurar um', []),
    (9, 15, 'Dia do Cliente', 'Seus direitos como consumidor em compras pela internet', ['consumidor']),
    (10, 1, 'Dia Nacional do Idoso', 'Direitos da pessoa idosa: prioridade, benefícios e proteção', ['previdenciario', 'familia']),
    (10, 5, 'Aniversário da Constituição', 'Direitos fundamentais que você usa no dia a dia', []),
    (11, 20, 'Dia da Consciência Negra', 'Discriminação no trabalho: o que a lei prevê', ['trabalhista', 'criminal']),
    (12, 10, 'Dia dos Direitos Humanos', 'Direitos humanos no cotidiano: exemplos práticos', []),
    (12, 20, 'Recesso forense', 'Recesso do Judiciário: o que acontece com os prazos (CPC art. 220)', []),
]
EVERGREEN = {
    'trabalhista': ['Demissão sem justa causa: o que você recebe', 'Horas extras: como são calculadas', 'Rescisão indireta: quando cabe'],
    'previdenciario': ['Como pedir o BPC/LOAS', 'Auxílio por incapacidade: passo a passo', 'Revisão de benefício: quando vale a pena'],
    'familia': ['Divórcio consensual em cartório: requisitos', 'Inventário extrajudicial: quando é possível', 'União estável x casamento'],
    'consumidor': ['Cobrança indevida: devolução em dobro', 'Voo atrasado ou cancelado: direitos do passageiro', 'Negativação indevida'],
    'civel': ['Contrato de aluguel: direitos do inquilino', 'Prescrição: prazos para cobrar uma dívida', 'Danos morais: quando cabem'],
    'tributario': ['Como contestar uma execução fiscal', 'Parcelamentos e transação tributária', 'Restituição de tributos pagos a mais'],
    'empresarial': ['Contrato social: cláusulas essenciais', 'Recuperação judicial: visão geral', 'Proteção de marca: como registrar'],
    'criminal': ['Direitos de quem é abordado pela polícia', 'Audiência de custódia: o que é', 'Medidas cautelares diversas da prisão'],
    'imobiliario': ['Usucapião: requisitos', 'Distrato de imóvel na planta', 'Despejo por falta de pagamento: prazos'],
    'administrativo': ['Concurso público: direitos do candidato', 'Mandado de segurança: quando usar', 'Licitações: noções básicas'],
    'bancario': ['Juros abusivos: como identificar', 'Golpe do Pix: o banco responde?', 'Superendividamento: a lei 14.181/21'],
    'saude': ['Reajuste abusivo do plano de saúde', 'Negativa de cirurgia: o que fazer', 'Tratamento fora do rol da ANS'],
}
CADRIUS_IDEAS = [
    ('Quanto tempo seu escritório perde com publicações?', 'Mostrar a caixa de publicações do DJEN com triagem e prazo sugerido.'),
    ('Prazo em dias úteis sem erro', 'Explicar a agenda forense (CPC 219/220/224, DJe) com um exemplo real de cálculo.'),
    ('LGPD no escritório de advocacia', 'Checklist prático: dados cifrados, consentimento por canal, trilha de auditoria.'),
    ('Automação que não envia nada sem você aprovar', 'Regras com simulação e aprovação humana (diferencial de confiança).'),
    ('Do documento à tarefa em 1 minuto', 'Vídeo curto: subir intimação → leitura → prazo na agenda.'),
    ('Marketing jurídico dentro do Provimento 205', 'Como o Cadrius ajuda a criar conteúdo informativo sem infringir a OAB.'),
    ('Webinar com subseção da OAB', 'Parceria: "Tecnologia e prazos" para jovens advogados (gera cadastros qualificados).'),
    ('Programa de indicação', 'Escritório indica outro → crédito de IA para os dois (sem desconto agressivo).'),
]


def upcoming_dates(today: date | None = None, days: int = 60, areas=None) -> list:
    today = today or date.today()
    out = []
    for year in (today.year, today.year + 1):
        for m, d, name, theme, rel in DATES:
            when = date(year, m, d)
            delta = (when - today).days
            if 0 <= delta <= days and (not rel or not areas or set(rel) & set(areas)):
                out.append({'data': when.isoformat(), 'ocasiao': name, 'tema': theme, 'areas': rel})
    return sorted(out, key=lambda x: x['data'])


def office_ideas(areas, today=None) -> dict:
    areas = [a for a in (areas or []) if a in EVERGREEN] or ['civel', 'consumidor']
    return {'datas': upcoming_dates(today, 60, areas),
            'temas': [{'area': a, 'tema': t} for a in areas for t in EVERGREEN[a]]}


def cadrius_ideas(today=None) -> dict:
    return {'datas': upcoming_dates(today, 60), 'temas': [{'tema': t, 'angulo': a} for t, a in CADRIUS_IDEAS]}
