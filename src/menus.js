import { config } from './config.js'
import { timeAndDate } from './lib/utils.js'

const categories = {
  stickers: ['sticker', 's', 'sa', 's2', 'saudio', 'stickeraudio', 'cl', 'ske', 'letr', 'sck', 'cleansticker', 'swm', 'stickerwm', 'toimg', 'toimage', 'stickerinfo', 'soundinfo', 'guiasonido'],
  descargas: ['play', 'ytplay', 'youtube.play', 'spotify', 'sp', 'ytmp3', 'yta', 'ytmp4', 'ytvideo', 'playvideo', 'youtube.video', 'tiktok', 'tt', 'tiktoknowm', 'ttnowm', 'instagram', 'ig', 'mediahelp', 'descargas', 'reel', 'play2', 'mp3', 'mp4'],
  grupos: ['admins', 'tagall', 'hidetag', 'kick', 'kill', 'add', 'promote', 'demote', 'link', 'revoke', 'subject', 'desc', 'open', 'close', 'groupinfo'],
  ia: ['ia', 'ai', 'pregunta', 'chatgpt', 'resumir', 'traducir', 'resetia'],
  herramientas: ['hora', 'fecha', 'calc', 'qr', 'id', 'jid', 'runtime', 'avatar', 'getpic', 'pfp', 'qrcode', 'resize', 'redimensionar', 'say', 'ver'],
  social: ['perfil', 'profile', 'me', 'owner', 'grupo', 'saludar'],
  anime: ['kiss', 'muak', 'beso', 'hug', 'abrazo', 'pat', 'slap', 'highfive', 'poke', 'dance', 'wave', 'smile', 'wink', 'cuddle', 'blush', 'cry', 'happy', 'bonk', 'handhold'],
  diversion: ['dado', 'moneda', '8ball', 'ship', 'rate', 'chiste', 'reto', 'verdad', 'ahorcado', 'hangman', 'trivia', 'quiz'],
  general: ['menu', 'ping', 'botinfo', 'ayuda', 'prefix', 'estado', 'uptime', 'comandos', 'setppbot', 'allmenu', 'info', 'status', 'p']
}

const labels = { stickers: '🎨  STICKER STUDIO', descargas: '🎧  MEDIA CENTER', grupos: '🛡️  ADMINISTRACIÓN', ia: '🤖  INTELIGENCIA ARTIFICIAL', herramientas: '⚙️  UTILIDADES', social: '💎  SOCIAL', anime: '🌌  RS ANIME EXPERIENCE', diversion: '🎮  ENTRETENIMIENTO', general: '📡  SISTEMA' }
export function mainMenu(profile = {}) {
  const { time, date } = timeAndDate()
  const p = config.prefix
  return ['♛ *𝗥𝗔𝗡𝗗𝗬 𝗦𝗬𝗦𝗧𝗘𝗠𝗦*', '✦ ᴘʀᴇᴍɪᴜᴍ ᴇᴅɪᴛɪᴏɴ · ᴠ2 ✦', '👑 *Owner:* Randy • @randy_zt', '━━━━━━━━━━━━━━━━', '◈ *𝗣𝗘𝗥𝗙𝗜𝗟 𝗗𝗜𝗚𝗜𝗧𝗔𝗟*', 'Nombre: ' + (profile.name || 'Usuario'), 'Rango: ' + (profile.isOwner ? 'Owner' : profile.isAdmin ? 'Administrador' : 'Usuario'), 'Fecha: ' + date + ' • ' + time, 'Prefijo: ' + p, '━━━━━━━━━━━━━━━━', ...Object.keys(categories).map((k,i) => '╭─ ' + String(i+1).padStart(2,'0') + ' · *' + labels[k] + '*\n╰─ › ' + p + 'menu ' + k + '  ·  ' + categories[k].length + ' comandos'), '━━━━━━━━━━━━━━━━', '📚 ' + p + 'menu todos', '🔊 ' + p + 'guiasonido', '✦ ᴅᴇsɪɢɴᴇᴅ ʙʏ ʀᴀɴᴅʏ\n© RANDY SYSTEMS 2026'].join('\n\n')
}
export function categoryMenu(name) {
  const key = name?.toLowerCase()
  if (!Object.hasOwn(categories, key)) return null
  return ['💎 *𝗥𝗔𝗡𝗗𝗬 𝗦𝗬𝗦𝗧𝗘𝗠𝗦*', '*' + labels[key] + '*', '━━━━━━━━━━━━━━━━', ...categories[key].map(c => '› ' + config.prefix + c + (c === 'kill' ? ' @all' : key === 'anime' ? ' @usuario' : '')), '━━━━━━━━━━━━━━━━', ...(key === 'stickers' ? ['.stickeraudio / .saudio / .sa / .s2: audio integrado en pruebas, video máximo 8 s. Usa ' + config.prefix + 'guiasonido para la guía.'] : []), '↩ ' + config.prefix + 'menu'].join('\n')
}
export function allCommandsMenu() { return Object.keys(categories).map(k => categoryMenu(k)).join('\n\n') }
export { categories }
