import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { randomBytes } from 'node:crypto'
import { spawn } from 'node:child_process'
import ffmpegPath from 'ffmpeg-static'
import sharp from 'sharp'
import { config } from '../config.js'

async function imageToWebp(buffer) {
  return sharp(buffer)
    .resize(512, 512, { fit: 'cover', position: 'centre' })
    .webp({ quality: 82 })
    .toBuffer()
}

async function videoToWebp(buffer) {
  const id = randomBytes(6).toString('hex')
  const input = path.join(os.tmpdir(), `randy-${id}.mp4`)
  const output = path.join(os.tmpdir(), `randy-${id}.webp`)

  try {
    await fs.writeFile(input, buffer)
    await new Promise((resolve, reject) => {
      const args = [
        '-y', '-i', input,
        '-t', '8',
        '-vf', 'fps=12,scale=512:512:force_original_aspect_ratio=increase:flags=lanczos,crop=512:512',
        '-loop', '0',
        '-an',
        '-vsync', '0',
        output
      ]
      const proc = spawn(ffmpegPath, args, { stdio: ['ignore', 'ignore', 'pipe'] })
      let stderr = ''
      proc.stderr.on('data', chunk => { stderr += String(chunk).slice(-4000) })
      proc.on('error', reject)
      proc.on('close', code => code === 0 ? resolve() : reject(new Error(`ffmpeg ${code}: ${stderr.slice(-800)}`)))
    })
    return await fs.readFile(output)
  } finally {
    await fs.rm(input, { force: true }).catch(() => {})
    await fs.rm(output, { force: true }).catch(() => {})
  }
}

function escapeXml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;')
}

function wrapWords(text, maxChars) {
  const words = String(text).trim().split(/\s+/).filter(Boolean)
  const lines = []
  let line = ''
  for (const word of words) {
    if (word.length > maxChars) {
      if (line) { lines.push(line); line = '' }
      for (let i = 0; i < word.length; i += maxChars) lines.push(word.slice(i, i + maxChars))
      continue
    }
    const candidate = line ? `${line} ${word}` : word
    if (candidate.length <= maxChars) line = candidate
    else { if (line) lines.push(line); line = word }
  }
  if (line) lines.push(line)
  return lines
}

function textStickerLayout(text) {
  const clean = String(text).replace(/\s+/g, ' ').trim().slice(0, 240).toUpperCase()
  const sizes = [66, 60, 54, 48, 44, 40, 36, 32, 28]
  for (const fontSize of sizes) {
    const maxChars = Math.max(7, Math.floor(450 / (fontSize * 0.54)))
    const lines = wrapWords(clean, maxChars)
    const lineHeight = Math.round(fontSize * 1.12)
    if (lines.length <= 7 && lines.length * lineHeight <= 430) return { lines, fontSize, lineHeight }
  }
  return { lines: wrapWords(clean, 20).slice(0, 9), fontSize: 26, lineHeight: 31 }
}

async function textToSticker(text) {
  const { lines, fontSize, lineHeight } = textStickerLayout(text)
  const totalHeight = lines.length * lineHeight
  const startY = Math.round((512 - totalHeight) / 2 + fontSize * 0.82)
  const tspans = lines
    .map((line, index) => `<tspan x="28" y="${Math.round(startY + index * lineHeight)}">${escapeXml(line)}</tspan>`)
    .join('')
  const svg = `<svg width="512" height="512" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg"><rect width="512" height="512" fill="#ffffff"/><text fill="#111111" font-family="Arial, Helvetica, sans-serif" font-size="${fontSize}" font-weight="400" letter-spacing="0">${tspans}</text></svg>`
  return sharp(Buffer.from(svg)).webp({ quality: 92 }).toBuffer()
}

function makeChunk(type, data) {
  const header = Buffer.alloc(8)
  header.write(type, 0, 4, 'ascii')
  header.writeUInt32LE(data.length, 4)
  return Buffer.concat([header, data, data.length % 2 ? Buffer.from([0]) : Buffer.alloc(0)])
}

function parseWebpChunks(webp) {
  if (webp.length < 12 || webp.toString('ascii', 0, 4) !== 'RIFF' || webp.toString('ascii', 8, 12) !== 'WEBP') throw new Error('El archivo no es un WebP válido.')
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
  return chunks
}

function rebuildWebp(chunks) {
  const body = Buffer.concat(chunks.map(chunk => makeChunk(chunk.type, chunk.data)))
  const header = Buffer.alloc(12)
  header.write('RIFF', 0, 4, 'ascii')
  header.writeUInt32LE(body.length + 4, 4)
  header.write('WEBP', 8, 4, 'ascii')
  return Buffer.concat([header, body])
}

function stripStickerMetadata(webp) {
  const chunks = parseWebpChunks(webp)
  const cleaned = chunks.filter(chunk => !['EXIF', 'XMP ', 'ICCP'].includes(chunk.type))
  const vp8x = cleaned.find(chunk => chunk.type === 'VP8X')
  if (vp8x?.data?.length) vp8x.data[0] &= ~0x2c
  return rebuildWebp(cleaned)
}

function writeUInt24LE(buffer, value, offset) {
  buffer[offset] = value & 0xff
  buffer[offset + 1] = (value >>> 8) & 0xff
  buffer[offset + 2] = (value >>> 16) & 0xff
}

function buildStickerExif(pack, author) {
  const metadata = Buffer.from(JSON.stringify({ 'sticker-pack-id': 'randy-systems', 'sticker-pack-name': pack, 'sticker-pack-publisher': author, emojis: ['⚡'] }), 'utf8')
  const exif = Buffer.concat([Buffer.from([0x49,0x49,0x2a,0x00,0x08,0x00,0x00,0x00,0x01,0x00,0x41,0x57,0x07,0x00,0x00,0x00,0x00,0x00,0x16,0x00,0x00,0x00]), metadata])
  exif.writeUInt32LE(metadata.length, 14)
  return exif
}

function addStickerMetadata(webp, pack, author) {
  const chunks = parseWebpChunks(webp)
  const filtered = chunks.filter(chunk => chunk.type !== 'EXIF')
  let vp8x = filtered.find(chunk => chunk.type === 'VP8X')
  if (vp8x) vp8x.data[0] |= 0x08
  else {
    let width = 0, height = 0, hasAlpha = false
    const vp8 = filtered.find(chunk => chunk.type === 'VP8 ')
    const vp8l = filtered.find(chunk => chunk.type === 'VP8L')
    if (vp8?.data?.length >= 10) { width = vp8.data.readUInt16LE(6) & 0x3fff; height = vp8.data.readUInt16LE(8) & 0x3fff }
    else if (vp8l?.data?.length >= 5) { const bits = vp8l.data.readUInt32LE(1); width = (bits & 0x3fff) + 1; height = ((bits >>> 14) & 0x3fff) + 1; hasAlpha = Boolean((bits >>> 28) & 1) }
    if (!width || !height) throw new Error('No pude leer las dimensiones del sticker.')
    const data = Buffer.alloc(10); data[0] = 0x08 | (hasAlpha ? 0x10 : 0); writeUInt24LE(data, width - 1, 4); writeUInt24LE(data, height - 1, 7); vp8x = { type: 'VP8X', data }; filtered.unshift(vp8x)
  }
  const exifChunk = { type: 'EXIF', data: buildStickerExif(pack, author) }
  const xmpIndex = filtered.findIndex(chunk => chunk.type === 'XMP ')
  if (xmpIndex >= 0) filtered.splice(xmpIndex, 0, exifChunk); else filtered.push(exifChunk)
  return rebuildWebp(filtered)
}

async function mediaAsWebp(ctx) {
  const { buffer, type } = await ctx.downloadQuotedOrCurrent()
  if (type.includes('imageMessage')) return imageToWebp(buffer)
  if (type.includes('stickerMessage')) return buffer
  throw new Error('unsupported sticker source')
}

async function swm(ctx) {
  try {
    const webp = await mediaAsWebp(ctx)
    const [packPart, authorPart] = ctx.args.join(' ').trim().split('|').map(value => value.trim())
    const sticker = addStickerMetadata(webp, (packPart || 'RANDY SYSTEMS').slice(0, 100), (authorPart || 'Randy').slice(0, 100))
    return ctx.sock.sendMessage(ctx.jid, { sticker }, { quoted: ctx.msg })
  } catch (error) { console.error('SWM sticker error:', error); return ctx.reply('❌ No pude cambiar el nombre del sticker. Responde a una imagen o sticker con *.swm Nombre | Autor*.') }
}

async function ske(ctx) {
  try {
    const webp = await mediaAsWebp(ctx)
    const customName = ctx.args.join(' ').trim()
    if (!customName) return ctx.reply('❌ Escribe el nombre. Ejemplo: *.ske Randy*')
    return ctx.sock.sendMessage(ctx.jid, { sticker: addStickerMetadata(webp, customName.slice(0, 100), '') }, { quoted: ctx.msg })
  } catch (error) { console.error('SKE sticker error:', error); return ctx.reply('❌ No pude crear ese sticker. Responde a una imagen o sticker con *.ske Nombre*.') }
}

async function letr(ctx) {
  try {
    const text = ctx.args.join(' ').trim()
    if (!text) return ctx.reply('❌ Escribe el texto. Ejemplo: *.letr hola*')
    return ctx.sock.sendMessage(ctx.jid, { sticker: await textToSticker(text) }, { quoted: ctx.msg })
  } catch (error) { console.error('LETR sticker error:', error); return ctx.reply('❌ No pude crear el sticker de texto. Prueba con un texto más corto.') }
}

async function sck(ctx) {
  try { const webp = await mediaAsWebp(ctx); return ctx.sock.sendMessage(ctx.jid, { sticker: stripStickerMetadata(webp) }, { quoted: ctx.msg }) }
  catch (error) { console.error('SCK sticker error:', error); return ctx.reply('❌ No pude limpiar ese sticker. Responde directamente al sticker o imagen con *.sck*.') }
}

async function cl(ctx) {
  try {
    const webp = await mediaAsWebp(ctx)
    const pack = String(ctx.msg?.pushName || ctx.senderNumber || 'Usuario').slice(0, 100)
    const author = String(config.botName || 'RANDY SYSTEMS').slice(0, 100)
    return ctx.sock.sendMessage(ctx.jid, { sticker: addStickerMetadata(webp, pack, author) }, { quoted: ctx.msg })
  } catch (error) { console.error('CL sticker error:', error); return ctx.reply('❌ Responde a una imagen o sticker con *.cl*. El pack llevará tu nombre y el autor será RANDY SYSTEMS.') }
}

export const stickerCommands = {
  sticker: async ctx => {
    try {
      const { buffer, type, content } = await ctx.downloadQuotedOrCurrent()
      if (type.includes('imageMessage')) return ctx.sock.sendMessage(ctx.jid, { sticker: await imageToWebp(buffer) }, { quoted: ctx.msg })
      if (type.includes('videoMessage')) {
        const seconds = Number(content?.seconds || 0)
        if (seconds > 8) return ctx.reply('❌ El video debe durar máximo 8 segundos para convertirlo en sticker.')
        return ctx.sock.sendMessage(ctx.jid, { sticker: await videoToWebp(buffer) }, { quoted: ctx.msg })
      }
      return ctx.reply('❌ Responde a una imagen o video corto con *.s* o *.sticker*.')
    } catch (error) { console.error('Sticker error:', error); return ctx.reply('❌ No pude crear ese sticker. Usa una imagen o un video corto.') }
  },
  s: async ctx => stickerCommands.sticker(ctx),
  cl,
  ske,
  letr,
  sck,
  cleansticker: sck,
  swm,
  stickerwm: swm,
  toimg: async ctx => {
    try { const { buffer, type } = await ctx.downloadQuotedOrCurrent(); if (!type.includes('stickerMessage')) return ctx.reply('Responde a un sticker con .toimg'); const png = await sharp(buffer).png().toBuffer(); return ctx.sock.sendMessage(ctx.jid, { image: png, caption: '✅ Sticker convertido.' }, { quoted: ctx.msg }) }
    catch { return ctx.reply('❌ No pude convertir ese sticker.') }
  },
  stickerinfo: async ctx => ctx.reply('🎨 *COMANDOS DE STICKERS*\n• *.sticker* / *.s* → convierte imagen o video corto en sticker.\n• *.letr texto* → sticker de texto en MAYÚSCULAS, fondo blanco completo y letra fina.\n• *.cl* → sticker con tu nombre como pack y RANDY SYSTEMS como autor.\n• *.ske Nombre* → sticker con SOLO el nombre que escribas, sin nombre del bot.\n• *.sck* → sticker limpio, sin nombre, autor ni metadata del bot.\n• *.swm Nombre | Autor* → cambia nombre del pack y autor.\n• *.toimg* → convierte un sticker en imagen.')
}
