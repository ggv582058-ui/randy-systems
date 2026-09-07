const pick = arr => arr[Math.floor(Math.random() * arr.length)]

export const funCommands = {
  dado: async ctx => ctx.reply(`🎲 Salió: *${1 + Math.floor(Math.random() * 6)}*`),
  moneda: async ctx => ctx.reply(`🪙 ${Math.random() < 0.5 ? 'Cara' : 'Cruz'}`),
  '8ball': async ctx => ctx.reply(`🎱 ${pick(['Sí.', 'No.', 'Probablemente.', 'Ni de chiste 😂', 'Todo apunta a que sí.', 'Pregunta otra vez.'])}`),
  rate: async ctx => ctx.reply(`📊 ${ctx.argText || 'Eso'}: *${Math.floor(Math.random() * 101)}%*`),
  ship: async ctx => ctx.reply(`❤️ Compatibilidad: *${Math.floor(Math.random() * 101)}%*`),
  chiste: async ctx => ctx.reply(pick(['¿Qué hace una abeja en el gimnasio? ¡Zum-ba! 😂', 'Programador: funciona en mi máquina. Servidor: pues aquí no 😭', '¿Cuál es el colmo de un bot? Que lo dejen en visto.'])),
  reto: async ctx => ctx.reply(pick(['Reto: manda un audio cantando 10 segundos.', 'Reto: cambia tu foto por un meme 5 minutos.', 'Reto: escribe algo bonito de alguien del grupo.'])),
  verdad: async ctx => ctx.reply(pick(['Verdad: ¿quién te cae mejor del grupo?', 'Verdad: ¿qué fue lo último que borraste de WhatsApp?', 'Verdad: ¿qué cosa te da pena admitir?']))
}
