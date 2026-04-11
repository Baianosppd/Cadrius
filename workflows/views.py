from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from .models import Workflow
from .serializers import WorkflowSerializer

class WorkflowViewSet(viewsets.ModelViewSet):
    """
    CRUD completo para o Front-end gerenciar as automações.
    """
    queryset = Workflow.objects.all().order_by('-created_at')
    serializer_class = WorkflowSerializer


from django.http import HttpResponse
# ... (mantenha os outros importes que já existem) ...

class WebhookReceiverView(APIView):
    """
    Gateway Universal: Recebe disparos da Evolution API (WhatsApp).
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'webhook'

    def post(self, request, connection_id):
        payload = request.data
        
        # A Evolution envia o tipo de evento no campo 'event'
        evento = payload.get('event')
        
        # Filtramos para logar apenas quando uma MENSAGEM chegar
        if evento == 'messages.upsert':
            dados_mensagem = payload.get('data', {})
            
            # Pega o número do remente e o texto (pode vir de vários campos dependendo se for texto puro ou resposta)
            numero_remetente = dados_mensagem.get('key', {}).get('remoteJid')
            
            # Tenta pegar a mensagem de texto simples
            mensagem = dados_mensagem.get('message', {})
            texto = mensagem.get('conversation') or mensagem.get('extendedTextMessage', {}).get('text')
            
            if numero_remetente and texto:
                print("\n=======================================")
                print(f" [WhatsApp Cadrius] Nova Mensagem!")
                print(f" Conexão ID: {connection_id}")
                print(f" De: {numero_remetente}")
                print(f" Texto: {texto}")
                print("=======================================\n")

        return Response({"status": "sucesso"}, status=status.HTTP_202_ACCEPTED)