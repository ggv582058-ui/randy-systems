import QRCode from 'qrcode'
import { evaluate } from 'mathjs'
import { timeAndDate, jidToNumber } from '../lib/utils.js'

import { findGroupParticipant, normalizeWhatsAppJid } from '../lib/group-identity.js'

async function resolveAvatar(ctx) {
  const target = ctx.getTargetJid() || ctx.sender
  const ids = new Set()
  const add = value => {
    const id = normalizeWhatsAppJid(value)
    if (/^\d+@(lid|s\.whatsapp\.net)$/.test(id)) ids.add(id)
  }
  add(target)
  if (!ctx.getTargetJid() || target === ctx.sender) {
    add(ctx.msg?.key?.participantAlt)
    if (!ctx.isGroup && !ctx.msg?.key?.fromMe) add(ctx.msg?.key?.remoteJidAlt)
  }
  const mapping = ctx.sock.signalRepository?.lidMapping
  for (const id of [...ids]) {
    try {
      add(id.endsWith('@lid') ? await mapping?.getPNForLID?.(id) : await mapping?.getLIDForPN?.(id))
    } catch {}
  }
  if (ctx.isGroup && typeof ctx.sock.groupMetadata === 'function') {
    try {
      const metadata = await ctx.sock.groupMetadata(ctx.jid)
      const member = await findGroupParticipant(ctx.sock, metadata?.participants || [], [...ids])
      add(member?.id); add(member?.phoneNumber); add(member?.lid)
    } catch {}
  }
  // Only use verified alternate identities. A LID's digits are not a phone number.
  const candidates = [...ids].sort((a,b) => Number(b.endsWith('@s.whatsapp.net')) - Number(a.endsWith('@s.whatsapp.net')))
  let lastStatus = null
  for (const jid of candidates) {
    for (const type of ['image', 'preview']) {
      try {
        const url = await ctx.sock.profilePictureUrl(jid, type)
        if (url) return { url, jid: target }
      } catch (error) {
        lastStatus = error?.output?.statusCode || error?.statusCode || error?.code || 'unavailable'
      }
    }
  }
  console.warn('RS avatar unavailable:', { candidates: candidates.length, status: lastStatus })
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
