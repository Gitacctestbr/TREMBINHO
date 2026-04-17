"""
TREMBINHO - Gestão de Memória de Conversa (Sprint 4 / Passo 4)
===============================================================
Gerencia históricos de conversa isolados por chat_id para o canal Telegram.

ARQUITETURA:
- Dicionário {chat_id: [mensagens]} em memória (RAM, não persiste em disco).
- Janela deslizante: mantém system prompt + últimas N mensagens user/assistant
  para não estourar o num_ctx=8192 do Qwen em conversas longas.
- Comando /reset: zera histórico de um chat específico.
- Thread-safe via threading.Lock (protege cenários terminal+listener simultâneos).

DECISÕES DE DESIGN:
- Sem persistência: cada mensagem do SDR tende a ser autocontida no uso real.
  Se virar necessidade, plugamos SQLite num sprint futuro.
- System prompt SEMPRE preservado na janela deslizante (é a "alma" do bot).
- Reuso de criar_historico_novo() do agente.py — fonte única de verdade do
  system prompt.
"""

import threading
from trembinho.agente import criar_historico_novo

# -----------------------------------------------------------------------------
# Configuração da janela deslizante
# -----------------------------------------------------------------------------
# Máximo de mensagens user/assistant mantidas (além do system prompt fixo).
# 20 = 10 pares de troca, suficiente pra conversas de prospecção sem estourar
# o num_ctx=8192 do Qwen 14B.
JANELA_MAXIMA_MENSAGENS = 20


# -----------------------------------------------------------------------------
# Estado global (protegido por lock)
# -----------------------------------------------------------------------------
_historicos_por_chat = {}
_lock = threading.Lock()


# -----------------------------------------------------------------------------
# API pública
# -----------------------------------------------------------------------------
def obter_historico(chat_id):
    """
    Retorna o histórico de conversa de um chat_id.
    Se não existir, cria um novo com o system prompt injetado.
    
    Args:
        chat_id: identificador único do chat (int ou str).
    
    Returns:
        Lista de mensagens (role/content) pronta pra ser passada ao Ollama.
    """
    chave = str(chat_id)
    with _lock:
        if chave not in _historicos_por_chat:
            _historicos_por_chat[chave] = criar_historico_novo()
        return _historicos_por_chat[chave]


def salvar_historico(chat_id, historico_atualizado):
    """
    Persiste na memória (RAM) o histórico retornado pelo motor do agente,
    aplicando a janela deslizante para não estourar o contexto do Qwen.
    
    Args:
        chat_id: identificador único do chat.
        historico_atualizado: lista retornada por processar_mensagem().
    """
    chave = str(chat_id)
    with _lock:
        _historicos_por_chat[chave] = _aplicar_janela_deslizante(historico_atualizado)


def resetar_historico(chat_id):
    """
    Zera o histórico de um chat específico e regenera o system prompt.
    Usado pelo comando /reset no Telegram.
    
    Args:
        chat_id: identificador único do chat.
    
    Returns:
        True sempre (idempotente - reseta mesmo se não existia).
    """
    chave = str(chat_id)
    with _lock:
        _historicos_por_chat[chave] = criar_historico_novo()
    return True


def tamanho_historico(chat_id):
    """Retorna quantas mensagens existem no histórico (útil pra debug/logs)."""
    chave = str(chat_id)
    with _lock:
        return len(_historicos_por_chat.get(chave, []))


# -----------------------------------------------------------------------------
# Lógica da janela deslizante
# -----------------------------------------------------------------------------
def _aplicar_janela_deslizante(historico):
    """
    Mantém o system prompt (primeira mensagem) + últimas N mensagens.
    
    Por quê preservar o system: é a personalidade + contexto temporal do bot.
    Cortá-lo faria o Qwen "esquecer" que é o Trembinho e perder a data de hoje.
    """
    if len(historico) <= JANELA_MAXIMA_MENSAGENS + 1:
        # +1 porque o system prompt não conta na janela
        return historico

    # Separa o system (sempre o primeiro) do resto
    system_msg = historico[0]
    corpo = historico[1:]

    # Corta o corpo mantendo as últimas N mensagens
    corpo_recortado = corpo[-JANELA_MAXIMA_MENSAGENS:]

    return [system_msg] + corpo_recortado


# -----------------------------------------------------------------------------
# Bateria de teste - rode com: python -m trembinho.memoria
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("🧠 TREMBINHO - Teste do módulo memoria.py")
    print("=" * 60)

    chat_teste = "123456789"

    # Teste 1: histórico novo vem com system prompt
    h = obter_historico(chat_teste)
    print(f"✅ Histórico novo criado: {len(h)} mensagem(ns) (esperado: 1)")
    print(f"   Role da primeira mensagem: {h[0]['role']} (esperado: system)")
    assert len(h) == 1 and h[0]["role"] == "system", "Falha no histórico inicial!"

    # Teste 2: salvar e recuperar
    h.append({"role": "user", "content": "teste"})
    h.append({"role": "assistant", "content": "resposta"})
    salvar_historico(chat_teste, h)
    h2 = obter_historico(chat_teste)
    print(f"✅ Histórico persistido: {len(h2)} mensagens (esperado: 3)")
    assert len(h2) == 3, "Falha ao persistir histórico!"

    # Teste 3: janela deslizante
    # Injeta 30 mensagens fake
    h_grande = obter_historico(chat_teste)
    for i in range(30):
        h_grande.append({"role": "user", "content": f"msg {i}"})
        h_grande.append({"role": "assistant", "content": f"resp {i}"})
    salvar_historico(chat_teste, h_grande)
    h3 = obter_historico(chat_teste)
    esperado = JANELA_MAXIMA_MENSAGENS + 1  # +1 do system
    print(f"✅ Janela deslizante aplicada: {len(h3)} mensagens (esperado: {esperado})")
    assert len(h3) == esperado, f"Janela não cortou corretamente! Tem {len(h3)}, esperado {esperado}"
    assert h3[0]["role"] == "system", "System prompt foi perdido na janela!"

    # Teste 4: reset
    resetar_historico(chat_teste)
    h4 = obter_historico(chat_teste)
    print(f"✅ Reset executado: {len(h4)} mensagem(ns) (esperado: 1)")
    assert len(h4) == 1, "Reset não limpou o histórico!"

    # Teste 5: isolamento entre chats
    outro_chat = "999888777"
    h_outro = obter_historico(outro_chat)
    h_outro.append({"role": "user", "content": "mensagem de outro chat"})
    salvar_historico(outro_chat, h_outro)
    assert tamanho_historico(chat_teste) == 1, "Reset vazou entre chats!"
    assert tamanho_historico(outro_chat) == 2, "Chat novo não isolou corretamente!"
    print(f"✅ Isolamento entre chats: chat1={tamanho_historico(chat_teste)}, chat2={tamanho_historico(outro_chat)}")

    print("=" * 60)
    print("🎯 Todos os testes passaram. Memória pronta pro Passo 5.")