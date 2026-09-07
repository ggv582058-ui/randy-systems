import OpenAI from 'openai'
import { config } from '../config.js'

function client() {
  if (!config.openaiKey) return null
  return new OpenAI({ apiKey: config.openaiKey })
}

async function ask(prompt, system = 'Responde en español, claro y breve.') {
  const c = client()
  if (!c) return '⚠️ IA no configurada. Agrega OPENAI_API_KEY en el archivo .env.'
  const response = await c.responses.create({ model: config.openaiModel, instructions: system, input: prompt })
  return response.output_text || 'Sin respuesta.'
}

export const aiCommands = {
  ia: async ctx => { if (!ctx.argText) return ctx.reply('Uso: .ia ¿qué quieres preguntar?'); await ctx.react('🤖'); return ctx.reply(await ask(ctx.argText)) },
  resumir: async ctx => { if (!ctx.argText) return ctx.reply('Uso: .resumir texto'); return ctx.reply(await ask(ctx.argText, 'Resume el texto en español de forma clara, conservando lo esencial.')) },
  traducir: async ctx => { if (!ctx.argText) return ctx.reply('Uso: .traducir <idioma> | <texto>'); return ctx.reply(await ask(ctx.argText, 'Traduce el texto al idioma solicitado. Devuelve solo la traducción.')) }
}
