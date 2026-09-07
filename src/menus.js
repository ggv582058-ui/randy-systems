import { config } from './config.js'
import { timeAndDate } from './lib/utils.js'

const categories = {
  stickers: ['sticker', 's', 'swm', 'stickerwm', 'toimg', 'stickerinfo'],
  descargas: ['play', 'ytplay', 'youtube.play', 'spotify', 'ytmp3', 'ytmp4', 'youtube.video', 'tiktok', 'tt', 'instagram', 'ig', 'mediahelp'],
  grupos: ['admins', 'tagall', 'hidetag', 'kick', 'add', 'promote', 'demote', 'link', 'revoke', 'subject', 'desc', 'open', 'close', 'groupinfo'],
  ia: ['ia', 'resumir', 'traducir'],
  herramientas: ['hora', 'fecha', 'calc', 'qr', 'id', 'jid', 'runtime', 'avatar'],
  social: ['perfil', 'me', 'owner', 'grupo', 'saludar'],
  diversion: ['dado', 'moneda', '8ball', 'ship', 'rate', 'chiste', 'reto', 'verdad'],
  general: ['menu', 'ping', 'botinfo', 'ayuda', 'prefix', 'estado', 'uptime', 'comandos', 'setppbot']
}

export function mainMenu(profile = {}) {
  const { time, date } = timeAndDate(); const p = config.prefix
  return `╭═════════════⊷\n╰╮き⃟❗️ɪɴғᴏ ᴅᴇʟ ʙᴏᴛ❗⃟ き\n╭┤⋟ Prefijo: 『 ${p} 』\n┃│⋟ Hora: ${time}\n┃│⋟ Fecha: ${date}\n┃│⋟ Nombre: *${config.botName}*\n┃│⋟ Grupo: ${config.groupLink || 'No configurado'}\n┃╰════════════⊷\n╰╦═════「★」════⊷\n╭┤き⃟👤 ɪɴғᴏ ᴘᴇʀғɪʟ 👤⃟ き\n┃╞════════════⊷\n┃┌━━━━── • ──━━━━\n┃│⋟ Nombre: ${profile.name || 'Usuario'}\n┃│⋟ User: @${profile.number || 'usuario'}\n┃│⋟ Rango: ${profile.isOwner ? 'Owner' : profile.isAdmin ? 'Administrador' : 'Usuario'}\n┃│⋟ Admin: ${profile.isAdmin ? '✅' : '❌'}\n┃╰━━━━── • ──━━━━\n╰╦═════「★」════⊷\n╭┤き⃟📜 ᴍᴇɴú ᴘᴏʀ ᴄᴀᴛᴇɢᴏʀíᴀs 📜⃟ き\n┃╰━━━━── • ──━━━━\n┃╭ ⋟ \`${p}menu stickers\` 🎨\n┃│  Crear, editar y gestionar stickers y paquetes.\n┃│  ${categories.stickers.length} comandos\n┃╰━━━─── • ──━━━━\n┃╭ ⋟ \`${p}menu descargas\` 📥\n┃│  Música, videos y descargas de YouTube, TikTok e Instagram.\n┃│  ${categories.descargas.length} comandos\n┃╰━━━─── • ──━━━━\n┃╭ ⋟ \`${p}menu grupos\` 👥\n┃│  Administración, seguridad y configuración de grupos.\n┃│  ${categories.grupos.length} comandos\n┃╰━━━─── • ──━━━━\n┃╭ ⋟ \`${p}menu ia\` 🤖\n┃│  Conversación y herramientas con inteligencia artificial.\n┃│  ${categories.ia.length} comandos\n┃╰━━━─── • ──━━━━\n┃╭ ⋟ \`${p}menu herramientas\` 🧰\n┃│  Consultas, información y utilidades prácticas.\n┃│  ${categories.herramientas.length} comandos\n┃╰━━━─── • ──━━━━\n┃╭ ⋟ \`${p}menu social\` 🎵\n┃│  Perfiles, actividad, relaciones y música.\n┃│  ${categories.social.length} comandos\n┃╰━━━─── • ──━━━━\n┃╭ ⋟ \`${p}menu diversion\` 🎭\n┃│  Juegos, reacciones, memes y entretenimiento.\n┃│  ${categories.diversion.length} comandos\n┃╰━━━─── • ──━━━━\n┃╭ ⋟ \`${p}menu general\` 👻\n┃│  Información y otros comandos del bot.\n┃│  ${categories.general.length} comandos\n┃╰━━━─── • ──━━━━\n┃╭ ⋟ \`${p}menu todos\` 📚\n┃│  Muestra todas las categorías.\n┃╰━━━─── • ──━━━━\n╰━━━━━── • ──━━━━`
}

export function categoryMenu(name) { const key = name?.toLowerCase(); const list = categories[key]; if (!list) return null; const pretty = list.map(c => `┃ ⋟ ${config.prefix}${c}`).join('\n'); return `╭═════════════⊷\n╰╮  ${key.toUpperCase()}\n╭╯═════════════⊷\n${pretty}\n╰═════════════⊷` }
export function allCommandsMenu() { return Object.keys(categories).map(k => categoryMenu(k)).join('\n\n') }
export { categories }
