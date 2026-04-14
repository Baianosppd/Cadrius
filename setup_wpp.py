import os
import django
import requests
import time

# Inicializa o Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cadrius.settings')
django.setup()

from accounts.models import Organization

org = Organization.objects.get(cnpj='11.111.111/0001-11')
instance_name = f"instancia_org_{org.id}"

URL = "http://evolution-api:8080"
API_KEY = "cadrius_mestre_secreto_123"
HEADERS = {"apikey": API_KEY, "Content-Type": "application/json"}

print(f"\n🗑️ 1. A limpar a sessão fantasma ({instance_name})...")
requests.delete(f"{URL}/instance/delete/{instance_name}", headers=HEADERS)
time.sleep(2)

print(f"🔌 2. A criar a instância e a ligar o motor do WhatsApp...")
requests.post(
    f"{URL}/instance/create",
    headers=HEADERS,
    json={"instanceName": instance_name, "integration": "WHATSAPP-BAILEYS"}
)

# O Segredo: Esperar que o motor Baileys inicie internamente antes de pedir a imagem
print("⏳ A aguardar 3 segundos para o gerador de QR Code aquecer...")
time.sleep(3)

print("📸 3. A pedir a imagem do QR Code...")
try:
    # No Evolution v2, este é o endpoint correto para forçar o retorno do QR Code
    response = requests.get(f"{URL}/instance/connect/{instance_name}", headers=HEADERS)
    data = response.json()
    
    # Procura a base64 diretamente na resposta
    base64_img = data.get('base64', '')
    
    if base64_img:
        html_content = f"""
        <html>
        <body style="display:flex; justify-content:center; align-items:center; height:100vh; background:#0f172a; color:white; font-family:sans-serif; flex-direction:column;">
            <h1>Cadrius AI - Leitura de WhatsApp</h1>
            <p>Abre o teu WhatsApp > Dispositivos Ligados > Ligar um Dispositivo</p>
            <div style="background:white; padding:20px; border-radius:10px;">
                <img src="{base64_img}" alt="QR Code WhatsApp" />
            </div>
        </body>
        </html>
        """
        with open('qrcode.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        print("✅ SUCESSO! Ficheiro 'qrcode.html' gerado.")
        print("👉 Abre-o no navegador e escaneia rápido!")
    else:
        print(f"⚠️ Não veio imagem. Resposta da API: {data}")

except Exception as e:
    print(f"❌ Erro ao puxar o QR Code: {e}")