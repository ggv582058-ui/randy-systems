import QRCode from 'qrcode'
import { evaluate } from 'mathjs'
import { timeAndDate, jidToNumber } from '../lib/utils.js'

async function resolveAvatar(ctx) {
  const target = ctx.getTargetJid() || ctx.sender
  const number = jidToNumber(target)
  const candidates = [
    target,
    number ? `${number}@s.whatsapp.net` : null,
    ...(ctx.participants || [])
      .filter(p => jidToNumber(p.id) === number)
      .map(p => p.id)
  ].filter(Boolean)

  const unique = [...new Set(candidates)]
  for (const jid of unique) {
    for (const type of ['image', 'preview']) {
      const url = await ctx.sock.profilePictureUrl(jid, type).catch(() => null)
      if (url) return { url, jid }
    }
  }
  return { url: null, jid: target }
}

export const toolCommands = {
  hora: async ctx => ctx.reply(`🕒 Hora: ${timeAndDate().time}`),
  fecha: async ctx => ctx.reply(`📅 Fecha: ${timeAndDate().date}`),
  calc: async ctx => { if (!ctx.argText) return ctx.reply('Uso: .calc 2+2*5'); try { const result = evaluate(ctx.argText); return ctx.reply(`🧮 Resultado: *${String(result)}*`) } catch { return ctx.reply('❌ Operación inválida.') } },
  qr: async ctx => { if (!ctx.argText) return ctx.reply('Uso: .qr texto o enlace'); const png = await QRCode.toBuffer(ctx.argText, { width: 512 }); return ctx.sock.sendMessage(ctx.jid, { image: png, caption: '✅ QR generado.' }, { quoted: ctx.msg }) },
  id: async ctx => ctx.reply(`🆔 Chat ID: ${ctx.jid}\n👤 Tu ID: ${ctx.sender}`),
  jid: async ctx => ctx.reply(`👤 JID: ${ctx.sender}`),
  avatar: async ctx => {
    const { url, jid } = await resolveAvatar(ctx)
    if (!url) return ctx.reply('❌ No pude obtener esa foto de perfil. Puede estar oculta por privacidad o WhatsApp no la está entregando al bot.')
    try {
      return await ctx.sock.sendMessage(ctx.jid, {
        image: { url },
        caption: `📸 @${jidToNumber(jid)}`,
        mentions: [jid]
      }, { quoted: ctx.msg })
    } catch (error) {
      console.error('Avatar send error:', error)
      return ctx.reply('❌ Encontré la foto, pero WhatsApp no me dejó enviarla. Intenta otra vez.')
    }
  }
}
