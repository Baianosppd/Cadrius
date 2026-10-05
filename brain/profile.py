"""Perfil do escritório e métricas de aprendizado (CAD-174).

``refresh_stats`` calcula, dos dados do próprio escritório, onde ele atua (tribunais, classes, tipos de documento) e sugere áreas;
``prompt_context`` devolve o trecho que entra nos prompts de minuta e marketing ("fale como este escritório fala");
``insights`` mede o aprendizado: taxa de aceite por tipo de ação, regras aprendidas, sugestões, tempo economizado estimado.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from brain.models import AIFeedback, AutomationSuggestion, MemoryItem, OfficeProfile, OfficeRule

AREAS = {
    'trabalhista': 'Trabalhista', 'previdenciario': 'Previdenciário', 'civel': 'Cível', 'familia': 'Família e sucessões',
    'consumidor': 'Consumidor', 'tributario': 'Tributário', 'empresarial': 'Empresarial', 'criminal': 'Criminal',
    'imobiliario': 'Imobiliário', 'administrativo': 'Administrativo', 'bancario': 'Bancário', 'saude': 'Saúde',
}
# palavra no tribunal/classe/tipo → área provável
HINTS = [('trt', 'trabalhista'), ('trabalh', 'trabalhista'), ('reclamação', 'trabalhista'), ('inss', 'previdenciario'),
         ('previd', 'previdenciario'), ('aposentad', 'previdenciario'), ('benefício', 'previdenciario'), ('aliment', 'familia'),
         ('divórcio', 'familia'), ('inventário', 'familia'), ('guarda', 'familia'), ('consumidor', 'consumidor'),
         ('juizado especial cível', 'consumidor'), ('execução fiscal', 'tributario'), ('tribut', 'tributario'),
         ('falência', 'empresarial'), ('recuperação judicial', 'empresarial'), ('penal', 'criminal'), ('criminal', 'criminal'),
         ('crime', 'criminal'), ('usucapião', 'imobiliario'), ('despejo', 'imobiliario'), ('locação', 'imobiliario'),
         ('mandado de segurança', 'administrativo'), ('improbidade', 'administrativo'), ('banco', 'bancario'),
         ('plano de saúde', 'saude'), ('procedimento comum', 'civel'), ('cível', 'civel')]
TONE_TEXT = {'formal': 'formal e técnico', 'proximo': 'próximo e acolhedor, sem perder a sobriedade', 'didatico': 'didático, em linguagem simples'}
MINUTES_SAVED = {'automation_run': 5, 'publication': 3, 'document': 4, 'draft': 20}


def get(org) -> OfficeProfile:
    profile, _ = OfficeProfile.objects.get_or_create(organization=org)
    return profile


def refresh_stats(org) -> OfficeProfile:
    from documents.models import DocumentExtraction
    from publications.models import Publication
    from research.models import MonitoredCase

    tribunais = Counter(t.upper() for t in MonitoredCase.objects.filter(organization=org).values_list('tribunal', flat=True) if t)
    tribunais.update(t.upper() for t in Publication.objects.filter(organization=org).values_list('tribunal', flat=True)[:2000] if t)
    classes = Counter(c for c in Publication.objects.filter(organization=org).exclude(classe='').values_list('classe', flat=True)[:2000])
    tipos = Counter()
    for ex in DocumentExtraction.objects.filter(document__organization=org, status=DocumentExtraction.Status.CONFIRMED).only('fields')[:300]:
        t = str((ex.fields or {}).get('tipo_documento') or '').strip()
        if t:
            tipos[t] += 1
    hints = Counter()
    for text, weight in [*tribunais.items(), *classes.items(), *tipos.items()]:
        low = text.lower()
        for needle, area in HINTS:
            if needle in low:
                hints[area] += weight
    profile = get(org)
    profile.auto_stats = {
        'tribunais': [{'nome': k, 'qtd': v} for k, v in tribunais.most_common(8)],
        'classes': [{'nome': k, 'qtd': v} for k, v in classes.most_common(8)],
        'tipos_documento': [{'nome': k, 'qtd': v} for k, v in tipos.most_common(8)],
        'areas_sugeridas': [a for a, _ in hints.most_common(4)],
        'calculado_em': timezone.now().isoformat(),
    }
    if not profile.areas and profile.auto_stats['areas_sugeridas']:
        profile.areas = profile.auto_stats['areas_sugeridas'][:3]
    profile.save()
    return profile


def prompt_context(org) -> str:
    """Trecho para os prompts. Só dados do perfil (nada de clientes/processos)."""
    p = OfficeProfile.objects.filter(organization=org).first()
    if p is None:
        return ''
    parts = []
    if p.areas:
        parts.append('Áreas de atuação: ' + ', '.join(AREAS.get(a, a) for a in p.areas) + '.')
    if p.audience:
        parts.append(f'Público atendido: {p.audience}.')
    if p.city:
        parts.append(f'Cidade: {p.city}.')
    parts.append(f'Tom de comunicação: {TONE_TEXT.get(p.tone, p.tone)}.')
    trib = [t['nome'] for t in (p.auto_stats or {}).get('tribunais', [])[:4]]
    if trib:
        parts.append('Tribunais mais frequentes: ' + ', '.join(trib) + '.')
    return '\n\nPerfil do escritório (use para ajustar o estilo; não invente fatos): ' + ' '.join(parts)


def insights(org, days=90) -> dict:
    from automations.models import RuleRun
    from minutas.models import Draft
    from publications.models import Publication

    since = timezone.now() - timedelta(days=days)
    rows = AIFeedback.objects.filter(organization=org, created_at__gte=since).values('action_kind', 'decision').annotate(n=Count('id'))
    by_kind = {}
    for r in rows:
        k = by_kind.setdefault(r['action_kind'], {'total': 0, 'approved': 0, 'edited': 0, 'rejected': 0, 'undone': 0})
        k[r['decision']] = r['n']
        k['total'] += r['n']
    for k in by_kind.values():
        k['taxa_aceite'] = round(100 * (k['approved'] + k['edited']) / k['total']) if k['total'] else None
        k['taxa_sem_edicao'] = round(100 * k['approved'] / k['total']) if k['total'] else None
    runs = RuleRun.objects.filter(organization=org, created_at__gte=since, status='success').count()
    pubs = Publication.objects.filter(organization=org, status='confirmada', reviewed_at__gte=since).count()
    drafts = Draft.objects.filter(organization=org, status='revisada', updated_at__gte=since).count()
    docs = AIFeedback.objects.filter(organization=org, created_at__gte=since, action_kind='document_extraction').count()
    minutes = (runs * MINUTES_SAVED['automation_run'] + pubs * MINUTES_SAVED['publication'] + docs * MINUTES_SAVED['document']
               + drafts * MINUTES_SAVED['draft'])
    sugg = dict(AutomationSuggestion.objects.filter(organization=org).values_list('status').annotate(n=Count('id')))
    memory = dict(MemoryItem.objects.filter(organization=org).values_list('kind').annotate(n=Count('id')))
    return {
        'periodo_dias': days, 'por_tipo': by_kind,
        'regras_aprendidas': OfficeRule.objects.filter(organization=org, status='active').count(),
        'regras_propostas': OfficeRule.objects.filter(organization=org, status='proposed').count(),
        'sugestoes': {'abertas': sugg.get('open', 0), 'aceitas': sugg.get('accepted', 0), 'dispensadas': sugg.get('dismissed', 0)},
        'memoria': memory,
        'volumes': {'automacoes': runs, 'publicacoes': pubs, 'documentos': docs, 'minutas': drafts},
        'tempo_economizado_min': minutes,
        'nota': 'Tempo economizado é uma estimativa (minutos médios por tarefa feita pelo Cadrius).',
    }
