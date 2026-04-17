"""
TREMBINHO - Gatilho de Pendências (Cron)
====================================================
Busca as tarefas e leads do dia no Notion e dispara 
o relatório via Telegram para o SDR.

SPRINT 4 / PASSO 5.6.C - MIGRAÇÃO PRO NOVO CONTRATO:
- listar_itens_no_notion() agora devolve list[dict] em vez de string crua.
- Formatação dos bullets reutilizada do agente.py via _formatar_listagem_compacta().
- Copy narrativo "BOM DIA CHEFE" preservado intacto.
- Função limpar_retorno_notion() removida (não precisa mais parsear string).
"""

import argparse
from datetime import datetime
from trembinho.notion import listar_itens_no_notion
from trembinho.notificador import enviar_mensagem_telegram, processar_fila_retry
from trembinho.agente import _formatar_listagem_compacta


def main():
    # Setup de argumentos de linha de comando
    parser = argparse.ArgumentParser(description="Disparador de pendências do Trembinho")
    parser.add_argument("--horario", choices=["manha", "tarde", "fim"], required=True, help="Momento do dia para o template")
    args = parser.parse_args()

    print("🚂 Iniciando verificação de pipeline...")
    
    # 1. Tenta limpar a fila de erros passados (Blindagem)
    processar_fila_retry()

    # 2. Puxa os dados de HOJE (agora retorna list[dict])
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

    # 4. Monta a mensagem em HTML reutilizando o formatador do agente
    mensagem = f"{saudacao}\n\n"
    
    mensagem += "🎯 <b>SUAS TAREFAS DE HOJE:</b>\n"
    mensagem += _formatar_listagem_compacta(tarefas_hoje, vazio_fallback="<i>Tudo limpo por aqui!</i>")
    
    mensagem += "\n\n👥 <b>LEADS ABERTOS:</b>\n"
    mensagem += _formatar_listagem_compacta(leads_hoje, vazio_fallback="<i>Nenhum lead pendente.</i>")
    
    mensagem += f"\n\n🚂 <i>{fechamento}</i>"

    # 5. Dispara
    enviar_mensagem_telegram(mensagem)


if __name__ == "__main__":
    main()