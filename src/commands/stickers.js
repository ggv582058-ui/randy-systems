import sharp from 'sharp'

async function imageToWebp(buffer) {
  return sharp(buffer)
    .resize(512, 512, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .webp({ quality: 82 })
    .toBuffer()
}

function makeChunk(type, data) {
  const header = Buffer.alloc(8)
  header.write(type, 0, 4, 'ascii')
  header.writeUInt32LE(data.length, 4)
  return Buffer.concat([header, data, data.length % 2 ? Buffer.from([0]) : Buffer.alloc(0)])
}

function writeUInt24LE(buffer, value, offset) {
  buffer[offset] = value & 0xff
  buffer[offset + 1] = (value >>> 8) & 0xff
  buffer[offset + 2] = (value >>> 16) & 0xff
}

function buildStickerExif(pack, author) {
  const metadata = Buffer.from(JSON.stringify({
    'sticker-pack-id': 'randy-systems',
    'sticker-pack-name': pack,
    'sticker-pack-publisher': author,
    emojis: ['⚡']
  }), 'utf8')

  const exif = Buffer.concat([
    Buffer.from([
      0x49, 0x49, 0x2a, 0x00, 0x08, 0x00, 0x00, 0x00,
      0x01, 0x00, 0x41, 0x57, 0x07, 0x00, 0x00, 0x00,
      0x00, 0x00, 0x16, 0x00, 0x00, 0x00
    ]),
    metadata
  ])
  exif.writeUInt32LE(metadata.length, 14)
  return exif
}

function addStickerMetadata(webp, pack, author) {
  if (webp.length < 12 || webp.toString('ascii', 0, 4) !== 'RIFF' || webp.toString('ascii', 8, 12) !== 'WEBP') {
    throw new Error('El archivo no es un WebP válido.')
  }

  const chunks = []
  let offset = 12
  while (offset + 8 <= webp.length) {
    const type = webp.toString('ascii', offset, offset + 4)
    const size = webp.readUInt32LE(offset + 4)
    const start = offset + 8
    const end = start + size
    if (end > webp.length) break
    chunks.push({ type, data: Buffer.from(webp.subarray(start, end)) })
    offset = end + (size % 2)
  }

  const filtered = chunks.filter(chunk => chunk.type !== 'EXIF')
  let vp8x = filtered.find(chunk => chunk.type === 'VP8X')

  if (vp8x) {
    vp8x.data[0] |= 0x08
  } else {
    let width = 0
    let height = 0
    let hasAlpha = false
    const vp8 = filtered.find(chunk => chunk.type === 'VP8 ')
    const vp8l = filtered.find(chunk => chunk.type === 'VP8L')

    if (vp8?.data?.length >= 10) {
      width = vp8.data.readUInt16LE(6) & 0x3fff
      height = vp8.data.readUInt16LE(8) & 0x3fff
    } else if (vp8l?.data?.length >= 5) {
      const bits = vp8l.data.readUInt32LE(1)
      width = (bits & 0x3fff) + 1
      height = ((bits >>> 14) & 0x3fff) + 1
      hasAlpha = Boolean((bits >>> 28) & 1)
    }

    if (!width || !height) throw new Error('No pude leer las dimensiones del sticker.')

    const data = Buffer.alloc(10)
    data[0] = 0x08 | (hasAlpha ? 0x10 : 0)
    writeUInt24LE(data, width - 1, 4)
    writeUInt24LE(data, height - 1, 7)
    vp8x = { type: 'VP8X', data }
    filtered.unshift(vp8x)
  }

  const exifChunk = { type: 'EXIF', data: buildStickerExif(pack, author) }
  const xmpIndex = filtered.findIndex(chunk => chunk.type === 'XMP ')
  if (xmpIndex >= 0) filtered.splice(xmpIndex, 0, exifChunk)
  else filtered.push(exifChunk)

  const body = Buffer.concat(filtered.map(chunk => makeChunk(chunk.type, chunk.data)))
  const header = Buffer.alloc(12)
  header.write('RIFF', 0, 4, 'ascii')
  header.writeUInt32LE(body.length + 4, 4)
  header.write('WEBP', 8, 4, 'ascii')
  return Buffer.concat([header, body])
}

async function swm(ctx) {
  try {
    const { buffer, type } = await ctx.downloadQuotedOrCurrent()
    const text = ctx.args.join(' ').trim()
    const [packPart, authorPart] = text.split('|').map(value => value.trim())
    const pack = (packPart || 'RANDY SYSTEMS').slice(0, 100)
    const author = (authorPart || 'Randy').slice(0, 100)

    let webp
    if (type.includes('imageMessage')) webp = await imageToWebp(buffer)
    else if (type.includes('stickerMessage')) webp = buffer
    else return ctx.reply('❌ Responde a una imagen o sticker con *.swm Nombre | Autor*.')

    const sticker = addStickerMetadata(webp, pack, author)
    return ctx.sock.sendMessage(ctx.jid, { sticker }, { quoted: ctx.msg })
  } catch (error) {
    console.error('SWM sticker error:', error)
    return ctx.reply('❌ No pude cambiar el nombre del sticker. Responde a una imagen o sticker con *.swm Nombre | Autor*.')
  }
}

export const stickerCommands = {
  sticker: async ctx => {
    try {
      const { buffer, type } = await ctx.downloadQuotedOrCurrent()
      if (!type.includes('imageMessage')) return ctx.reply('Por ahora .sticker acepta imágenes. Responde a una imagen o envíala con .sticker')
      const webp = await imageToWebp(buffer)
      return ctx.sock.sendMessage(ctx.jid, { sticker: webp }, { quoted: ctx.msg })
    } catch {
      return ctx.reply('❌ Responde a una imagen o envía una imagen con .sticker')
    }
  },
  s: async ctx => stickerCommands.sticker(ctx),
  swm,
  stickerwm: swm,
  toimg: async ctx => {
    try {
      const { buffer, type } = await ctx.downloadQuotedOrCurrent()
      if (!type.includes('stickerMessage')) return ctx.reply('Responde a un sticker con .toimg')
      const png = await sharp(buffer).png().toBuffer()
      return ctx.sock.sendMessage(ctx.jid, { image: png, caption: '✅ Sticker convertido.' }, { quoted: ctx.msg })
    } catch {
      return ctx.reply('❌ No pude convertir ese sticker.')
    }
  },
  stickerinfo: async ctx => ctx.reply('🎨 Sticker: responde a una imagen con *.sticker*.\nNombre/autor: responde a una imagen o sticker con *.swm RANDY SYSTEMS | Randy*.\nConversión: responde a un sticker con *.toimg*.')
}
