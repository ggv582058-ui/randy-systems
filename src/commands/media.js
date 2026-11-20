import { downloadContentFromMessage } from '@whiskeysockets/baileys'
import { getQuotedImage, isAuthorOfQuotedMessage } from '../lib/own-media.js'

const MAX_PHOTO_BYTES = 16 * 1024 * 1024

async function resendOwnPhoto(ctx) {
  if (!ctx.isGroup) return ctx.reply('📸 Por seguridad, .ver funciona en grupos y solo con fotos que tú enviaste.')
  if (!await isAuthorOfQuotedMessage(ctx.sock, ctx.participants, ctx.msg, ctx.sender)) {
    return ctx.reply('🔒 Responde con .ver a una foto enviada por ti. No puedo copiar fotos privadas de otros usuarios.')
  }

  const image = getQuotedImage(ctx.msg)
  if (!image) {
    return ctx.reply('❌ No tengo los datos de esa foto. Responde directamente a tu propia imagen con .ver. Si era de una sola vista y WhatsApp ya la retiró, no puedo recuperarla.')
  }

  try {
    const stream = await downloadContentFromMessage(image, 'image')
    const chunks = []
    let total = 0
    for await (const chunk of stream) {
      total += chunk.length
      if (total > MAX_PHOTO_BYTES) throw new Error('photo too large')
      chunks.push(chunk)
    }
    if (!total) throw new Error('empty photo')
    return await ctx.sock.sendMessage(ctx.jid, {
      image: Buffer.concat(chunks),
      caption: '📸 RANDY SYSTEMS | Foto reenviada por su autor.'
    }, { quoted: ctx.msg })
  } catch (error) {
    console.error('VER own-photo resend error:', error?.message || error)
    return ctx.reply('❌ WhatsApp no permitió descargar esa foto. Es posible que haya expirado o que no esté disponible para el bot.')
  }
}

export const mediaCommands = {
  ver: resendOwnPhoto
}
