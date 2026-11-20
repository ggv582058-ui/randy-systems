import { downloadContentFromMessage } from '@whiskeysockets/baileys'
import { getQuotedImageInfo, isAuthorOfQuotedMessage } from '../lib/own-media.js'

const MAX_PHOTO_BYTES = 16 * 1024 * 1024

async function resendOwnPhoto(ctx) {
  if (!ctx.isGroup) return ctx.reply('📸 Por seguridad, .ver funciona en grupos y solo con fotos que tú enviaste.')
  if (!await isAuthorOfQuotedMessage(ctx.sock, ctx.participants, ctx.msg, ctx.sender)) {
    return ctx.reply('🔒 Responde con .ver a una foto enviada por ti. No puedo copiar fotos privadas de otros usuarios.')
  }

  const { image, isViewOnce } = getQuotedImageInfo(ctx.msg)
  if (!image) {
    return ctx.reply('❌ La foto ya no está adjunta al mensaje citado. Si era de una sola vista, WhatsApp puede retirar los datos y el bot no puede recuperarlos.')
  }

  if (!image.mediaKey || (!image.url && !image.directPath)) {
    return ctx.reply(isViewOnce
      ? '🔒 WhatsApp no entregó el archivo de tu foto de una sola vista. Envíala nuevamente como foto normal para usar .ver.'
      : '❌ Esa foto no incluye los datos necesarios para descargarla. Reenvíala como imagen normal.')
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
    const status = error?.output?.statusCode || error?.status || error?.code || 'unknown'
    console.error('VER media unavailable:', { status, viewOnce: isViewOnce })
    return ctx.reply(isViewOnce
      ? '🔒 WhatsApp no permitió recuperar esa foto de una sola vista. Mándala como foto normal y después responde con .ver.'
      : '❌ No pude descargar tu foto. Puede haber caducado o fallado la descarga. Intenta reenviarla como imagen normal.')

  }
}

export const mediaCommands = {
  ver: resendOwnPhoto
}
