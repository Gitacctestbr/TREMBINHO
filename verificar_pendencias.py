"""
TREMBINHO - Gatilho de Pendências (Cron)
====================================================
Busca as tarefas e leads do dia no Notion e dispara 
o relatório via Telegram para o SDR.
"""

import argparse
from datetime import datetime
from trembinho.notion import listar_itens_no_notion
from trembinho.notificador import enviar_mensagem_telegram, processar_fila_retry

def limpar_retorno_notion(texto_notion, tipo_icone):
    """Limpa a string crua do Notion para ficar elegante no Telegram."""
    if "Nenhum item encontrado" in texto_notion:
        return "<i>Tudo limpo por aqui!</i>\n"
    
    linhas_limpas = ""
    for linha in texto_notion.split('\n'):
        if linha.strip():
            # Extrai apenas o nome e o status, ignorando a data repetida
            partes = linha.split(" | Data:")
            if partes:
                texto = partes[0].replace("- [Tarefa] ", f"{tipo_icone} ").replace("- [Lead] ", f"{tipo_icone} ")
                linhas_limpas += f"{texto}\n"
    return linhas_limpas

def main():
    # Setup de argumentos de linha de comando
    parser = argparse.ArgumentParser(description="Disparador de pendências do Trembinho")
    parser.add_argument("--horario", choices=["manha", "tarde", "fim"], required=True, help="Momento do dia para o template")
    args = parser.parse_args()

    print("🚂 Iniciando verificação de pipeline...")
    
    # 1. Tenta limpar a fila de erros passados (Blindagem)
    processar_fila_retry()

    # 2. Puxa os dados de HOJE
    hoje = datetime.now().strftime("%Y-%m-%d")
    tarefas_hoje = listar_itens_no_notion(tipo="Tarefa", status="Aberto", data_inicio=hoje, data_fim=hoje)
    leads_hoje = listar_itens_no_notion(tipo="Lead", status="Aberto", data_inicio=hoje, data_fim=hoje)

    # 3. Escolhe o Copy (Texto) com base no horário
    if args.horario == "manha":
        saudacao = "🌅 <b>BOM DIA, CHEFE!</b> Golden Hour batendo na porta."
        fechamento = "Acelera esse SPIN Selling e bora qualificar!"
    elif args.horario == "tarde":
        saudacao = "☕ <b>BOA TARDE!</b> Resumo do front de batalha:"
        fechamento = "Ainda dá tempo de aplicar um BANT nesses contatos."
    else:
        saudacao = "🌙 <b>FIM DE EXPEDIENTE!</b> O que ficou pra trás:"
        fechamento = "Atualiza o CRM que amanhã a guerra continua."

    # 4. Monta a mensagem em HTML
    mensagem = f"{saudacao}\n\n"
    
    mensagem += "🎯 <b>SUAS TAREFAS DE HOJE:</b>\n"
    mensagem += limpar_retorno_notion(tarefas_hoje, "👉")
    
    mensagem += "\n👥 <b>LEADS ABERTOS:</b>\n"
    mensagem += limpar_retorno_notion(leads_hoje, "👤")
    
    mensagem += f"\n🚂 <i>{fechamento}</i>"

    # 5. Dispara
    enviar_mensagem_telegram(mensagem)

if __name__ == "__main__":
    main()