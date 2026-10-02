import os
import django
import json

# 1. Inicia o ambiente Django para podermos aceder aos módulos internos
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cadrius.settings')
django.setup()

from extraction.ai_wrapper import extract_fields_from_text
from extraction.schemas import ProcessoJuridicoSchema


texto_juridico_mock = """
PUBLICAÇÃO: 2024-06-01
PROCESSO: 0001234-56.2024.8.26.0000
CLASSE: Ação de Indenização
ASSUNTO: Danos Morais
PARTES:
- Autor: João da Silva  
- Réu: Empresa XYZ Ltda
ADVOGADOS: jullio      
DESCRIÇÃO: O autor alega que sofreu danos morais devido a um incidente ocorrido em 2023, onde a empresa XYZ Ltda foi responsável por um acidente que resultou em lesões. O autor busca indenização pelos danos sofridos, incluindo despesas médicas e sofrimento emocional.
HISTÓRICO: O processo foi distribuído em 2024-01-15 e passou por uma audiência de conciliação em 2024-03-10, onde não houve acordo entre as partes. O réu apresentou contestação em 2024-04-05, negando as alegações do autor e apresentando sua versão dos fatos. O processo está atualmente aguardando a fase de instrução, onde serão ouvidas testemunhas e apresentadas provas documentais.
https://www.tjsp.jus.br/Download/Diario/2024/06/01/0001234-56.2024.8.26.0000.pdf

"""

prompt_instrucao = "Analise esta publicação do Diário de Justiça e extraia os metadados rigorosamente e simule envios para diferentes bancos de dados e fontes de comunicação."

print("\n🚀 [CADRIUS AI] A iniciar Teste de Extração B2B...\n")

# =====================================================================
# TESTE 1: OpenAI
# =====================================================================
print("🧠 A processar com OPENAI...")
try:
    resultado_openai = extract_fields_from_text(
        text=texto_juridico_mock,
        schema=ProcessoJuridicoSchema,
        prompt_template=prompt_instrucao,
        provider='OPENAI'  
    )
    
    if resultado_openai:
        print("✅ SUCESSO! JSON Retornado:\n")
        print(json.dumps(resultado_openai, indent=4, ensure_ascii=False))
    else:
        print("❌ Falha na extração.")
except Exception as e:
    print(f"⚠️ Erro ao contactar a API: {e}\n(Garante que tens a OPENAI_API_KEY no teu .env!)")
    
print("\n=====================================================================\n")

print("🧠 A processar com GROQ...")
try:
    resultado_groq = extract_fields_from_text(
        text=texto_juridico_mock,
        schema=ProcessoJuridicoSchema,
        prompt_template=prompt_instrucao,
        provider='GROQ'  
    )
    
    if resultado_groq:
        print("✅ SUCESSO! JSON Retornado:\n")
        print(json.dumps(resultado_groq, indent=4, ensure_ascii=False))
    else:
        print("❌ Falha na extração.")
except Exception as e:
    print(f"⚠️ Erro ao contactar a API: {e}\n(Garante que tens a GROQ_API_KEY no teu .env!)")
    
print("\n=====================================================================\n")


print("🧠 A processar com GEMINI...")
try:
    resultado_gemini = extract_fields_from_text(
        text=texto_juridico_mock,
        schema=ProcessoJuridicoSchema,
        prompt_template=prompt_instrucao,
        provider='GEMINI'  
    )
    
    if resultado_gemini:
        print("✅ SUCESSO! JSON Retornado:\n")
        print(json.dumps(resultado_gemini, indent=4, ensure_ascii=False))
    else:
        print("❌ Falha na extração.")
except Exception as e:
    print(f"⚠️ Erro ao contactar a API: {e}\n(Garante que tens a GEMINI_API_KEY no teu .env!)")
    
print("\n=====================================================================\n")