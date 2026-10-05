"""Geração, aprovação e publicação de conteúdo (CAD-174).

Gerar: IA (quando a política do escritório permite; créditos ``marketing_content``) com o perfil do escritório, as regras do
canal e as regras da OAB no prompt; sem IA, um esqueleto por canal com [COMPLETAR]. Todo texto passa pelo verificador.
Publicar: Facebook e Instagram pela conexão Meta; os demais canais ficam no calendário com lembrete para publicar à mão.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, Field

from marketing import compliance
from marketing.models import ContentPiece

logger = logging.getLogger(__name__)
AUTO_CHANNELS = {'facebook', 'instagram'}
CHANNEL_SPEC = {
    'instagram': 'legenda de Instagram de até 1.800 caracteres, parágrafos curtos, 3 a 5 hashtags relevantes em português',
    'facebook': 'post de Facebook de até 1.200 caracteres, tom conversado e informativo',
    'linkedin': 'post de LinkedIn de 800 a 1.300 caracteres, gancho na 1ª linha, linguagem profissional',
    'blog': 'artigo de blog de 700 a 1.000 palavras com título SEO, intertítulos (##) e conclusão; sem jargão desnecessário',
    'google_business': 'novidade do Perfil da Empresa no Google de até 1.000 caracteres, sem telefone no texto',
    'newsletter': 'newsletter por e-mail com assunto, saudação, 3 blocos curtos e despedida',
    'video_curto': 'roteiro de vídeo curto (30 a 60 s): gancho, 3 pontos e encerramento, com indicações de cena entre colchetes',
}
OAB_RULES = ('Regras obrigatórias (Provimento 205/2021 da OAB): conteúdo informativo e sóbrio; NÃO prometa resultado; NÃO cite preço, '
             'desconto ou consulta gratuita; NÃO faça chamada para contratação imediata; NÃO se declare o melhor; NÃO cite clientes '
             'ou casos concretos; sem sensacionalismo. Pode convidar a "saber mais" de forma discreta.')
CADRIUS_RULES = ('Você escreve para a Cadrius, software jurídico com IA para escritórios de advocacia (prazos, publicações do DJEN, '
                 'documentos, automações com aprovação humana, LGPD). Público: advogados e gestores de escritório. Sem promessas '
                 'absolutas; use benefícios concretos; convide a testar grátis no site.')


class ContentSchema(BaseModel):
    titulo: str = Field(default='', description='Título ou assunto (blog/newsletter) ou primeira linha')
    texto: str = Field(description='O conteúdo completo pronto para revisão')
    hashtags: list[str] = Field(default_factory=list, description='Hashtags sem o #, quando o canal usa')
    sugestao_imagem: str = Field(default='', description='Descrição da imagem/arte ideal')


def skeleton(channel: str, theme: str, scope: str) -> dict:
    who = '[COMPLETAR: nome do escritório]' if scope == 'escritorio' else 'Cadrius'
    close = ('Este conteúdo é informativo e não substitui a análise de um advogado.' if scope == 'escritorio'
             else 'Teste o Cadrius gratuitamente em cadrius.ia.br.')
    body = {
        'blog': f'# {theme}\n\n[COMPLETAR: introdução em 2 frases — por que o tema importa]\n\n## O que diz a lei\n'
                '[COMPLETAR: explicação simples com a base legal]\n\n## Na prática\n[COMPLETAR: exemplo hipotético]\n\n'
                f'## Cuidados\n[COMPLETAR: prazos e documentos]\n\n{close}\n\n{who}',
        'newsletter': f'Assunto: {theme}\n\nOlá!\n\n[COMPLETAR: contexto]\n\n1. [COMPLETAR]\n2. [COMPLETAR]\n3. [COMPLETAR]\n\n{close}\n{who}',
        'video_curto': f'[CENA 1 — gancho] {theme}?\n[CENA 2] [COMPLETAR: ponto 1]\n[CENA 3] [COMPLETAR: ponto 2]\n'
                       f'[CENA 4] [COMPLETAR: ponto 3]\n[ENCERRAMENTO] {close}',
    }.get(channel, f'{theme}\n\n[COMPLETAR: explique em 3 frases simples]\n\n[COMPLETAR: um cuidado prático]\n\n{close}')
    return {'titulo': theme, 'texto': body, 'hashtags': [], 'sugestao_imagem': f'Arte sóbria com o título "{theme}"'}


def _few_shot(org, theme):
    from aigov.sanitize import wrap_untrusted
    from brain import memory
    from brain.models import MemoryItem
    try:
        found = memory.similar(org, theme, kind=MemoryItem.Kind.MARKETING_EXAMPLE, k=1)
    except Exception:  # noqa: BLE001
        return ''
    if not found:
        return ''
    return '\n\nExemplo de conteúdo já aprovado por este escritório (imite o estilo, não o tema):\n' + wrap_untrusted(found[0][1].text[:1500])


def _ai(org, user, channel, theme, brief, scope):
    """(dict, provedor, aviso). Escritório: governança do escritório + créditos. Cadrius: só o interruptor global de IA."""
    from aigov.guard import AIBlocked, get_policy, global_ai_enabled, run_guarded
    from documents.pipeline import Skip, pick_provider
    from extraction.ai_wrapper import extract_fields_from_text

    rules = OAB_RULES if scope == 'escritorio' else CADRIUS_RULES
    prompt = (f'Crie um {CHANNEL_SPEC.get(channel, "post")} em português do Brasil sobre o tema abaixo. {rules}')
    if scope == 'escritorio':
        from brain.profile import prompt_context
        prompt += prompt_context(org) + _few_shot(org, theme)
    text = f'TEMA: {theme}\nORIENTAÇÕES DO AUTOR: {brief or "nenhuma"}'
    try:
        if scope == 'escritorio':
            from billing.credit_weights import credits_for
            from billing.credits import check_credit_available, consume_credit
            provider = pick_provider(get_policy(org))
            weight = credits_for('marketing_content')
            if weight:
                ok, msg = check_credit_available(org, user_id=getattr(user, 'pk', None))
                if not ok:
                    raise Skip(msg)
            result = run_guarded(organization=org, user=user, kind='marketing', provider=provider, categories=[], input_text=text,
                                 fn=lambda: extract_fields_from_text(text, ContentSchema, prompt, provider=provider))
            if result and weight:
                consume_credit(org, user_id=getattr(user, 'pk', None), amount=weight)
        else:
            if not global_ai_enabled():
                raise Skip('IA desativada na plataforma.')
            import os
            provider = next((p for p in ('GROQ', 'GEMINI', 'OPENAI') if os.environ.get(f'{p}_API_KEY', '').strip()), None)
            if not provider:
                raise Skip('Nenhum provedor de IA configurado.')
            result = extract_fields_from_text(text, ContentSchema, prompt, provider=provider)
    except Skip as exc:
        return None, '', f'{exc} Esqueleto sem IA para você completar.'
    except AIBlocked as exc:
        return None, '', f'IA bloqueada pela política do escritório ({exc.message}). Esqueleto sem IA.'
    except Exception:  # noqa: BLE001
        logger.exception('Falha ao gerar conteúdo de marketing')
        return None, '', 'A IA falhou. Esqueleto sem IA para você completar.'
    if not result or not (result.get('texto') or '').strip():
        return None, '', 'A IA não devolveu texto. Esqueleto sem IA.'
    return result, provider, ''


def generate(*, scope, org, user, channel, theme, brief='', use_ai=True, campaign=None):
    data, provider, notice = (None, '', '')
    if use_ai:
        data, provider, notice = _ai(org, user, channel, theme, brief, scope)
    if data is None:
        data = skeleton(channel, theme, scope)
    tags = [t.strip().lstrip('#').replace(' ', '')[:40] for t in data.get('hashtags') or [] if str(t).strip()][:8]
    body = data['texto'].strip()
    piece = ContentPiece.objects.create(
        scope=scope, organization=org if scope == 'escritorio' else None, campaign=campaign, channel=channel, theme=theme[:200],
        title=(data.get('titulo') or theme)[:200], body=body, generated_body=body, hashtags=tags,
        image_hint=(data.get('sugestao_imagem') or '')[:500], ai_provider=provider, created_by=user,
        compliance=compliance.check(body + ' ' + ' '.join(tags), scope, channel))
    return piece, notice


def full_text(piece) -> str:
    tags = ' '.join(f'#{t}' for t in piece.hashtags or [])
    return f'{piece.body}\n\n{tags}'.strip() if tags and piece.channel in ('instagram', 'facebook', 'linkedin') else piece.body


def learn(piece, user):
    """Conteúdo aprovado: mede a edição (sinal) e guarda como exemplo de estilo do escritório."""
    if piece.scope != 'escritorio' or piece.organization is None:
        return
    try:
        from brain import feedback, memory
        from brain.models import MemoryItem
        if piece.generated_body:
            feedback.record_review(piece.organization, user, 'marketing', f'content:{piece.pk}', {'texto': piece.generated_body},
                                   {'texto': piece.body})
        MemoryItem.objects.filter(organization=piece.organization, source=f'content:{piece.pk}').delete()
        memory.remember(piece.organization, MemoryItem.Kind.MARKETING_EXAMPLE, piece.body[:3000], title=piece.theme[:160],
                        payload={'canal': piece.channel}, source=f'content:{piece.pk}', user=user)
    except Exception:  # noqa: BLE001
        logger.exception('Falha ao registrar aprendizado do conteúdo %s', piece.pk)


def _meta_creds(piece):
    if piece.scope == 'cadrius':
        creds = {'page_id': getattr(settings, 'CADRIUS_META_PAGE_ID', ''), 'page_access_token': getattr(settings, 'CADRIUS_META_PAGE_TOKEN', ''),
                 'ig_user_id': getattr(settings, 'CADRIUS_META_IG_USER_ID', '')}
        return creds if creds['page_id'] and creds['page_access_token'] else None
    from integrations.services import org_connection
    conn = org_connection(piece.organization, 'META')
    return (conn.credentials or {}) if conn else None


def publish(piece) -> ContentPiece:
    """Publica agora (canais automáticos). Levanta ValueError com o motivo se não der."""
    from audit import service as audit
    from integrations.services import IntegrationError, meta_publish

    if piece.channel not in AUTO_CHANNELS:
        raise ValueError('Este canal não tem publicação automática: publique pelo app e marque como publicado.')
    creds = _meta_creds(piece)
    if not creds:
        raise ValueError('Conecte o Facebook/Instagram (Meta) em Integrações para publicar automaticamente.')
    try:
        ext = meta_publish(creds, piece.channel, full_text(piece), image_url=piece.image_url)
    except IntegrationError as exc:
        piece.status, piece.publish_error = ContentPiece.Status.FAILED, str(exc)[:300]
        piece.save(update_fields=['status', 'publish_error', 'updated_at'])
        raise ValueError(str(exc)) from exc
    piece.status, piece.external_id, piece.published_at, piece.publish_error = ContentPiece.Status.PUBLISHED, ext[:120], timezone.now(), ''
    piece.save(update_fields=['status', 'external_id', 'published_at', 'publish_error', 'updated_at'])
    audit.log('marketing.content_published', actor_type='system', organization=piece.organization, target=piece,
              changes={'canal': piece.channel, 'escopo': piece.scope})
    return piece


def publish_due(now=None) -> dict:
    """Comando a cada 15 min: publica o que venceu (Meta) e lembra de publicar à mão nos outros canais."""
    now = now or timezone.now()
    out = {'publicados': 0, 'falhas': 0, 'lembretes': 0}
    for piece in ContentPiece.objects.filter(status=ContentPiece.Status.SCHEDULED, scheduled_at__lte=now).select_related('organization')[:200]:
        if piece.channel in AUTO_CHANNELS and _meta_creds(piece):
            try:
                publish(piece)
                out['publicados'] += 1
            except ValueError:
                out['falhas'] += 1
            continue
        if piece.scope == 'escritorio' and not piece.publish_error:
            from notifications.models import Notification
            from notifications.services import notify
            notify(type=Notification.Type.AUTOMACAO, title='Hora de publicar um conteúdo', organization=piece.organization,
                   description=f'{piece.get_channel_display()}: {piece.title[:80]}', origem='Marketing', acao='Publicar',
                   action_label='Abrir marketing', link='/marketing', actor_id=piece.created_by_id, dedupe_key=f'mkt-{piece.pk}')
            piece.publish_error = 'Publique pelo app do canal e marque como publicado.'
            piece.save(update_fields=['publish_error', 'updated_at'])
            out['lembretes'] += 1
    return out
