import os
from dotenv import load_dotenv
from anthropic import Anthropic

# 1. Carrega as chaves de forma segura (igual ao seu main.py)
load_dotenv()

# 2. Inicializa o motor. Ele acha a chave sozinho pelo nome padrão ANTHROPIC_API_KEY.
client = Anthropic()

try:
    print("🔌 Conectando ao motor do Claude...")
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=500,
        messages=[
            {"role": "user", "content": "Aja como um assistente de rotina chamado Trembinho. Diga 'Teste concluído, estou online!' de forma breve."}
        ]
    )
    print("\n🧠 Resposta do Trembinho:")
    print(response.content[0].text)

except Exception as e:
    print(f"❌ Ocorreu um erro: {e}")