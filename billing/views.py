import stripe
import logging
from django.conf import settings
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from audit import service as audit_service
from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from billing.models import SubscriptionPlan
from billing.serializers import SubscriptionPlanSerializer, current_plan_payload
from billing.promotions import PromotionError, ensure_stripe_coupon, validate_promotion
from billing.stripe_sync import apply_event
from billing.models import CreditPack
from billing.entitlements import ai_enabled

logger = logging.getLogger(__name__)

# Configura a chave secreta do Stripe
stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '') or None


class PlansListView(APIView):
    """
    GET /api/billing/plans/
    Planos disponíveis para exibição no perfil e upgrade (id numérico para checkout).
    """
    permission_classes = [AllowAny]

    def get(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True).order_by('price_brl', 'id')
        return Response(SubscriptionPlanSerializer(plans, many=True).data)


class CurrentPlanView(APIView):
    """
    GET /api/billing/plans/current/
    Plano atual do escritório do utilizador + outros planos disponíveis (card do Perfil).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = get_active_membership(request.user)
        if membership is None:
            return Response(
                {'detail': 'Utilizador sem organização ativa.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(current_plan_payload(membership.organization))


class CreateCheckoutSessionView(APIView):
    """
    O Front-end chama isto quando o cliente clica em "Assinar Plano Pro".
    Devolvemos o link da página de pagamento do Stripe.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        membership = get_active_membership(request.user)
        if membership is None:
            return Response(
                {'detail': 'Utilizador sem organização ativa.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            # 1. Pega a organização do utilizador que fez o pedido
            if membership.role not in MANAGE_TEAM_ROLES:
                return Response(
                    {'detail': 'Apenas donos ou administradores podem gerir a assinatura.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            user_org = membership.organization
            
            # 2. Pega o plano que ele quer assinar (vem no JSON do Front-end)
            plan_id = request.data.get('plan_id')
            plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
            if plan.price_brl <= 0:
                return Response({'detail': 'Este plano é gratuito: não há pagamento a fazer.'},
                                status=status.HTTP_400_BAD_REQUEST)

            # 2b. Cupom opcional: validado no servidor (período, plano, limite de usos, uma vez por escritório)
            promo, session_extra, promo_meta = None, {}, {}
            promo_code = (request.data.get('promo_code') or '').strip()
            if promo_code:
                try:
                    promo, _final = validate_promotion(promo_code, plan, user_org)
                except PromotionError as exc:
                    return Response({'detail': str(exc), 'code': 'invalid_promotion'}, status=status.HTTP_400_BAD_REQUEST)
                session_extra['discounts'] = [{'coupon': ensure_stripe_coupon(promo)}]
                promo_meta = {'promo_id': str(promo.pk)}

            # 3. Cria a sessão de Checkout no Stripe
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'brl',
                        'product_data': {
                            'name': f'Cadrius AI - {plan.name}',
                            'description': f'Até {plan.max_ai_extractions} extrações com IA por mês.',
                        },
                        'unit_amount': int(plan.price_brl * 100), # Stripe cobra em cêntimos
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                # Guardamos o ID da Organização nos metadados para sabermos quem pagou depois!
                client_reference_id=str(user_org.id),
                # O webhook só confia nestes metadados (gravados por nós), nunca em dados do navegador.
                metadata={'kind': 'subscription', 'plan_id': str(plan.pk), **promo_meta},
                subscription_data={'metadata': {'kind': 'subscription', 'plan_id': str(plan.pk), **promo_meta}},
                **session_extra,
                success_url=f"{settings.FRONTEND_URL}/dashboard?payment=success",
                cancel_url=f"{settings.FRONTEND_URL}/perfil?payment=cancelled",
            )

            audit_service.log('billing.checkout', organization=user_org,
                              changes={'plan_id': plan.pk, 'promotion': promo.code if promo else None})
            return Response({'checkout_url': checkout_session.url}, status=status.HTTP_200_OK)

        except SubscriptionPlan.DoesNotExist:
            return Response({'detail': 'Plano inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            # Não devolver str(e): vazava detalhes internos/da API do Stripe ao cliente.
            logger.exception("Erro ao criar sessão de checkout")
            return Response(
                {'detail': 'Não foi possível iniciar o pagamento. Tente novamente.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class StripeWebhookView(APIView):
    """
    O Stripe chama este endpoint silenciosamente (sem login) 
    para avisar se o cartão passou ou se a assinatura foi cancelada.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')

        event = None

        # Sem segredo configurado a assinatura seria validada contra '' (forjável por qualquer um).
        if not endpoint_secret:
            logger.error("STRIPE_WEBHOOK_SECRET não configurado; webhook recusado.")
            return HttpResponse(status=503)

        # 1. Valida se o pedido veio MESMO do Stripe (Segurança)
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        except ValueError:
            return HttpResponse(status=400)
        except stripe.SignatureVerificationError:
            return HttpResponse(status=400)

        # 2. Aplica o evento ao estado da assinatura (billing/stripe_sync.py): pagamento, renovação, falha, cancelamento, créditos.
        try:
            outcome = apply_event(event)
            logger.info("Stripe %s → %s", event['type'], outcome)
        except Exception:
            # 500 faz o Stripe reenviar (as operações são idempotentes)
            logger.exception("Falha ao processar evento do Stripe")
            return HttpResponse(status=500)

        return HttpResponse(status=200)


class CreditPacksView(APIView):
    """GET /api/billing/credit-packs/ — pacotes de créditos avulsos à venda."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        packs = CreditPack.objects.filter(is_active=True)
        return Response([{'id': p.pk, 'name': p.name, 'credits': p.credits, 'price': str(p.price_brl)} for p in packs])


class CreditPackCheckoutView(APIView):
    """POST /api/billing/credit-packs/checkout/ {pack_id} — só dono/administrador; devolve a URL do Stripe (pagamento único)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        membership = get_active_membership(request.user)
        if membership is None or membership.role not in MANAGE_TEAM_ROLES:
            return Response({'detail': 'Apenas donos ou administradores podem comprar créditos.'},
                            status=status.HTTP_403_FORBIDDEN)
        org = membership.organization
        if not ai_enabled(org):
            return Response({'detail': 'Regularize a assinatura antes de comprar créditos.'},
                            status=status.HTTP_400_BAD_REQUEST)
        pack = CreditPack.objects.filter(pk=request.data.get('pack_id'), is_active=True).first()
        if pack is None:
            return Response({'detail': 'Pacote inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{'price_data': {'currency': 'brl', 'unit_amount': int(pack.price_brl * 100),
                                            'product_data': {'name': f'Cadrius — {pack.name}',
                                                             'description': f'{pack.credits} créditos de IA (valem 12 meses).'}},
                             'quantity': 1}],
                mode='payment',
                client_reference_id=str(org.id),
                metadata={'kind': 'credit_pack', 'pack_id': str(pack.pk)},
                success_url=f"{settings.FRONTEND_URL}/dashboard?credits=success",
                cancel_url=f"{settings.FRONTEND_URL}/perfil?credits=cancelled",
            )
        except Exception:
            logger.exception('Erro ao criar checkout de créditos')
            return Response({'detail': 'Não foi possível iniciar o pagamento. Tente novamente.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        audit_service.log('billing.checkout', organization=org, changes={'credit_pack_id': pack.pk})
        return Response({'checkout_url': session.url})


class PromotionValidateView(APIView):
    """POST /api/billing/promotions/validate/ {plan_id, code} — prévia do desconto (a cobrança real é recalculada no checkout)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        membership = get_active_membership(request.user)
        if membership is None or membership.role not in MANAGE_TEAM_ROLES:
            return Response({'detail': 'Apenas donos ou administradores.'}, status=status.HTTP_403_FORBIDDEN)
        plan = SubscriptionPlan.objects.filter(pk=request.data.get('plan_id'), is_active=True).first()
        if plan is None:
            return Response({'detail': 'Plano inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            promo, final = validate_promotion(request.data.get('code'), plan, membership.organization)
        except PromotionError as exc:
            return Response({'valid': False, 'detail': str(exc)}, status=status.HTTP_200_OK)
        return Response({'valid': True, 'name': promo.name, 'duration': promo.duration, 'duration_months': promo.duration_months,
                         'original': str(plan.price_brl), 'discounted': str(final)})


class BillingNoticesView(APIView):
    """GET /api/billing/notices/ — informes do financeiro vigentes para o escritório (por plano e estado da assinatura)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Q
        from django.utils import timezone
        from billing.entitlements import effective_status
        from billing.models import BillingNotice
        membership = get_active_membership(request.user)
        if membership is None:
            return Response([])
        org, now = membership.organization, timezone.now()
        status_now = effective_status(org, now)
        qs = BillingNotice.objects.filter(is_active=True).filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now)) \
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
        out = []
        for n in qs:
            if n.audience_tiers and org.plan.tier not in n.audience_tiers:
                continue
            if n.audience_statuses and status_now not in n.audience_statuses:
                continue
            out.append({'id': n.pk, 'title': n.title, 'body': n.body, 'severity': n.severity})
        return Response(out)
