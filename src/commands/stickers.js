import { proto, prepareWAMessageMedia, generateWAMessageFromContent } from '@whiskeysockets/baileys'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { makeStickerPackId } from '../lib/sticker-identity.js'
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

let videoConversionBusy = false

async function videoToWebp(buffer, compact = false) {
  if (videoConversionBusy) throw new Error('Otra conversión de video está en proceso.')
  videoConversionBusy = true
  let dir
  try {
    dir = await fs.mkdtemp(path.join(os.tmpdir(), 'randy-webp-'))
    const input = path.join(dir, 'input.mp4')
    const output = path.join(dir, 'output.webp')
    await fs.writeFile(input, buffer)
    // Keep the canvas 512x512; reduce frame rate, effective resolution and
    // quality progressively instead of rejecting an oversized first encode.
    const profiles = compact
      ? [[10, 384, 48], [8, 320, 36], [6, 256, 25], [4, 192, 12], [2, 128, 8]]
      : [[12, 512, 65], [8, 320, 36], [6, 256, 25], [4, 192, 12], [2, 128, 8]]
    const deadline = Date.now() + 35000
    for (const [fps, size, quality] of profiles) {
      const remaining = deadline - Date.now()
      if (remaining < 1000) break
      await new Promise((resolve, reject) => {
        const args = [
          '-nostdin', '-y', '-threads', '1', '-i', input,
          '-filter_threads', '1', '-t', '8',
          '-vf', 'fps=' + fps + ',scale=' + size + ':' + size + ':force_original_aspect_ratio=increase:flags=bilinear,crop=' + size + ':' + size + ',scale=512:512:flags=neighbor',
          '-c:v', 'libwebp_anim', '-threads', '1', '-quality', String(quality), '-compression_level', '3',
          '-loop', '0', '-an', '-vsync', '0', output
        ]
        const proc = spawn(ffmpegPath, args, { stdio: ['ignore', 'ignore', 'pipe'] })
        let stderr = ''
        const timer = setTimeout(() => proc.kill('SIGKILL'), remaining)
        proc.stderr.on('data', chunk => { stderr = (stderr + String(chunk)).slice(-4000) })
        proc.once('error', error => { clearTimeout(timer); reject(error) })
        proc.once('close', code => {
          clearTimeout(timer)
          if (code === 0) resolve()
          else reject(new Error('ffmpeg ' + code + ': ' + stderr.slice(-500)))
        })
      })
      const stat = await fs.stat(output)
      console.log('Sticker compression:', { fps, size, quality, bytes: stat.size })
      if (stat.size > 0 && stat.size <= 490000) return await fs.readFile(output)
    }
    throw new Error('STICKER_SIZE_LIMIT')
  } finally {
    if (dir) await fs.rm(dir, { recursive: true, force: true }).catch(() => {})
    videoConversionBusy = false
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

function buildStickerExif(pack, author, fresh = false) {
  const metadata = Buffer.from(JSON.stringify({ 'sticker-pack-id': makeStickerPackId(pack, author, { fresh }), 'sticker-pack-name': pack, 'sticker-pack-publisher': author, emojis: ['⚡'] }), 'utf8')
  const exif = Buffer.concat([Buffer.from([0x49,0x49,0x2a,0x00,0x08,0x00,0x00,0x00,0x01,0x00,0x41,0x57,0x07,0x00,0x00,0x00,0x00,0x00,0x16,0x00,0x00,0x00]), metadata])
  exif.writeUInt32LE(metadata.length, 14)
  return exif
}

function addStickerMetadata(webp, pack, author, { fresh = false } = {}) {
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
  const exifChunk = { type: 'EXIF', data: buildStickerExif(pack, author, fresh) }
  const xmpIndex = filtered.findIndex(chunk => chunk.type === 'XMP ')
  if (xmpIndex >= 0) filtered.splice(xmpIndex, 0, exifChunk); else filtered.push(exifChunk)
  return rebuildWebp(filtered)
}

// Keep a small, chat-scoped index of descriptors of sound stickers the bot
// has just sent. Quoted messages can omit the new audio field on older clients.
// Do not store audio bytes or persist private media across restarts.
const recentSoundStickers = new Map()
const SOUND_TTL = 6 * 60 * 60 * 1000
const soundScope = ctx => JSON.stringify([String(ctx.sock.user?.id || ''), ctx.jid])
function soundHash(content) {
  const value = content?.fileEncSha256
  if (!(value instanceof Uint8Array) || value.length !== 32) return ''
  return Buffer.from(value).toString('base64')
}
function validSoundAudio(audio) {
  return Boolean(audio?.mediaKey?.length === 32 && (audio.directPath || audio.url))
}
function rememberSoundSticker(ctx, id, content, audio) {
  if (!id || !validSoundAudio(audio)) return
  const scope = soundScope(ctx)
  const key = JSON.stringify([scope, id])
  const now = Date.now()
  for (const [k,v] of recentSoundStickers) if (v.expires <= now) recentSoundStickers.delete(k)
  recentSoundStickers.delete(key)
  while (recentSoundStickers.size >= 300) recentSoundStickers.delete(recentSoundStickers.keys().next().value)
  recentSoundStickers.set(key,{scope,hash:soundHash(content),audio,expires:now+SOUND_TTL})
}
function recoverSoundSticker(ctx, content) {
  const info = ctx.msg?.message?.extendedTextMessage?.contextInfo ||
    ctx.msg?.message?.imageMessage?.contextInfo || ctx.msg?.message?.videoMessage?.contextInfo
  const scope = soundScope(ctx), hash = soundHash(content), now = Date.now()
  const exact = info?.stanzaId && recentSoundStickers.get(JSON.stringify([scope,info.stanzaId]))
  if (exact && exact.expires > now && (!hash || !exact.hash || exact.hash === hash)) return exact.audio
  if (!hash) return null
  const matches = [...recentSoundStickers.values()].filter(v=>v.scope===scope && v.hash===hash && v.expires>now)
  // Avoid choosing a different soundtrack if several messages match.
  return matches.length===1 ? matches[0].audio : null
}
// Inspect only ordinary sticker messages delivered to this bot. Retain
// the existing bounded, chat-scoped descriptor cache; no media download.
function findSoundSticker(message, depth = 0) {
  if (!message || typeof message !== 'object' || depth > 3) return null
  const sticker = message.stickerMessage
  if (sticker) {
    const audio = sticker.audioMessage || soundAudio.get(sticker)
    if (validSoundAudio(audio)) return { sticker, audio }
  }
  for (const key of ['audioStickerMessage','ephemeralMessage','deviceSentMessage']) {
    const nested = message[key]?.message
    const found = findSoundSticker(nested, depth + 1)
    if (found) return found
  }
  return null
}
export function rememberIncomingSoundSticker(sock, msg) {
  const jid = msg?.key?.remoteJid
  if (!jid || !(jid.endsWith('@g.us') || jid.endsWith('@s.whatsapp.net') || jid.endsWith('@lid'))) return
  const found = findSoundSticker(msg.message)
  if (!found) return
  rememberSoundSticker({sock,jid},msg.key.id,found.sticker,found.audio)
}
async function mediaAsWebp(ctx) {
  const { buffer, type, content } = await ctx.downloadQuotedOrCurrent()
  if (type.includes('imageMessage')) return { webp: await imageToWebp(buffer), audio: null }
  if (type.includes('stickerMessage')) {
    const quoted = ctx.msg?.message?.extendedTextMessage?.contextInfo?.quotedMessage || ctx.msg?.message?.imageMessage?.contextInfo?.quotedMessage || ctx.msg?.message?.videoMessage?.contextInfo?.quotedMessage
    const embedded = content?.audioMessage || soundAudio.get(content) || findSoundSticker(quoted)?.audio
    const audio = validSoundAudio(embedded) ? embedded : recoverSoundSticker(ctx,content)
    console.info('RS sticker edit source:', { audio: Boolean(audio), embedded: Boolean(embedded), recovered: Boolean(audio && audio !== embedded) })
    if (embedded && !audio) throw new Error('SOUND_STICKER_AUDIO_UNAVAILABLE')
    return { webp: buffer, audio }
  }
  throw new Error('unsupported sticker source')
}

async function sendEditedSticker(ctx, sticker, audio) {
  if (!audio) return ctx.sock.sendMessage(ctx.jid, { sticker }, { quoted: ctx.msg })
  if (!soundStickerCodecReady() || !audio.mediaKey || !(audio.directPath || audio.url)) throw new Error('SOUND_STICKER_AUDIO_UNAVAILABLE')
  return relaySoundSticker(ctx, sticker, audio)
}

async function swm(ctx) {
  try {
    const { webp, audio } = await mediaAsWebp(ctx)
    const [packPart, authorPart] = ctx.args.join(' ').trim().split('|').map(value => value.trim())
    const sticker = addStickerMetadata(webp, (packPart || 'RANDY SYSTEMS').slice(0, 100), (authorPart || 'Randy').slice(0, 100))
    return await sendEditedSticker(ctx, sticker, audio)
  } catch (error) { console.error('SWM sticker error:', error); return ctx.reply('❌ No pude cambiar el nombre del sticker. Responde a una imagen o sticker con *.swm Nombre | Autor*.') }
}

async function ske(ctx) {
  const customName = ctx.args.join(' ').trim()
  if (!customName) return ctx.reply('❌ Escribe el nombre. Ejemplo: *.ske Randy*')
  try {
    const { webp, audio } = await mediaAsWebp(ctx)
    const sticker = addStickerMetadata(webp, customName.slice(0, 100), '', { fresh: true })
    return await sendEditedSticker(ctx, sticker, audio)
  } catch (error) {
    const status = error?.output?.statusCode || error?.status || error?.code || 'unknown'
    console.error('SKE failed:', { status, reason: String(error?.message || error).slice(0, 160) })
    return ctx.reply('❌ No se pudo crear el sticker. Si es uno viejo de Favoritos, WhatsApp podría no entregar el archivo original. Prueba reenviándolo como imagen normal, o usa una foto con .s antes de cambiarle el nombre con .ske.')
  }
}

async function letr(ctx) {
  try {
    const text = ctx.args.join(' ').trim()
    if (!text) return ctx.reply('❌ Escribe el texto. Ejemplo: *.letr hola*')
    return ctx.sock.sendMessage(ctx.jid, { sticker: await textToSticker(text) }, { quoted: ctx.msg })
  } catch (error) { console.error('LETR sticker error:', error); return ctx.reply('❌ No pude crear el sticker de texto. Prueba con un texto más corto.') }
}

async function sck(ctx) {
  try { const { webp, audio } = await mediaAsWebp(ctx); return await sendEditedSticker(ctx, stripStickerMetadata(webp), audio) }
  catch (error) { console.error('SCK sticker error:', error); return ctx.reply('❌ No pude limpiar ese sticker. Responde directamente al sticker o imagen con *.sck*.') }
}

async function cl(ctx) {
  try {
    const { webp, audio } = await mediaAsWebp(ctx)
    const pack = String(ctx.args.join(' ').trim() || ctx.msg?.pushName || ctx.senderNumber || 'Usuario').slice(0, 100)
    const author = String(config.botName || 'RANDY SYSTEMS').slice(0, 100)
    return await sendEditedSticker(ctx, addStickerMetadata(webp, pack, author), audio)
  } catch (error) { console.error('CL sticker error:', error); return ctx.reply('❌ Responde a una imagen o sticker con *.cl*. El pack llevará tu nombre y el autor será RANDY SYSTEMS.') }
}


// Extend only the sticker wire codec, leaving the pinned connection library intact.
const StickerProto = proto.Message.StickerMessage
const originalStickerEncode = StickerProto.encode
const originalStickerDecode = StickerProto.decode
const originalMessageDecode = proto.Message.decode
const stickerWireFields = new WeakMap()
const soundAudio = new WeakMap()

// Inspect a bounded protobuf slice, keeping only the embedded media descriptor.
function wireSlice(reader, length) {
  const input = reader?.buf instanceof Uint8Array ? reader.buf : reader instanceof Uint8Array ? reader : null
  const start = reader?.pos ?? 0
  const end = length == null ? (reader?.len ?? input?.length ?? 0) : start + length
  if (!input || end > input.length || end < start || end-start > 1024*1024) return null
  return input.subarray(start,end)
}
function wireFields(bytes) {
  if (!bytes) return []
  let p=0
  const fields=[]
  function varint() {
    let n=0, f=1
    for(let i=0;i<10 && p<bytes.length;i++){
      const b=bytes[p++]; n+=(b&127)*f
      if(!(b&128))return n
      f*=128
    }
    throw new Error('invalid varint')
  }
  while(p<bytes.length && fields.length<512){
    const tag=varint(), field=Math.floor(tag/8), wire=tag%8
    if(!field)throw new Error('invalid field')
    let data=null
    if(wire===0)varint()
    else if(wire===1)p+=8
    else if(wire===5)p+=4
    else if(wire===2){
      const n=varint()
      if(!Number.isSafeInteger(n)||n<0||p+n>bytes.length)throw new Error('invalid field length')
      data=bytes.subarray(p,p+n);p+=n
    }else throw new Error('unsupported wire type')
    if(p>bytes.length)throw new Error('truncated wire')
    fields.push({field,wire,data})
  }
  return fields
}
// The install-time WAProto schema now defines the audio fields natively.
// Keep flat stickers for Baileys media classification, and preserve audio
// through the generated fromObject/toObject/encode/decode methods.
StickerProto.decode = function(reader,length,...rest) {
  const bytes=wireSlice(reader,length)
  const result=originalStickerDecode.call(this,reader,length,...rest)
  try {
    stickerWireFields.set(result,wireFields(bytes).map(f=>f.field+':'+f.wire).join(', '))
    if(result.audioMessage) soundAudio.set(result,result.audioMessage)
  } catch {}
  return result
}
proto.Message.decode = function(reader,length,...rest) {
  const result=originalMessageDecode.call(this,reader,length,...rest)
  const sticker=result.audioStickerMessage?.message?.stickerMessage
  if(sticker && (!result.stickerMessage || validSoundAudio(sticker.audioMessage))) {
    result.stickerMessage=sticker
    delete result.audioStickerMessage
  }
  return result
}
const originalMessageEncode=proto.Message.encode
proto.Message.encode=function(message,writer) {
  const sticker=message?.stickerMessage
  const audio=sticker && (sticker.audioMessage || soundAudio.get(sticker))
  if(!audio) return originalMessageEncode.call(this,message,writer)
  writer=originalMessageEncode.call(this,{...message,stickerMessage:undefined,audioStickerMessage:undefined},writer)
  const nested=writer.uint32(1074).fork().uint32(10).fork().uint32(210).fork()
  originalStickerEncode.call(StickerProto,{...sticker,audioMessage:undefined},nested)
  nested.uint32(192).uint32(0)
  proto.Message.AudioMessage.encode(audio,nested.uint32(210).fork()).ldelim()
  nested.ldelim().ldelim().ldelim()
  return writer
}
function soundStickerCodecReady() {
  const audio=new proto.Message.AudioMessage({seconds:3,mediaKey:Buffer.alloc(32,1),directPath:'/codec-test'})
  const sample=proto.Message.fromObject({stickerMessage:{isAnimated:true,audioMessage:audio}})
  const encoded=proto.Message.encode(sample).finish()
  const decoded=proto.Message.decode(encoded)
  return wireFields(encoded).some(f=>f.field===134) &&
    decoded.stickerMessage?.audioMessage?.seconds===3 &&
    decoded.stickerMessage.audioMessage.mediaKey?.length===32
}
let audioStickerBusy = false

async function extractStickerAudio(buffer) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'randy-audio-'))
  const input = path.join(dir, 'input.mp4')
  const output = path.join(dir, 'audio.ogg')
  try {
    await fs.writeFile(input, buffer)
    await new Promise((resolve, reject) => {
      const proc = spawn(ffmpegPath, [
        '-nostdin', '-y', '-i', input, '-map', '0:a:0',
        '-t', '8', '-vn', '-c:a', 'libopus', '-b:a', '48k', '-ac', '1', output
      ], { stdio: ['ignore', 'ignore', 'pipe'] })
      let stderr = ''
      const timer = setTimeout(() => proc.kill('SIGKILL'), 20000)
      proc.stderr.on('data', chunk => { stderr = (stderr + String(chunk)).slice(-2000) })
      proc.once('error', error => { clearTimeout(timer); reject(error) })
      proc.once('close', code => {
        clearTimeout(timer)
        if (code === 0) resolve()
        else reject(new Error('Audio unavailable: ' + stderr.slice(-400)))
      })
    })
    return await fs.readFile(output)
  } finally {
    await fs.rm(dir, { recursive: true, force: true }).catch(() => {})
  }
}

async function relaySoundSticker(ctx, sticker, audio) {
  const prepared = await prepareWAMessageMedia({ sticker, isAnimated: parseWebpChunks(sticker).some(c=>c.type==='ANIM') }, { upload: ctx.sock.waUploadToServer })
  const payload = generateWAMessageFromContent(ctx.jid, prepared, { userJid: ctx.sock.user.id, quoted: ctx.msg })
  if (!payload.message?.stickerMessage || !audio) throw new Error('SOUND_STICKER_MEDIA')
  payload.message.stickerMessage.audioMessage = audio
  soundAudio.set(payload.message.stickerMessage, audio)
  const wire = proto.Message.encode(payload.message).finish()
  if (!wireFields(wire).some(f=>f.field===134)) throw new Error('SOUND_STICKER_WIRE')
  console.info('RS sound sticker: native envelope encoded', { bytes: wire.length })
  const result = await ctx.sock.relayMessage(ctx.jid, payload.message, { messageId: payload.key.id })
  rememberSoundSticker(ctx, payload.key.id, payload.message.stickerMessage, audio)
  return result
}

async function stickerWithAudio(ctx) {
  if (audioStickerBusy) return ctx.reply('⏳ Hay otro sticker con audio en proceso. Intenta nuevamente en unos segundos.')
  audioStickerBusy = true
  try {
    const { buffer, type, content } = await ctx.downloadQuotedOrCurrent()
    if (type !== 'videoMessage') return ctx.reply('🎵 Responde a un video con sonido de hasta 8 segundos usando *.sa*. Recibirás un sticker animado con sonido integrado (experimental).')
    if (Number(content?.seconds || 0) > 8 || buffer.length > 8 * 1024 * 1024) return ctx.reply('❌ Usa un video de máximo 8 segundos y 8 MB.')
    const audio = await extractStickerAudio(buffer)
    let sticker = await videoToWebp(buffer, true)
    const name = ctx.args.join(' ').trim()
    if (name) sticker = addStickerMetadata(sticker, name.slice(0,100), '', { fresh:true })
    if (!soundStickerCodecReady()) throw new Error('SOUND_STICKER_CODEC')
    const preparedAudio = await prepareWAMessageMedia({ audio, mimetype: 'audio/ogg; codecs=opus', ptt: false, seconds: Number(content?.seconds || 0) || undefined }, { upload: ctx.sock.waUploadToServer })
    await relaySoundSticker(ctx, sticker, preparedAudio.audioMessage)
    return
  } catch (error) {
    console.error('Audio sticker error:', String(error?.message || error).slice(0, 200))
    return ctx.reply(error?.message === 'STICKER_SIZE_LIMIT' ? '❌ No logré comprimir este video al límite de WhatsApp. Intenta con otro clip.' : '❌ No pude crear el sticker con audio. Comprueba que el video tenga sonido y dure hasta 8 segundos; si hay otra conversión, intenta después.')
  } finally {
    audioStickerBusy = false
  }
}

// Inspect only the shape of a deliberately quoted message; never expose keys or media URLs.
async function soundInfo(ctx) {
  const quoted = ctx.msg.message?.extendedTextMessage?.contextInfo?.quotedMessage
  if (!quoted) return ctx.reply('Responde a un sticker sonoro original con .soundinfo.')
  const lines = []
  function walk(obj, prefix = '', depth = 0) {
    if (!obj || typeof obj !== 'object' || depth > 5 || lines.length >= 60) return
    for (const key of Object.keys(obj)) {
      if (lines.length >= 60) break
      const value = obj[key]
      if (value == null) continue
      const path = prefix + key
      if (['contextInfo','mediaKey','fileSha256','fileEncSha256','url','directPath','participant','remoteJid','stanzaId'].includes(key)) continue
      if (Buffer.isBuffer(value) || value instanceof Uint8Array) lines.push(path + ': bytes (' + value.length + ')')
      else if (typeof value === 'object') { lines.push(path + ': object'); walk(value, path + '.', depth + 1) }
      else if (['isAnimated','isLottie','seconds','mimetype','width','height'].includes(key)) lines.push(path + ': ' + String(value).slice(0,80))
      else lines.push(path + ': ' + typeof value)
    }
  }
  walk(quoted)
  const wire = quoted.stickerMessage && stickerWireFields.get(quoted.stickerMessage)
  lines.push('Wire tags: ' + (wire || 'no disponibles; el mensaje pudo ser reconstruido'))
  lines.push('Audio original reconocido: ' + (findSoundSticker(quoted) ? 'sí' : 'no'))
  const source = quoted.stickerMessage || quoted.audioStickerMessage?.message?.stickerMessage
  lines.push('Audio recuperable de mensajes recientes: ' + (recoverSoundSticker(ctx,source) ? 'sí' : 'no'))
  return ctx.reply('🔬 SOUND INFO — campos reconocidos por Baileys\n' + (lines.join('\n') || 'Sin campos reconocidos') + '\nLos campos desconocidos pueden haber sido descartados por el decodificador.')
}

export const stickerCommands = {
  soundinfo: soundInfo,
  sa: stickerWithAudio,
  saudio: stickerWithAudio,
  stickeraudio: stickerWithAudio,
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
  stickerinfo: async ctx => ctx.reply('🎨 *COMANDOS DE STICKERS*\n• *.sticker* / *.s* → convierte imagen o video corto en sticker.\n• *.letr texto* → sticker de texto en MAYÚSCULAS, fondo blanco completo y letra fina.\n• *.cl* → sticker con tu nombre como pack y RANDY SYSTEMS como autor.\n• *.ske Nombre* → crea una copia con ese nombre, sin autor; conserva el audio si WhatsApp entrega sus datos. Si tenías la versión anterior en Favoritos, elimínala y guarda la nueva; WhatsApp no permite renombrar favoritos existentes desde el bot.\n• *.sck* → sticker limpio, sin nombre, autor ni metadata del bot.\n• *.swm Nombre | Autor* → cambia nombre del pack y autor.\n• *.toimg* → convierte un sticker en imagen.\n• *.sa* / *.stickeraudio* → sticker animado con sonido integrado (experimental) de un video con sonido (máx. 8 s). Usa .sa Nombre para añadir el nombre desde la creación.')
}
