import stripe
import logging
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from accounts.models import Organization

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

@csrf_exempt  # Desativamos o CSRF apenas para esta rota, pois o Stripe não tem o nosso token
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    event = None

    try:
        # A magia da segurança: Valida a assinatura usando o segredo do webhook
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error("Webhook Error: Payload inválido")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error("Webhook Error: Assinatura inválida (Possível ataque!)")
        return HttpResponse(status=400)

    # 1. O CLIENTE PAGOU COM SUCESSO
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # O client_reference_id é injetado por nós quando geramos o link de pagamento
        org_id = session.get('client_reference_id') 

        if org_id:
            try:
                org = Organization.objects.get(id=org_id)
                # O dinheiro entrou? Ativamos o escritório imediatamente!
                org.is_active = True
                org.save()
                logger.info(f"✅ Escritório {org.name} ativado com sucesso após pagamento.")
            except Organization.DoesNotExist:
                logger.error(f"Organization ID {org_id} não encontrada após pagamento.")

    # 2. O PAGAMENTO MENSAL FALHOU (Cartão recusado / Boleto vencido)
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        # Lógica para suspender a conta ou enviar email de aviso
        logger.warning(f"⚠️ Pagamento falhou para a fatura {invoice.get('id')}")

    return HttpResponse(status=200) # Temos de responder 200 OK rápido para o Stripe não reenviar