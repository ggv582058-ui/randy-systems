import axios from 'axios'
import OpenAI from 'openai'
import { config } from '../config.js'

function client() {
  if (!config.openaiKey) return null
  return new OpenAI({ apiKey: config.openaiKey, timeout: 25000, maxRetries: 0 })
}

async function ask(prompt, system = 'Eres el asistente RANDY SYSTEMS. Responde en el idioma del usuario, de forma útil, clara y concisa. Si no sabes algo, dilo; no inventes datos ni afirmes haber realizado acciones externas.') {
  const c = client()
  if (!c) return null
  const response = await c.responses.create({
    model: config.openaiModel,
    instructions: system,
    input: prompt,
    max_output_tokens: 1800,
    store: false
  })
  return response.output_text || 'Sin respuesta.'
}

const STOPWORDS = new Set([
  'que','para','con','por','una','uno','unos','unas','del','las','los','como','más','pero','sus','ese','esa','esto','esta','este','hay','fue','son','ser','sin','sobre','entre','desde','hasta','porque','cuando','donde','también','muy','todo','todos','toda','todas','the','and','for','with','from','that','this','are','was','were','have','has','but','not','you','your','they','their','will','would','about'
])

function localSummary(text = '') {
  const clean = String(text).replace(/\s+/g, ' ').trim()
  if (!clean) return ''
  if (clean.length <= 500) return clean

  const sentences = clean.match(/[^.!?]+[.!?]+|[^.!?]+$/g)?.map(s => s.trim()).filter(Boolean) || [clean]
  if (sentences.length <= 3) return sentences.join(' ')

  const words = clean.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || []
  const freq = new Map()
  for (const word of words) {
    if (STOPWORDS.has(word)) continue
    freq.set(word, (freq.get(word) || 0) + 1)
  }

  const scored = sentences.map((sentence, index) => {
    const terms = sentence.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || []
    const score = terms.reduce((sum, word) => sum + (freq.get(word) || 0), 0) / Math.max(terms.length, 1)
    return { sentence, index, score }
  })

  const take = Math.max(2, Math.min(6, Math.ceil(sentences.length * 0.3)))
  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, take)
    .sort((a, b) => a.index - b.index)
    .map(item => item.sentence)
    .join(' ')
}

const LANGUAGE_CODES = {
  espanol: 'es', español: 'es', spanish: 'es', es: 'es',
  ingles: 'en', inglés: 'en', english: 'en', en: 'en',
  portugues: 'pt', portugués: 'pt', portuguese: 'pt', pt: 'pt',
  frances: 'fr', francés: 'fr', french: 'fr', fr: 'fr',
  italiano: 'it', italian: 'it', it: 'it',
  aleman: 'de', alemán: 'de', german: 'de', de: 'de',
  japones: 'ja', japonés: 'ja', japanese: 'ja', ja: 'ja',
  coreano: 'ko', korean: 'ko', ko: 'ko'
}

async function translateWithoutKey(targetLanguage, text) {
  const normalized = String(targetLanguage || '').trim().toLowerCase()
  const target = LANGUAGE_CODES[normalized] || normalized
  if (!/^[a-z]{2,3}(?:-[a-z]{2})?$/i.test(target)) {
    throw new Error('Idioma no reconocido.')
  }

  const { data } = await axios.get('https://translate.googleapis.com/translate_a/single', {
    params: { client: 'gtx', sl: 'auto', tl: target, dt: 't', q: text },
    timeout: 12000,
    headers: { 'user-agent': 'RANDY-SYSTEMS/1.0' }
  })

  const translated = Array.isArray(data?.[0])
    ? data[0].map(part => part?.[0] || '').join('').trim()
    : ''
  if (!translated) throw new Error('Sin traducción.')
  return translated
}

let activeQuestions = 0
const lastQuestion = new Map()
async function generalQuestion(ctx) {
    if (!ctx.argText) return ctx.reply('Uso: .ia ¿qué quieres preguntar?')
    if (ctx.argText.length > 4000) return ctx.reply('❌ La pregunta debe tener máximo 4000 caracteres.')
    if (!config.openaiKey) return ctx.reply('⚠️ La IA requiere que el administrador configure OPENAI_API_KEY en Render.')
    const key = String(ctx.sender || ctx.senderNumber || ctx.jid)
    const now = Date.now()
    if (now - (lastQuestion.get(key) || 0) < 5000) return ctx.reply('⏳ Espera unos segundos antes de otra consulta.')
    if (activeQuestions >= 3) return ctx.reply('⏳ La IA está atendiendo otras consultas. Intenta de nuevo.')
    if (lastQuestion.size >= 1000) lastQuestion.delete(lastQuestion.keys().next().value)
    lastQuestion.set(key, now)
    activeQuestions++
    try {
      await ctx.react('🤖').catch(() => {})
      const answer = await ask(ctx.argText)
      if (answer) return ctx.reply(answer)
      return ctx.reply('⚠️ *.ia* necesita una OPENAI_API_KEY configurada en Render. *.resumir* y *.traducir* ya funcionan sin esa clave.')
    } catch (error) {
      console.error('AI command error:', error?.status || error?.code || 'unknown')
      return ctx.reply('❌ La IA no pudo responder ahora. Intenta de nuevo; si persiste, el administrador debe revisar la API.')
    } finally {
      activeQuestions--
    }
}

export const aiCommands = {
  ia: generalQuestion,
  ai: generalQuestion,
  pregunta: generalQuestion,
  chatgpt: generalQuestion,

  resumir: async ctx => {
    if (!ctx.argText) return ctx.reply('Uso: .resumir texto')
    try {
      const answer = await ask(ctx.argText, 'Resume el texto en español de forma clara, conservando lo esencial.')
      return ctx.reply(answer || `📝 *Resumen*\n${localSummary(ctx.argText)}`)
    } catch (error) {
      console.error('Summary AI fallback:', error)
      return ctx.reply(`📝 *Resumen*\n${localSummary(ctx.argText)}`)
    }
  },

  traducir: async ctx => {
    if (!ctx.argText) return ctx.reply('Uso: .traducir <idioma> | <texto>\nEjemplo: .traducir inglés | hola mundo')
    const separator = ctx.argText.indexOf('|')
    if (separator < 0) return ctx.reply('Uso: .traducir <idioma> | <texto>\nEjemplo: .traducir inglés | hola mundo')
    const targetLanguage = ctx.argText.slice(0, separator).trim()
    const text = ctx.argText.slice(separator + 1).trim()
    if (!targetLanguage || !text) return ctx.reply('❌ Falta el idioma o el texto.')

    try {
      if (config.openaiKey) {
        const answer = await ask(`${targetLanguage} | ${text}`, 'Traduce el texto al idioma solicitado. Devuelve solo la traducción.')
        if (answer) return ctx.reply(answer)
      }
      return ctx.reply(await translateWithoutKey(targetLanguage, text))
    } catch (error) {
      console.error('Translate fallback error:', error)
      return ctx.reply('❌ No pude traducir ese texto ahora. Prueba de nuevo o usa un idioma como inglés, español, portugués o francés.')
    }
  }
}
