import { config } from './config.js'
import { timeAndDate } from './lib/utils.js'

const categories = {
  stickers: ['sticker', 's', 'sa', 'stickeraudio', 'cl', 'ske', 'letr', 'sck', 'cleansticker', 'swm', 'stickerwm', 'toimg', 'stickerinfo', 'soundinfo', 'guiasonido'],
  descargas: ['play', 'ytplay', 'youtube.play', 'spotify', 'sp', 'ytmp3', 'yta', 'ytmp4', 'ytvideo', 'playvideo', 'youtube.video', 'tiktok', 'tt', 'tiktoknowm', 'ttnowm', 'instagram', 'ig', 'mediahelp', 'descargas'],
  grupos: ['admins', 'tagall', 'hidetag', 'kick', 'kill', 'add', 'promote', 'demote', 'link', 'revoke', 'subject', 'desc', 'open', 'close', 'groupinfo'],
  ia: ['ia', 'ai', 'pregunta', 'chatgpt', 'resumir', 'traducir', 'resetia'],
  herramientas: ['hora', 'fecha', 'calc', 'qr', 'id', 'jid', 'runtime', 'avatar', 'ver'],
  social: ['perfil', 'me', 'owner', 'grupo', 'saludar'],
  diversion: ['dado', 'moneda', '8ball', 'ship', 'rate', 'chiste', 'reto', 'verdad'],
  general: ['menu', 'ping', 'botinfo', 'ayuda', 'prefix', 'estado', 'uptime', 'comandos', 'setppbot']
}

const labels = { stickers: '🎨  STICKER STUDIO', descargas: '🎧  MEDIA CENTER', grupos: '🛡️  ADMINISTRACIÓN', ia: '🤖  INTELIGENCIA ARTIFICIAL', herramientas: '⚙️  UTILIDADES', social: '💎  SOCIAL', diversion: '🎮  ENTRETENIMIENTO', general: '📡  SISTEMA' }
export function mainMenu(profile = {}) {
  const { time, date } = timeAndDate()
  const p = config.prefix
  return ['♛ *𝗥𝗔𝗡𝗗𝗬 𝗦𝗬𝗦𝗧𝗘𝗠𝗦*', '✦ ᴘʀᴇᴍɪᴜᴍ ᴇᴅɪᴛɪᴏɴ ✦', '👑 *Owner:* Randy • @randy_zt', '━━━━━━━━━━━━━━━━', '◈ *𝗣𝗘𝗥𝗙𝗜𝗟 𝗗𝗜𝗚𝗜𝗧𝗔𝗟*', 'Nombre: ' + (profile.name || 'Usuario'), 'Rango: ' + (profile.isOwner ? 'Owner' : profile.isAdmin ? 'Administrador' : 'Usuario'), 'Fecha: ' + date + ' • ' + time, 'Prefijo: ' + p, '━━━━━━━━━━━━━━━━', ...Object.keys(categories).map((k,i) => '╭─ ' + String(i+1).padStart(2,'0') + ' · *' + labels[k] + '*\n╰─ › ' + p + 'menu ' + k + '  ·  ' + categories[k].length + ' comandos'), '━━━━━━━━━━━━━━━━', '📚 ' + p + 'menu todos', '🔊 ' + p + 'guiasonido', '✦ ᴅᴇsɪɢɴᴇᴅ ʙʏ ʀᴀɴᴅʏ\n© RANDY SYSTEMS 2026'].join('\n\n')
}
export function categoryMenu(name) {
  const key = name?.toLowerCase()
  if (!Object.hasOwn(categories, key)) return null
  return ['💎 *𝗥𝗔𝗡𝗗𝗬 𝗦𝗬𝗦𝗧𝗘𝗠𝗦*', '*' + labels[key] + '*', '━━━━━━━━━━━━━━━━', ...categories[key].map(c => '› ' + config.prefix + c + (c === 'kill' ? ' @all' : '')), '━━━━━━━━━━━━━━━━', ...(key === 'stickers' ? ['Audio nativo: experimental. Usa ' + config.prefix + 'guiasonido para la guía.'] : []), '↩ ' + config.prefix + 'menu'].join('\n')
}
export function allCommandsMenu() { return Object.keys(categories).map(k => categoryMenu(k)).join('\n\n') }
export { categories }
