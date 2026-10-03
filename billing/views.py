import stripe
import logging
from django.conf import settings
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from accounts.models import Organization
from audit import service as audit_service
from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from billing.models import SubscriptionPlan
from billing.serializers import SubscriptionPlanSerializer, current_plan_payload

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
            plan = SubscriptionPlan.objects.get(id=plan_id)

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
                success_url=f"{settings.FRONTEND_URL}/dashboard?payment=success",
                cancel_url=f"{settings.FRONTEND_URL}/perfil?payment=cancelled",
            )

            audit_service.log('billing.checkout', organization=user_org, changes={'plan_id': plan.pk})
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

        # 2. Lida com o evento de Pagamento Concluído
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            org_id = session.get('client_reference_id')
            
            if org_id:
                try:
                    org = Organization.objects.get(id=org_id)
                    org.is_active = True  # Liberta o acesso!
                    org.save()
                    audit_service.log('billing.payment_confirmed', actor_type='webhook', organization=org,
                                      reason='checkout.session.completed')
                    logger.info("Pagamento confirmado org_id=%s", org.id)
                except (Organization.DoesNotExist, ValueError):
                    logger.warning("Webhook Stripe com client_reference_id desconhecido.")

        # 3. Lida com o evento de Assinatura Cancelada / Cartão Recusado
        elif event['type'] == 'customer.subscription.deleted':
            # A lógica real seria buscar o customer_id, mas para simplificar a arquitetura inicial:
            logger.warning("🚨 Assinatura cancelada!")
            pass

        return HttpResponse(status=200)