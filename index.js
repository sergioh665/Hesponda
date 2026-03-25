const wppconnect = require("@wppconnect-team/wppconnect");
const cron = require("node-cron");
require("dotenv").config();

// Configurável via .env
const SESSION_NAME = process.env.SESSION_NAME || "Hesponda";
const TIMEZONE = process.env.TIMEZONE || "America/Fortaleza";
const TARGET_NUMBERS = (process.env.TARGET_NUMBERS || "")
	.split(",")
	.map((s) => s.trim())
	.filter(Boolean);
const REMINDER_TIMES = (process.env.REMINDER_TIMES || "08:00,20:00")
	.split(",")
	.map((s) => s.trim())
	.filter(Boolean);
const RESPONSE_WINDOW_HOURS = Number(process.env.RESPONSE_WINDOW_HOURS || 3);
const RESPONSE_WINDOW_MS = RESPONSE_WINDOW_HOURS * 60 * 60 * 1000;

// Frases aceitas como confirmação
const EXPECTED_CONFIRMATIONS = ["1", "já tomei", "ja tomei", "tomei", "sim"];

// Estado em memória: armazena lembretes pendentes por número
const pendingReminders = new Map();

wppconnect
	.create({
		session: SESSION_NAME,
		autoClose: 0,
		catchQR: (base64Qr, asciiQR) => {
			console.log("Terminal QR Code: ", asciiQR);
		},
	})
	.then((client) => start(client))
	.catch((error) => console.log("Erro ao iniciar:", error));

function start(client) {
	console.log("Bot Hesponda ativo e operante! 🚀");

	if (TARGET_NUMBERS.length === 0) {
		console.warn(
			"Atenção: nenhuma `TARGET_NUMBERS` definida em .env. Nenhum lembrete será enviado.",
		);
	} else {
		client
			.sendText(
				TARGET_NUMBERS[0],
				"Bot ativo! Vou enviar lembretes nos horários configurados.",
			)
			.then(() => console.log("Mensagem de teste enviada ✅"))
			.catch((err) => console.error("Erro no envio de teste:", err));
	}

	// Agenda os horários configurados (cada entrada no formato HH:MM)
	REMINDER_TIMES.forEach((time) => {
		const parts = time.split(":");
		if (parts.length !== 2)
			return console.warn(`Horário inválido em REMINDER_TIMES: ${time}`);
		const hour = Number(parts[0]);
		const minute = Number(parts[1]);
		const cronExpr = `${minute} ${hour} * * *`;

		cron.schedule(
			cronExpr,
			async () => {
				for (const number of TARGET_NUMBERS) {
					const text = `Olá! Hora do remédio. Responda com '1' ou 'já tomei' quando tomar.`;
					try {
						await client.sendText(number, text);
						pendingReminders.set(number, {
							sentAt: Date.now(),
							expiresAt: Date.now() + RESPONSE_WINDOW_MS,
							text,
						});
						console.log(
							`[${new Date().toLocaleString()}] Lembrete enviado para ${number}`,
						);
					} catch (err) {
						console.error(`Erro ao enviar lembrete para ${number}:`, err);
					}
				}
			},
			{ timezone: TIMEZONE },
		);
	});

	// Listener para respostas — usa o contexto de `pendingReminders`
	client.onMessage(async (message) => {
		try {
			const from = message.from;
			const body = (message.body || "").trim().toLowerCase();

			// Só processa se houver um lembrete pendente para esse número
			const pending = pendingReminders.get(from);
			if (!pending) return; // Ignora mensagens sem contexto de lembrete

			// Verifica se ainda está dentro da janela de resposta
			if (Date.now() > pending.expiresAt) {
				// opção: remover o lembrete expirado
				pendingReminders.delete(from);
				console.log(`Resposta recebida fora da janela para ${from}, ignorada.`);
				return;
			}

			// Checa se a resposta bate com uma confirmação esperada
			if (EXPECTED_CONFIRMATIONS.includes(body)) {
				await client.sendText(from, "Obrigado! Marquei como tomado. ❤️");
				pendingReminders.delete(from);
				console.log(`Confirmação recebida de ${from}: ${body}`);
			} else {
				// Resposta diferente — orienta sobre as opções válidas
				await client.sendText(
					from,
					"Por favor responda apenas com '1' ou 'já tomei' para confirmar que tomou o remédio.",
				);
				console.log(`Resposta inválida de ${from}: ${body}`);
			}
		} catch (err) {
			console.error("Erro ao processar mensagem recebida:", err);
		}
	});
}
