from django.db.models.signals import pre_save
from django.dispatch import receiver

from audit import service as audit
from billing.models import PlanPriceHistory, SubscriptionPlan


@receiver(pre_save, sender=SubscriptionPlan)
def track_plan_changes(sender, instance, **kwargs):
    """Registra no histórico (e na trilha de auditoria) toda mudança de preço ou de créditos de um plano."""
    if not instance.pk:
        return
    old = SubscriptionPlan.objects.filter(pk=instance.pk).first()
    if old is None or (old.price_brl == instance.price_brl and old.max_ai_extractions == instance.max_ai_extractions):
        return
    from audit.context import get_context
    who = getattr(instance, '_changed_by', '') or get_context().actor_id or ''
    PlanPriceHistory.objects.create(plan=instance, old_price=old.price_brl, new_price=instance.price_brl,
                                    old_credits=old.max_ai_extractions, new_credits=instance.max_ai_extractions,
                                    changed_by=str(who)[:64])
    audit.log('billing.price_changed', actor_type='admin', target=instance,
              changes={'price': [str(old.price_brl), str(instance.price_brl)],
                       'credits': [old.max_ai_extractions, instance.max_ai_extractions]})
