import QRCode from 'qrcode'
import { evaluate } from 'mathjs'
import { timeAndDate, jidToNumber } from '../lib/utils.js'

export const toolCommands = {
  hora: async ctx => ctx.reply(`🕒 Hora: ${timeAndDate().time}`),
  fecha: async ctx => ctx.reply(`📅 Fecha: ${timeAndDate().date}`),
  calc: async ctx => { if (!ctx.argText) return ctx.reply('Uso: .calc 2+2*5'); try { const result = evaluate(ctx.argText); return ctx.reply(`🧮 Resultado: *${String(result)}*`) } catch { return ctx.reply('❌ Operación inválida.') } },
  qr: async ctx => { if (!ctx.argText) return ctx.reply('Uso: .qr texto o enlace'); const png = await QRCode.toBuffer(ctx.argText, { width: 512 }); return ctx.sock.sendMessage(ctx.jid, { image: png, caption: '✅ QR generado.' }, { quoted: ctx.msg }) },
  id: async ctx => ctx.reply(`🆔 Chat ID: ${ctx.jid}\n👤 Tu ID: ${ctx.sender}`),
  jid: async ctx => ctx.reply(`👤 JID: ${ctx.sender}`),
  avatar: async ctx => { const target = ctx.getTargetJid() || ctx.sender; const url = await ctx.sock.profilePictureUrl(target, 'image').catch(() => null); if (!url) return ctx.reply('No pude obtener la foto de perfil.'); return ctx.sock.sendMessage(ctx.jid, { image: { url }, caption: `📸 @${jidToNumber(target)}`, mentions: [target] }, { quoted: ctx.msg }) }
}
