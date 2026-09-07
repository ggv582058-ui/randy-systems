import { mainMenu, categoryMenu, allCommandsMenu } from '../menus.js'
import { config } from '../config.js'
import { formatUptime } from '../lib/utils.js'

export const generalCommands = {
  menu: async ctx => {
    const category = ctx.args[0]?.toLowerCase()
    if (category === 'todos') return ctx.reply(allCommandsMenu())
    if (category) { const m = categoryMenu(category); if (m) return ctx.reply(m) }
    const name = ctx.msg.pushName || 'Usuario'
    return ctx.sock.sendMessage(ctx.jid, { text: mainMenu({ name, number: ctx.senderNumber, isAdmin: ctx.isAdmin, isOwner: ctx.isOwner }), mentions: [ctx.sender] }, { quoted: ctx.msg })
  },
  comandos: async ctx => ctx.reply(allCommandsMenu()),
  ping: async ctx => { const start = Date.now(); await ctx.react('⚡'); return ctx.reply(`🏓 Pong: ${Date.now() - start} ms`) },
  botinfo: async ctx => ctx.reply(`🤖 *${config.botName}*\nPrefijo: ${config.prefix}\nRuntime: ${formatUptime(process.uptime())}\nMotor: Baileys`),
  ayuda: async ctx => ctx.reply(`Usa *${config.prefix}menu* para ver las categorías.\nEjemplo: *${config.prefix}menu grupos*`),
  prefix: async ctx => ctx.reply(`Mi prefijo actual es: *${config.prefix}*`),
  estado: async ctx => ctx.reply('🟢 Bot conectado y operativo.'),
  uptime: async ctx => ctx.reply(`⏱️ Activo: ${formatUptime(process.uptime())}`),
  runtime: async ctx => ctx.reply(`⏱️ ${formatUptime(process.uptime())}`)
}
