import os
import datetime
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

load_dotenv()
TOKEN = os.getenv("TOKEN")

# Estados para a criação do lembrete
NOME_LEMBRETE, HORARIO_LEMBRETE, ESCOLHA_FREQUENCIA, SELECAO_DIAS = range(4)
# Estado para a lógica de adiamento
AGUARDANDO_ADIAMENTO = 4
# Estados para a lógica de deleção
CONFIRMACAO_PARAR, AGUARDANDO_NUMERO_DELECAO = range(5, 7)

# Nomes dos dias para exibição
NOME_DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================


def gerar_teclado_dias(dias_selecionados):
    """Gera o teclado dinâmico com os dias da semana"""
    keyboard = []
    linha = []
    for i, dia in enumerate(NOME_DIAS):
        # Se o dia estiver na lista de selecionados, ganha um check
        texto_botao = f"✅ {dia}" if i in dias_selecionados else dia
        linha.append(InlineKeyboardButton(texto_botao, callback_data=f"dia_{i}"))

        # Quebra a linha a cada 3 botões para ficar bonito no celular
        if len(linha) == 3 or i == 6:
            keyboard.append(linha)
            linha = []

    # Adiciona o botão de confirmar no final
    keyboard.append(
        [InlineKeyboardButton("💾 Confirmar Dias", callback_data="confirmar_dias")]
    )
    return InlineKeyboardMarkup(keyboard)


# ==========================================
# FLUXO 1: CRIAÇÃO DO LEMBRETE
# ==========================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    primeiro_nome = update.effective_user.first_name

    await update.message.reply_text(
        f"Olá, {primeiro_nome}! O que você quer que eu te lembre?"
    )
    return NOME_LEMBRETE


async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nome"] = update.message.text
    await update.message.reply_text(
        f"Beleza, vou te lembrar de '{context.user_data['nome']}'.\n\n"
        "Que horas devo enviar o lembrete? (Digite no formato HH:MM, ex: 09:00 ou 19:30)"
    )
    return HORARIO_LEMBRETE


async def receber_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    horario_digitado = update.message.text

    try:
        hora, minuto = map(int, horario_digitado.split(":"))
        # Salvamos o horário na memória para usar depois de escolher os dias
        context.user_data["hora_obj"] = datetime.time(
            hour=hora,
            minute=minuto,
            tzinfo=datetime.timezone(datetime.timedelta(hours=-3)),
        )
        context.user_data["hora_str"] = horario_digitado

        # Pergunta a frequência
        keyboard = [
            [InlineKeyboardButton("🔄 Todos os dias", callback_data="freq_diario")],
            [
                InlineKeyboardButton(
                    "📅 Dias específicos", callback_data="freq_especifico"
                )
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Qual será a frequência desse lembrete?", reply_markup=reply_markup
        )
        return ESCOLHA_FREQUENCIA

    except ValueError:
        await update.message.reply_text(
            "Ops! Formato inválido. Tente novamente no formato HH:MM (ex: 09:00)."
        )
        return HORARIO_LEMBRETE


async def lidar_frequencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    nome_lembrete = context.user_data["nome"]
    hora_str = context.user_data["hora_str"]
    hora_obj = context.user_data["hora_obj"]
    chat_id = str(update.effective_chat.id)

    if query.data == "freq_diario":
        # Agenda para todos os dias (0 a 6)
        context.job_queue.run_daily(
            disparar_lembrete,
            time=hora_obj,
            days=(0, 1, 2, 3, 4, 5, 6),
            data={
                "chat_id": update.effective_chat.id,
                "nome": nome_lembrete,
                "hora_str": f"Todos os dias às {hora_str}",
            },
            name=chat_id,
        )
        await query.edit_message_text(
            f"✅ Feito! Lembrete '{nome_lembrete}' agendado para todos os dias às {hora_str}.\n\n"
            "⚠️ *Aviso:* Se você limpar o chat, os lembretes ativos serão perdidos!",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    elif query.data == "freq_especifico":
        # Inicia uma lista vazia para guardar os dias que ele vai selecionar
        context.user_data["dias_selecionados"] = []
        reply_markup = gerar_teclado_dias(context.user_data["dias_selecionados"])
        await query.edit_message_text(
            "Selecione os dias da semana:", reply_markup=reply_markup
        )
        return SELECAO_DIAS


async def lidar_selecao_dias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("dia_"):
        dia_index = int(query.data.split("_")[1])
        dias_selecionados = context.user_data["dias_selecionados"]

        # Se já estava selecionado, remove. Se não, adiciona (Toggle)
        if dia_index in dias_selecionados:
            dias_selecionados.remove(dia_index)
        else:
            dias_selecionados.append(dia_index)

        # Atualiza o teclado na mesma mensagem
        reply_markup = gerar_teclado_dias(dias_selecionados)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return SELECAO_DIAS

    elif query.data == "confirmar_dias":
        dias_selecionados = context.user_data.get("dias_selecionados", [])

        if not dias_selecionados:
            await query.message.reply_text(
                "Você precisa selecionar pelo menos um dia! Clique nos dias acima."
            )
            return SELECAO_DIAS

        # Finaliza e agenda
        nome_lembrete = context.user_data["nome"]
        hora_str = context.user_data["hora_str"]
        hora_obj = context.user_data["hora_obj"]
        chat_id = str(update.effective_chat.id)

        # Monta a string bonita para o /listar (ex: Seg, Qua, Sex)
        dias_selecionados.sort()
        nomes_dias_escolhidos = [NOME_DIAS[i] for i in dias_selecionados]
        string_dias = ", ".join(nomes_dias_escolhidos)

        context.job_queue.run_daily(
            disparar_lembrete,
            time=hora_obj,
            days=tuple(dias_selecionados),  # Passamos os dias específicos aqui!
            data={
                "chat_id": update.effective_chat.id,
                "nome": nome_lembrete,
                "hora_str": f"{string_dias} às {hora_str}",
            },
            name=chat_id,
        )

        await query.edit_message_text(
            f"✅ Feito! Lembrete '{nome_lembrete}' agendado para {string_dias} às {hora_str}.\n\n"
            "⚠️ *Aviso:* Se você limpar o chat, os lembretes ativos serão perdidos!",
            parse_mode="Markdown",
        )
        return ConversationHandler.END


# ==========================================
# FLUXO 2: LISTAR ALARMES
# ==========================================


async def listar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    jobs_atuais = context.job_queue.get_jobs_by_name(chat_id)

    if not jobs_atuais:
        await update.message.reply_text("📋 Não tem nenhum lembrete ativo no momento.")
        return

    mensagem = "📋 *Os seus lembretes ativos:*\n\n"
    for index, job in enumerate(jobs_atuais, 1):
        nome = job.data["nome"]
        hora = job.data.get("hora_str", "Horário pendente")
        mensagem += f"{index}. ⏰ *{nome}* - {hora}\n"

    await update.message.reply_text(mensagem, parse_mode="Markdown")


# ==========================================
# FLUXO 3: LÓGICA DE PARAR / EXCLUIR
# ==========================================


async def menu_parar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    jobs_atuais = context.job_queue.get_jobs_by_name(chat_id)

    if not jobs_atuais:
        await update.message.reply_text(
            "Você não tem nenhum lembrete ativo para parar."
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("💥 Apagar Tudo", callback_data="parar_tudo")],
        [
            InlineKeyboardButton(
                "🗑️ Apagar Específico", callback_data="parar_especifico"
            )
        ],
        [InlineKeyboardButton("❌ Cancelar Operação", callback_data="parar_cancelar")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "⚠️ Você entrou no menu de cancelamento.\nO que você deseja fazer?",
        reply_markup=reply_markup,
    )
    return CONFIRMACAO_PARAR


async def lidar_menu_parar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(update.effective_chat.id)
    jobs_atuais = context.job_queue.get_jobs_by_name(chat_id)

    if query.data == "parar_cancelar":
        await query.edit_message_text(
            "Operação cancelada. Seus lembretes continuam ativos!"
        )
        return ConversationHandler.END

    elif query.data == "parar_tudo":
        for job in jobs_atuais:
            job.schedule_removal()
        await query.edit_message_text(
            "🛑 Todos os seus lembretes foram cancelados com sucesso!"
        )
        return ConversationHandler.END

    elif query.data == "parar_especifico":
        mensagem = "🔢 *Escolha qual lembrete deseja apagar:*\nDigite apenas o número correspondente.\n\n"
        for index, job in enumerate(jobs_atuais, 1):
            nome = job.data["nome"]
            hora = job.data.get("hora_str", "")
            mensagem += f"*{index}* - ⏰ {nome} ({hora})\n"

        await query.edit_message_text(mensagem, parse_mode="Markdown")
        return AGUARDANDO_NUMERO_DELECAO


async def executar_delecao_especifica(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    texto_digitado = update.message.text
    chat_id = str(update.effective_chat.id)
    jobs_atuais = context.job_queue.get_jobs_by_name(chat_id)

    try:
        numero = int(texto_digitado)
        if 1 <= numero <= len(jobs_atuais):
            job_para_remover = jobs_atuais[numero - 1]
            nome_removido = job_para_remover.data["nome"]
            job_para_remover.schedule_removal()
            await update.message.reply_text(
                f"🗑️ Sucesso! O lembrete '{nome_removido}' foi removido."
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                f"Número inválido. Escolha um número entre 1 e {len(jobs_atuais)}."
            )
            return AGUARDANDO_NUMERO_DELECAO

    except ValueError:
        await update.message.reply_text(
            "Por favor, digite apenas o número correspondente (ex: 2)."
        )
        return AGUARDANDO_NUMERO_DELECAO


async def fallback_cancelar_geral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operação cancelada.")
    return ConversationHandler.END


# ==========================================
# FLUXO 4: DISPARO E LÓGICA DE ADIAR
# ==========================================


async def disparar_lembrete(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    nome_lembrete = job.data["nome"]

    keyboard = [
        [
            InlineKeyboardButton("✅ Sim", callback_data=f"sim_{nome_lembrete}"),
            InlineKeyboardButton("❌ Não", callback_data=f"nao_{nome_lembrete}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Ei! Você já fez isso: {nome_lembrete}?",
        reply_markup=reply_markup,
    )


async def lidar_com_botoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    acao, nome_lembrete = query.data.split("_", 1)

    if acao == "sim":
        await query.edit_message_text(
            text=f"Parabéns por concluir: '{nome_lembrete}'! Continue assim, Você é meu orgulho 🎉!"
        )
        return ConversationHandler.END

    elif acao == "nao":
        context.user_data["lembrete_adiar"] = nome_lembrete
        await query.edit_message_text(
            text=f"Sem problemas. Adiar '{nome_lembrete}' para quantos minutos? (ex: 15)"
        )
        return AGUARDANDO_ADIAMENTO


async def agendar_adiamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    minutos_str = update.message.text
    nome_lembrete = context.user_data.get("lembrete_adiar")
    chat_id = str(update.effective_chat.id)

    try:
        minutos = int(minutos_str)
        context.job_queue.run_once(
            disparar_lembrete,
            when=minutos * 60,
            data={
                "chat_id": update.effective_chat.id,
                "nome": nome_lembrete,
                "hora_str": f"Adiado (toca daqui a {minutos} min)",
            },
            name=chat_id,
        )
        await update.message.reply_text(
            f"⏳ Combinado! Daqui a {minutos} minutos te lembro novamente de '{nome_lembrete}'."
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "Por favor, digite apenas números inteiros (ex: 15)."
        )
        return AGUARDANDO_ADIAMENTO


if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv_criacao = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NOME_LEMBRETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)
            ],
            HORARIO_LEMBRETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_horario)
            ],
            # Adicionamos os novos gerenciadores de estado aqui
            ESCOLHA_FREQUENCIA: [
                CallbackQueryHandler(lidar_frequencia, pattern="^freq_")
            ],
            SELECAO_DIAS: [
                CallbackQueryHandler(
                    lidar_selecao_dias, pattern="^(dia_|confirmar_dias)"
                )
            ],
        },
        fallbacks=[CommandHandler("cancelar", fallback_cancelar_geral)],
    )

    conv_parar = ConversationHandler(
        entry_points=[CommandHandler("parar", menu_parar)],
        states={
            CONFIRMACAO_PARAR: [CallbackQueryHandler(lidar_menu_parar)],
            AGUARDANDO_NUMERO_DELECAO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, executar_delecao_especifica
                )
            ],
        },
        fallbacks=[CommandHandler("cancelar", fallback_cancelar_geral)],
    )

    conv_adiamento = ConversationHandler(
        entry_points=[CallbackQueryHandler(lidar_com_botoes, pattern=r"^(sim_|nao_)")],
        states={
            AGUARDANDO_ADIAMENTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, agendar_adiamento)
            ]
        },
        fallbacks=[CommandHandler("cancelar", fallback_cancelar_geral)],
    )

    app.add_handler(conv_criacao)
    app.add_handler(conv_parar)
    app.add_handler(conv_adiamento)

    app.add_handler(CommandHandler("listar", listar))

    print("Hesponda Lembretes rodando...")
    app.run_polling()
