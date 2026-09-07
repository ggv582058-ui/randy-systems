export const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

export function jidToNumber(jid = '') {
  return jid.split('@')[0].split(':')[0]
}

export function formatUptime(seconds = 0) {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return `${d}d ${h}h ${m}m ${s}s`
}

export function getText(msg) {
  const m = msg?.message || {}
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    m.documentMessage?.caption ||
    ''
  )
}

export function quotedMessage(msg) {
  const ctx = msg?.message?.extendedTextMessage?.contextInfo
    || msg?.message?.imageMessage?.contextInfo
    || msg?.message?.videoMessage?.contextInfo
  return ctx?.quotedMessage || null
}

export function quotedParticipant(msg) {
  const ctx = msg?.message?.extendedTextMessage?.contextInfo
    || msg?.message?.imageMessage?.contextInfo
    || msg?.message?.videoMessage?.contextInfo
  return ctx?.participant || null
}

export function parseCommand(text, prefix) {
  if (!text?.startsWith(prefix)) return null
  const body = text.slice(prefix.length).trim()
  if (!body) return null
  const [raw, ...args] = body.split(/\s+/)
  return {
    command: raw.toLowerCase(),
    args,
    argText: args.join(' ')
  }
}

export function timeAndDate(locale = 'es-MX', tz = 'America/New_York') {
  const now = new Date()
  const time = new Intl.DateTimeFormat(locale, {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: tz
  }).format(now)
  const date = new Intl.DateTimeFormat(locale, {
    day: '2-digit', month: '2-digit', year: 'numeric', timeZone: tz
  }).format(now)
  return { time, date }
}
