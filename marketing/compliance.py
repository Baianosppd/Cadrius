"""Verificador de conteúdo (CAD-174).

Escritório: Provimento 205/2021 da OAB — marketing jurídico é permitido quando informativo, sóbrio e sem mercantilização, captação
de clientela, promessa de resultado ou autopromoção comparativa; impulsionamento pago só de conteúdo informativo. Também alerta
dados pessoais no texto (LGPD) e menção a clientes/casos (sigilo profissional).
Cadrius: publicidade comum (CDC/CONAR): sem promessas absolutas, sem dados pessoais.

É um apoio, não um parecer: alertas "alto" impedem agendar até a pessoa corrigir ou confirmar que revisou; a responsabilidade final
é de quem publica. Fontes: docs/PESQUISA_FASE_E.md.
"""
from __future__ import annotations

import re
import unicodedata

RULES_OAB = [
    ('alto', 'Promessa de resultado', r'\b(garant\w*|100 ?%|causa ganha|ganho certo|sucesso (garantido|certo)|resultado (garantido|certo)|vitória (certa|garantida))',
     'Não prometa resultado (Provimento 205/2021, art. 3º; CED art. 39). Fale do direito, não do desfecho.'),
    ('alto', 'Mercantilização / preço', r'\b(pre[cç]o|desconto|promo[cç][aã]o|gr[aá]tis|gratuit[ao]|consulta (gratuita|gr[aá]tis|free)|parcel\w+ (sem juros|em \d+)|valor(es)? (acess[ií]ve(l|is)|baix\w+)|black ?friday|oferta)',
     'Não divulgue preço, desconto ou gratuidade como atrativo (vedada a mercantilização).'),
    ('alto', 'Captação de clientela', r'(entre em contato (agora|j[aá])|chame no (whats|zap)|ligue (j[aá]|agora)|contrate (j[aá]|agora|nosso)|n[aã]o perca|[uú]ltimas vagas|clique (aqui|no link) e (contrate|agende)|agende (j[aá]|agora) sua)',
     'Evite chamada para contratação imediata. Use convite informativo (ex.: "saiba mais no site").'),
    ('alto', 'Autopromoção comparativa', r'\b(melhor(es)? (advogad\w+|escrit[oó]rio)|n[uú]mero 1|n[ºo°] ?1 em|o mais (experiente|premiado|procurado)|l[ií]der em|imbat[ií]vel)',
     'Não se compare nem se autoproclame o melhor (vedada a autopromoção).'),
    ('medio', 'Menção a cliente ou caso', r'\b(meu cliente|nosso cliente|ganhamos (para|o caso)|conseguimos para|caso (real|do cliente)|nossa vit[oó]ria)',
     'Não exponha clientes nem casos concretos (sigilo profissional; Provimento veda publicidade de casos).'),
    ('medio', 'Sensacionalismo', r'(!!+|\burgente\b|\babsurdo\b|\bchocante\b|\bvoc[eê] precisa saber agora\b)',
     'Mantenha tom sóbrio e discreto; evite sensacionalismo.'),
    ('baixo', 'Título de especialista', r'\bespecialista\b',
     'Use "especialista" apenas se houver título de especialização (pós-graduação) que você possa comprovar.'),
    ('baixo', 'Ostentação', r'\b(carr[aã]o|luxo|ostenta\w*|meu (iate|jatinho))\b', 'Evite ostentação de bens ligada à atividade.'),
]
RULES_CADRIUS = [
    ('alto', 'Promessa absoluta', r'\b(100 ?% (seguro|garantido)|garantimos (resultado|que voc[eê] (ganh|vence))|nunca mais perca)',
     'Evite promessas absolutas (CDC art. 37 e Código do CONAR). Prefira dados verificáveis.'),
    ('medio', 'Comparação com concorrente', r'\b(melhor que|superior (ao|à)|ao contr[aá]rio d[oa] (astrea|advbox|projuris))',
     'Comparação com concorrente precisa ser objetiva e comprovável (CONAR, art. 32).'),
]
PII = [
    ('alto', 'Dado pessoal (CPF)', r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b', 'Remova CPF do texto (LGPD).'),
    ('alto', 'Número de processo', r'\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b', 'Não cite processos concretos em conteúdo de marketing.'),
    ('medio', 'Telefone no texto', r'\(?\b\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b', 'Prefira o botão/link do perfil a telefone no texto.'),
]
LIMITS = {'instagram': 2200, 'facebook': 5000, 'linkedin': 3000, 'google_business': 1500, 'blog': 20000, 'newsletter': 10000,
          'video_curto': 2200}


def _fold(text: str) -> str:
    return unicodedata.normalize('NFC', text or '')


def check(text: str, scope: str = 'escritorio', channel: str = '') -> list:
    """Lista de alertas [{nivel, regra, trecho, sugestao}] — vazia = nada encontrado."""
    body = _fold(text)
    out = []
    for level, name, rx, tip in (RULES_OAB if scope == 'escritorio' else RULES_CADRIUS) + PII:
        m = re.search(rx, body, re.IGNORECASE)
        if m:
            out.append({'nivel': level, 'regra': name, 'trecho': m.group(0)[:80], 'sugestao': tip})
    limit = LIMITS.get(channel)
    if limit and len(body) > limit:
        out.append({'nivel': 'medio', 'regra': 'Tamanho', 'trecho': f'{len(body)} caracteres',
                    'sugestao': f'O canal aceita até {limit} caracteres.'})
    return out


def blocking(alerts) -> bool:
    return any(a.get('nivel') == 'alto' for a in alerts or [])
