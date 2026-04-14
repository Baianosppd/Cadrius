import stripe
import logging
from django.conf import settings
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.models import Organization
from billing.models import SubscriptionPlan

logger = logging.getLogger(__name__)

# Configura a chave secreta do Stripe
stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', 'sk_test_chave_falsa_para_ja')

class CreateCheckoutSessionView(APIView):
    """
    O Front-end chama isto quando o cliente clica em "Assinar Plano Pro".
    Devolvemos o link da página de pagamento do Stripe.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # 1. Pega a organização do utilizador que fez o pedido
            user_org = request.user.organizationmembership_set.first().organization
            
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
                success_url=f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')}/dashboard?payment=success",
                cancel_url=f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')}/planos?payment=cancelled",
            )

            return Response({'checkout_url': checkout_session.url}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Erro ao criar sessão de checkout: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

        # 1. Valida se o pedido veio MESMO do Stripe (Segurança)
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        except ValueError:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
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
                    logger.info(f"💰 Pagamento confirmado para a Org {org.name}!")
                except Organization.DoesNotExist:
                    pass

        # 3. Lida com o evento de Assinatura Cancelada / Cartão Recusado
        elif event['type'] == 'customer.subscription.deleted':
            # A lógica real seria buscar o customer_id, mas para simplificar a arquitetura inicial:
            logger.warning("🚨 Assinatura cancelada!")
            pass

        return HttpResponse(status=200)