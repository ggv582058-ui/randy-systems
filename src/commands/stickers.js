import sharp from 'sharp'

async function imageToWebp(buffer) {
  return sharp(buffer).resize(512, 512, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).webp({ quality: 82 }).toBuffer()
}

export const stickerCommands = {
  sticker: async ctx => { try { const { buffer, type } = await ctx.downloadQuotedOrCurrent(); if (!type.includes('imageMessage')) return ctx.reply('Por ahora .sticker acepta imágenes. Responde a una imagen o envíala con .sticker'); const webp = await imageToWebp(buffer); return ctx.sock.sendMessage(ctx.jid, { sticker: webp }, { quoted: ctx.msg }) } catch { return ctx.reply('❌ Responde a una imagen o envía una imagen con .sticker') } },
  s: async ctx => stickerCommands.sticker(ctx),
  stickerwm: async ctx => stickerCommands.sticker(ctx),
  toimg: async ctx => { try { const { buffer, type } = await ctx.downloadQuotedOrCurrent(); if (!type.includes('stickerMessage')) return ctx.reply('Responde a un sticker con .toimg'); const png = await sharp(buffer).png().toBuffer(); return ctx.sock.sendMessage(ctx.jid, { image: png, caption: '✅ Sticker convertido.' }, { quoted: ctx.msg }) } catch { return ctx.reply('❌ No pude convertir ese sticker.') } },
  stickerinfo: async ctx => ctx.reply('🎨 Sticker: responde a una imagen con *.sticker*.\nConversión: responde a un sticker con *.toimg*.')
}
