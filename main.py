"""
TREMBINHO - Segundo Cérebro SDR
Arquivo de entrada: main.py
Versão: 1.0 - Estável com trava de confirmação
"""

from trembinho.config import carregar_configuracoes, validar_chave_gemini
from trembinho.agente import rodar_agente

def validar_chaves_notion(config):
    """Verifica se as chaves do Notion estão presentes no .env."""
    if not config.get("notion_api_key") or not config.get("notion_database_id"):
        print("❌ ERRO: Chaves do Notion (API Key ou Database ID) faltando no .env")
        return False
    return True

def main():
    """Ponto de entrada do Trembinho."""
    
    print("=" * 50)
    print("🧠 TREMBINHO - Segundo Cérebro SDR")
    print("=" * 50)
    
    config = carregar_configuracoes()
    
    if not (validar_chave_gemini(config) and validar_chaves_notion(config)):
        return
        
    print("✅ Configurações e chaves validadas.")
    print("🚀 Iniciando o chat com o Gemini...")
    print("=" * 50)
    
    # Inicia o loop de conversa com o agente
    rodar_agente(config["gemini_api_key"])
    
    print("\n" + "=" * 50)
    print("Encerrando o Trembinho. Boa sorte nas vendas!")
    print("=" * 50)

if __name__ == "__main__":
    main()