"""Adicional "Estúdio de mídia com IA" (CAD-231).

- **Plano Enterprise:** já inclui o adicional.
- **Demais planos pagos (e o teste):** o dono ou administrador contrata pelo Stripe (assinatura mensal separada da do
  plano), ou a Gestão libera como cortesia, com ou sem prazo.
- **Consumo:** imagens e vídeos descontam créditos de IA, com peso próprio (`marketing_image` e `marketing_video`). O
  adicional libera o recurso; os créditos medem o uso.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils import timezone

INCLUDED_TIERS = {'ENTERPRISE'}


def price_brl() -> Decimal:
    return Decimal(str(getattr(settings, 'MEDIA_ADDON_PRICE_BRL', '149.00')))


def _addon(org):
    from billing.models import MediaAddon
    return MediaAddon.objects.filter(organization=org).first()


def included_in_plan(org) -> bool:
    return bool(org and org.plan_id and org.plan.tier in INCLUDED_TIERS)


def media_ai_enabled(org, now=None) -> bool:
    """Pode gerar imagem/vídeo com IA? (incluído no plano ou adicional ativo e dentro do prazo)."""
    if org is None:
        return False
    if included_in_plan(org):
        return True
    a = _addon(org)
    if a is None or not a.active:
        return False
    return a.ends_at is None or a.ends_at > (now or timezone.now())


def status(org) -> dict:
    a = _addon(org)
    return {
        'ativo': media_ai_enabled(org),
        'incluido_no_plano': included_in_plan(org),
        'origem': 'plano' if included_in_plan(org) else (a.source if a and a.active else ''),
        'termina_em': a.ends_at if a and a.active else None,
        'preco': str(price_brl()),
        'pode_contratar': not included_in_plan(org),
        'recursos': ['Imagens com IA (Gemini "Nano Banana")', 'Vídeos curtos com IA (Gemini Veo)',
                     'Usar suas fotos como referência na geração'],
    }


def activate(org, *, source, subscription_id='', session_id='', ends_at=None):
    from billing.models import MediaAddon
    a, _ = MediaAddon.objects.get_or_create(organization=org)
    a.active, a.source, a.ends_at = True, source, ends_at
    a.started_at = a.started_at or timezone.now()
    if subscription_id:
        a.stripe_subscription_id = subscription_id
    if session_id:
        a.stripe_session_id = session_id
    a.save()
    return a


def deactivate(org):
    a = _addon(org)
    if a and a.active:
        a.active = False
        a.save(update_fields=['active', 'updated_at'])
    return a
