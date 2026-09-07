import { config } from '../config.js'
import { jidToNumber } from '../lib/utils.js'

export const socialCommands = {
  perfil: async ctx => {
    const target = ctx.getTargetJid() || ctx.sender
    const name = target === ctx.sender ? (ctx.msg.pushName || 'Usuario') : 'Usuario'
    const url = await ctx.sock.profilePictureUrl(target, 'image').catch(() => null)
    const text = `👤 *PERFIL*\nNombre: ${name}\nUser: @${jidToNumber(target)}\nAdmin: ${ctx.isAdmin ? '✅' : '❌'}`
    if (url) return ctx.sock.sendMessage(ctx.jid, { image: { url }, caption: text, mentions: [target] }, { quoted: ctx.msg })
    return ctx.sock.sendMessage(ctx.jid, { text, mentions: [target] }, { quoted: ctx.msg })
  },
  me: async ctx => socialCommands.perfil(ctx),
  owner: async ctx => ctx.reply(config.ownerNumber ? `👑 Owner: wa.me/${config.ownerNumber}` : 'Owner no configurado.'),
  saludar: async ctx => ctx.reply(`👋 Qué onda, ${ctx.msg.pushName || 'apa'}.`)
}
