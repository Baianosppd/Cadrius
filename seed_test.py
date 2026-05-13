import os
import django
from django.utils import timezone

# 1. Carrega o ambiente do Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cadrius.settings')
django.setup()

from django.contrib.auth import get_user_model
from billing.models import SubscriptionPlan
from accounts.models import Organization, OrganizationMembership
from extraction.models import ExtractionProfile
from workflows.models import Workflow, Trigger, Action, ExecutionLog
from integrations.models import AppConnection
from emails.models import MailBox, EmailMessage

# Importa a função central que acabámos de construir!
from tasks.tasks import process_email 

User = get_user_model()

print("\n🔥 INICIANDO O TESTE DE FOGO END-TO-END 🔥\n")

# ==========================================
# FASE 1: FUNDAÇÃO B2B (Escritório e Assinatura)
# ==========================================
plan, _ = SubscriptionPlan.objects.get_or_create(
    tier='PRO', defaults={'name': 'Plano Pro', 'price_brl': 199.00, 'max_ai_extractions': 1000}
)

org, _ = Organization.objects.get_or_create(
    cnpj='11.111.111/0001-11', defaults={'name': 'Machado & Dutra Advogados', 'plan': plan}
)

user, _ = User.objects.get_or_create(
    username='admin_teste@cadrius.com', 
    defaults={'email': 'admin_teste@cadrius.com', 'password': '123'}
)

OrganizationMembership.objects.get_or_create(user=user, organization=org, role='OWNER')
print("✅ Fundação (Tenant) criada.")

# ==========================================
# FASE 2: O CÉREBRO (Perfil de Extração IA)
# ==========================================
profile, _ = ExtractionProfile.objects.get_or_create(
    name='Leitor de Despachos (Goiás)',
    user=user,
    defaults={
        'ai_provider': 'OPENAI', # O motor escolhido
        'pydantic_schema_name': 'ProcessoJuridicoSchema',
        'system_prompt_template': 'Extraia os dados deste despacho preenchendo o schema com precisão clínica.'
    }
)
print("🧠 Cérebro (Prompt e Schema Pydantic) configurado.")

# ==========================================
# FASE 3: OS MÚSCULOS E NERVOS (Workflow, Gatilho e Ação)
# ==========================================
workflow, _ = Workflow.objects.get_or_create(
    name='Alerta de Prazo no WhatsApp',
    organization=org,
    defaults={'is_active': True}
)

conn, _ = AppConnection.objects.get_or_create(
    name='WhatsApp Evolution', user=user, defaults={'app_name': 'WHATSAPP'}
)

Trigger.objects.get_or_create(
    workflow=workflow, connection=conn, defaults={'event_type': 'novo_email'}
)

Action.objects.get_or_create(
    workflow=workflow,
    defaults={
        'action_type': 'WHATSAPP_EVOLUTION',
        # Repara na injeção das variáveis {{chave}} no template!
        'payload_template': '{"number": "5562999999999", "text": "🤖 *Cadrius AI Informa*\\n\\nProcesso: {{numero_processo}}\\nResumo: {{resumo_movimentacao}}\\n🚨 *Prazo*: {{prazo_fatal}}\\n💡 Sugestão: {{sugestao_proximo_passo}}"}'
    }
)
print("⚙️ Orquestrador (Workflow e Template Dinâmico) preparado.")

# ==========================================
# FASE 4: O EVENTO (Chegada do E-mail)
# ==========================================
mailbox, _ = MailBox.objects.get_or_create(
    name='Caixa de Publicações', user=user, defaults={'imap_host': 'tjgo.jus.br', 'username': 'tjgo', 'password': '123'}
)

texto_email = """
TRIBUNAL DE JUSTIÇA DO ESTADO DE GOIÁS
Processo nº: 0012345-67.2025.8.09.0051
Ação: Procedimento Comum Cível
DESPACHO:
Intime-se a parte autora para apresentar réplica à contestação no prazo fatal de 15 dias.
Goiânia, 11 de Abril de 2026.
"""

email_msg = EmailMessage.objects.create(
    mailbox=mailbox,
    message_id=f"msg_teste_{timezone.now().timestamp()}",
    subject="Nova Intimação - TJGO",
    sender="publicacoes@tjgo.jus.br",
    received_at=timezone.now(),
    body_text=texto_email
)
print(f"📧 E-mail {email_msg.id} recebido na caixa. A enviar para o processamento assíncrono...\n")

# ==========================================
# FASE 5: A IGNIÇÃO (Execução Síncrona para Teste)
# ==========================================
print("--------------------------------------------------")
# Chamamos a função diretamente para ver o que acontece em tempo real
process_email(email_id=email_msg.id, profile_id=profile.id, workflow_id=workflow.id)
print("--------------------------------------------------\n")

# Validamos os registos finais no banco
exec_log = ExecutionLog.objects.filter(workflow=workflow).order_by('-created_at').first()
if exec_log:
    print(f"📊 Relatório Final da Operação: Status do Disparo = {exec_log.status}")
    if exec_log.error_message:
        print(f"⚠️ Erro Registado: {exec_log.error_message}")
else:
    print("⚠️ Nenhum log de execução foi gerado. Algo falhou na orquestração.")

print("\n🚀 Fim do Teste de Fogo.")