"""Regras de promoção (CAD-160): validar o cupom, calcular o preço com desconto e refletir no Stripe (Coupon)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F
from django.utils import timezone

from billing.models import Promotion, PromotionRedemption

MIN_CHARGE = Decimal('0.50')  # mínimo cobrável pelo Stripe em BRL


class PromotionError(Exception):
    """Mensagem segura para exibir ao usuário."""


def _money(value) -> Decimal:
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def discounted_price(promo: Promotion, price) -> Decimal:
    price = Decimal(price)
    if promo.kind == Promotion.Kind.TRIAL:
        return _money(price)
    if promo.kind == Promotion.Kind.PERCENT:
        return _money(price * (Decimal(100) - promo.value) / Decimal(100))
    return _money(price - promo.value)


def validate_promotion(code, plan, organization, now=None) -> tuple[Promotion, Decimal]:
    now = now or timezone.now()
    promo = Promotion.objects.filter(code=(code or '').strip().upper()).first()
    if promo is None or not promo.is_active:
        raise PromotionError('Cupom inválido ou inativo.')
    if (promo.starts_at and now < promo.starts_at) or (promo.ends_at and now > promo.ends_at):
        raise PromotionError('Este cupom não está no período de validade.')
    if promo.plan_tiers and plan.tier not in promo.plan_tiers:
        raise PromotionError('Este cupom não vale para o plano escolhido.')
    if promo.max_redemptions is not None and promo.redemptions_count >= promo.max_redemptions:
        raise PromotionError('Este cupom atingiu o limite de usos.')
    if organization is not None and PromotionRedemption.objects.filter(promotion=promo, organization=organization).exists():
        raise PromotionError('Este cupom já foi usado por este escritório.')
    final = discounted_price(promo, plan.price_brl)
    if promo.kind == Promotion.Kind.TRIAL:
        return promo, final
    if final < MIN_CHARGE:
        raise PromotionError('Este cupom deixaria o valor abaixo do mínimo cobrável.')
    return promo, final


def ensure_stripe_coupon(promo: Promotion) -> str:
    """Cria o Coupon no Stripe na primeira vez que o cupom é usado."""
    if promo.stripe_coupon_id:
        return promo.stripe_coupon_id
    import stripe
    params = {'name': promo.name[:40], 'duration': promo.duration,
              'metadata': {'cadrius_promotion': promo.code}}
    if promo.duration == Promotion.Duration.REPEATING:
        params['duration_in_months'] = promo.duration_months or 1
    if promo.kind == Promotion.Kind.PERCENT:
        params['percent_off'] = float(promo.value)
    else:
        params.update(amount_off=int(promo.value * 100), currency='brl')
    coupon = stripe.Coupon.create(**params)
    promo.stripe_coupon_id = coupon['id'] if not hasattr(coupon, 'id') else coupon.id
    promo.save(update_fields=['stripe_coupon_id'])
    return promo.stripe_coupon_id


def record_redemption(promo: Promotion, organization, session_id='') -> bool:
    """Idempotente: devolve True só na primeira vez (incrementa o contador de usos)."""
    _, created = PromotionRedemption.objects.get_or_create(
        promotion=promo, organization=organization, defaults={'stripe_session_id': session_id})
    if created:
        Promotion.objects.filter(pk=promo.pk).update(redemptions_count=F('redemptions_count') + 1)
    return created


MAX_TRIAL_EXTRA_DAYS = 90


def apply_trial_coupon(promo: Promotion, organization, actor=None) -> int:
    """Cupom de dias extras (CAD-224): estende o teste do escritório. Só vale durante o teste (ou no cadastro)."""
    from datetime import timedelta

    from audit import service as audit
    from billing.entitlements import TRIALING, effective_status
    if promo.kind != Promotion.Kind.TRIAL:
        raise PromotionError('Este cupom é de desconto: ele vale no pagamento do plano.')
    if effective_status(organization) != TRIALING:
        raise PromotionError('Cupom de dias extras vale só durante o período de teste.')
    days = max(1, min(int(promo.value), MAX_TRIAL_EXTRA_DAYS))
    if not record_redemption(promo, organization):
        raise PromotionError('Este cupom já foi usado por este escritório.')
    base = max(organization.trial_ends_at or timezone.now(), timezone.now())
    organization.trial_ends_at = base + timedelta(days=days)
    organization.save(update_fields=['trial_ends_at'])
    audit.log('billing.coupon_applied', actor=actor, organization=organization,
              changes={'cupom': promo.code, 'tipo': 'dias_extras', 'dias': days})
    return days


def reserve_at_signup(code: str, plan, organization, actor=None) -> dict:
    """Cupom informado no cadastro: dias extras aplicam na hora; desconto fica reservado para o 1º pagamento."""
    from audit import service as audit
    promo, final = validate_promotion(code, plan, organization)
    if promo.kind == Promotion.Kind.TRIAL:
        days = apply_trial_coupon(promo, organization, actor)
        return {'tipo': 'dias_extras', 'dias': days, 'codigo': promo.code}
    organization.pending_promotion = promo
    organization.save(update_fields=['pending_promotion'])
    audit.log('billing.coupon_applied', actor=actor, organization=organization,
              changes={'cupom': promo.code, 'tipo': 'desconto_reservado'})
    return {'tipo': 'desconto', 'codigo': promo.code, 'preco_com_desconto': str(final)}
