import { mainMenu, categoryMenu, allCommandsMenu } from '../menus.js'
import { config } from '../config.js'
import { formatUptime } from '../lib/utils.js'

const MENU_IMAGE = Buffer.from('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', 'base64')

export const generalCommands = {
  menu: async ctx => {
    const category = ctx.args[0]?.toLowerCase()
    if (category === 'todos') return ctx.reply(allCommandsMenu())
    if (category) { const m = categoryMenu(category); if (m) return ctx.reply(m) }
    const name = ctx.msg.pushName || 'Usuario'
    const caption = mainMenu({ name, number: ctx.senderNumber, isAdmin: ctx.isAdmin, isOwner: ctx.isOwner })
    return ctx.sock.sendMessage(ctx.jid, { image: MENU_IMAGE, caption, mentions: [ctx.sender] }, { quoted: ctx.msg })
  },
  comandos: async ctx => ctx.reply(allCommandsMenu()),
  ping: async ctx => { const start = Date.now(); await ctx.react('⚡'); return ctx.reply(`🏓 Pong: ${Date.now() - start} ms`) },
  botinfo: async ctx => ctx.reply(`🤖 *${config.botName}*\nPrefijo: ${config.prefix}\nRuntime: ${formatUptime(process.uptime())}\nMotor: Baileys\nGrupo: ${config.groupLink}`),
  ayuda: async ctx => ctx.reply(`Usa *${config.prefix}menu* para ver las categorías.\nEjemplo: *${config.prefix}menu grupos*`),
  prefix: async ctx => ctx.reply(`Mi prefijo actual es: *${config.prefix}*`),
  estado: async ctx => ctx.reply('🟢 Bot conectado y operativo.'),
  uptime: async ctx => ctx.reply(`⏱️ Activo: ${formatUptime(process.uptime())}`),
  runtime: async ctx => ctx.reply(`⏱️ ${formatUptime(process.uptime())}`)
}
