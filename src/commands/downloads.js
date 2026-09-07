import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
import axios from 'axios'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const ytdlp = require('youtube-dl-exec')

const MAX_MEDIA_BYTES = 45 * 1024 * 1024
const DOWNLOAD_TIMEOUT_MS = 120000
const HTTP_TIMEOUT_MS = 30000

function safeName(value = 'media') {
  return String(value)
    .normalize('NFKD')
    .replace(/[^\w\s.-]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 80) || 'media'
}

function looksLikeUrl(value = '') {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol)
  } catch {
    return false
  }
}

function isSpotifyUrl(value = '') {
  try { return new URL(value).hostname.endsWith('spotify.com') } catch { return false }
}

function firstEntry(info) {
  if (Array.isArray(info?.entries) && info.entries.length) return info.entries[0]
  return info
}

async function spotifySearchText(url) {
  const { data } = await axios.get('https://open.spotify.com/oembed', {
    params: { url },
    timeout: 12000,
    headers: { 'user-agent': 'Mozilla/5.0 RANDY-SYSTEMS/1.0' }
  })
  const title = data?.title || ''
  const artist = data?.author_name || ''
  const query = `${title} ${artist} audio`.trim()
  if (!query) throw new Error('No pude leer esa canción de Spotify.')
  return { query, title, artist }
}

async function getInfo(target) {
  const raw = await ytdlp(target, {
    dumpSingleJson: true,
    skipDownload: true,
    noWarnings: true,
    noPlaylist: true,
    socketTimeout: 15,
    retries: 1,
    extractorRetries: 1
  }, { timeout: 30000 })
  return firstEntry(raw)
}

async function downloadToTemp(target, format) {
  const id = `${Date.now()}-${crypto.randomBytes(4).toString('hex')}`
  const stem = path.join(os.tmpdir(), `randy-${id}`)
  const output = `${stem}.%(ext)s`

  await ytdlp(target, {
    output,
    format,
    noPlaylist: true,
    noWarnings: true,
    maxFilesize: '45M',
    socketTimeout: 15,
    retries: 2,
    fragmentRetries: 2,
    concurrentFragments: 2
  }, { timeout: DOWNLOAD_TIMEOUT_MS })

  const dir = path.dirname(stem)
  const prefix = path.basename(stem)
  const names = await fs.readdir(dir)
  const match = names.find(name => name.startsWith(prefix + '.'))
  if (!match) throw new Error('No se generó el archivo multimedia.')

  const filePath = path.join(dir, match)
  const stat = await fs.stat(filePath)
  if (stat.size > MAX_MEDIA_BYTES) {
    await fs.rm(filePath, { force: true }).catch(() => {})
    throw new Error('El archivo supera el límite de 45 MB para enviarlo por WhatsApp.')
  }
  return filePath
}

async function downloadHttpBuffer(url) {
  const response = await axios.get(url, {
    responseType: 'arraybuffer',
    timeout: HTTP_TIMEOUT_MS,
    maxContentLength: MAX_MEDIA_BYTES,
    maxBodyLength: MAX_MEDIA_BYTES,
    headers: {
      'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148',
      accept: '*/*'
    }
  })
  const buffer = Buffer.from(response.data)
  if (!buffer.length) throw new Error('La fuente devolvió un archivo vacío.')
  if (buffer.length > MAX_MEDIA_BYTES) throw new Error('El archivo supera 45 MB.')
  return buffer
}

async function tiktokFallback(url) {
  const { data } = await axios.get('https://www.tikwm.com/api/', {
    params: { url, hd: 1 },
    timeout: 20000,
    headers: { 'user-agent': 'Mozilla/5.0 RANDY-SYSTEMS/1.0' }
  })

  if (data?.code !== 0 || !data?.data) {
    throw new Error(data?.msg || 'TikTok fallback no devolvió el video.')
  }

  const mediaUrl = data.data.hdplay || data.data.play || data.data.wmplay
  if (!mediaUrl) throw new Error('TikTok fallback no encontró una fuente reproducible.')

  const video = await downloadHttpBuffer(mediaUrl)
  return {
    video,
    title: safeName(data.data.title || 'TikTok'),
    sourceClean: Boolean(data.data.hdplay || data.data.play)
  }
}

async function sendAudio(ctx, target, label = '') {
  await ctx.react('⏳').catch(() => {})
  const info = await getInfo(target).catch(() => null)
  const source = info?.webpage_url || info?.original_url || target
  const title = safeName(info?.title || label || 'RANDY SYSTEMS Audio')
  const filePath = await downloadToTemp(source, 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best')
  try {
    const audio = await fs.readFile(filePath)
    const ext = path.extname(filePath).toLowerCase()
    const mimetype = ext === '.mp3' ? 'audio/mpeg' : ext === '.ogg' || ext === '.opus' ? 'audio/ogg' : 'audio/mp4'
    await ctx.sock.sendMessage(ctx.jid, {
      audio,
      mimetype,
      fileName: `${title}${ext || '.m4a'}`,
      ptt: false
    }, { quoted: ctx.msg })
    await ctx.react('✅').catch(() => {})
  } finally {
    await fs.rm(filePath, { force: true }).catch(() => {})
  }
}

async function sendVideo(ctx, target, label = '', format = 'best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]/best') {
  await ctx.react('⏳').catch(() => {})
  const info = await getInfo(target).catch(() => null)
  const source = info?.webpage_url || info?.original_url || target
  const title = safeName(info?.title || label || 'RANDY SYSTEMS Video')
  const filePath = await downloadToTemp(source, format)
  try {
    const video = await fs.readFile(filePath)
    await ctx.sock.sendMessage(ctx.jid, {
      video,
      mimetype: 'video/mp4',
      fileName: `${title}.mp4`,
      caption: `🎬 *${title}*\n🤖 RANDY SYSTEMS`
    }, { quoted: ctx.msg })
    await ctx.react('✅').catch(() => {})
  } finally {
    await fs.rm(filePath, { force: true }).catch(() => {})
  }
}

async function play(ctx) {
  if (!ctx.argText) return ctx.reply('🎵 Usa *.play nombre de la canción* o pega un link de YouTube/Spotify.')
  try {
    let target = ctx.argText.trim()
    let label = ''
    if (isSpotifyUrl(target)) {
      const spotify = await spotifySearchText(target)
      label = [spotify.title, spotify.artist].filter(Boolean).join(' - ')
      target = `ytsearch1:${spotify.query}`
    } else if (!looksLikeUrl(target)) {
      target = `ytsearch1:${target}`
    }
    return await sendAudio(ctx, target, label)
  } catch (error) {
    console.error('play/download audio error:', error)
    await ctx.react('❌').catch(() => {})
    return ctx.reply('❌ No pude sacar esa música ahora. Prueba con otro nombre o enlace.')
  }
}

async function youtubeVideo(ctx) {
  if (!ctx.argText) return ctx.reply('🎬 Usa *.ytmp4 nombre/link* o *.youtube.video nombre/link*.')
  try {
    const target = looksLikeUrl(ctx.argText) ? ctx.argText.trim() : `ytsearch1:${ctx.argText.trim()}`
    return await sendVideo(ctx, target)
  } catch (error) {
    console.error('youtube video error:', error)
    await ctx.react('❌').catch(() => {})
    return ctx.reply('❌ No pude descargar ese video ahora. Intenta con otro enlace o nombre.')
  }
}

async function socialVideo(ctx, platform) {
  const url = ctx.args[0]
  if (!url || !looksLikeUrl(url)) return ctx.reply(`📥 Usa *.${platform} link* con un enlace público.`)

  const host = new URL(url).hostname.toLowerCase()
  if (platform === 'tiktok' && !host.includes('tiktok.com')) return ctx.reply('❌ Ese enlace no parece ser de TikTok.')
  if (platform === 'instagram' && !host.includes('instagram.com')) return ctx.reply('❌ Ese enlace no parece ser de Instagram.')

  if (platform === 'tiktok') {
    try {
      return await sendVideo(ctx, url, '', 'play_addr/best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]/best')
    } catch (primaryError) {
      console.error('tiktok primary download error:', primaryError?.message || primaryError)
      try {
        await ctx.react('⏳').catch(() => {})
        const fallback = await tiktokFallback(url)
        await ctx.sock.sendMessage(ctx.jid, {
          video: fallback.video,
          mimetype: 'video/mp4',
          fileName: `${fallback.title}.mp4`,
          caption: `🎬 *${fallback.title}*\n🤖 RANDY SYSTEMS${fallback.sourceClean ? '\n✨ Fuente directa priorizada' : ''}`
        }, { quoted: ctx.msg })
        await ctx.react('✅').catch(() => {})
        return
      } catch (fallbackError) {
        console.error('tiktok fallback error:', fallbackError?.message || fallbackError)
        await ctx.react('❌').catch(() => {})
        return ctx.reply('❌ TikTok rechazó ambas fuentes de descarga. Prueba de nuevo en unos minutos o con otro enlace público.')
      }
    }
  }

  try {
    return await sendVideo(ctx, url)
  } catch (error) {
    console.error(`${platform} download error:`, error)
    await ctx.react('❌').catch(() => {})
    return ctx.reply('❌ No pude sacar ese video. Verifica que sea público y vuelve a intentar.')
  }
}

const mediaHelp = `📥 *DESCARGAS • RANDY SYSTEMS*

🎵 *.play canción* → busca la canción y manda el audio.
🎵 *.play link* → audio desde un enlace compatible.
🟢 *.spotify link* → toma el título/artista de Spotify y busca una fuente de audio compatible.
🎧 *.ytmp3 link* → audio de YouTube.
🎬 *.ytmp4 nombre/link* → video de YouTube.
🎬 *.ytvideo nombre/link* → alias rápido para video de YouTube.
🎵 *.youtube.play nombre/link* → audio de YouTube.
📹 *.youtube.video nombre/link* → video de YouTube.
🎵 *.tiktok link* / *.tt link* → TikTok con doble proveedor y fuente directa priorizada.
📸 *.instagram link* / *.ig link* → video/Reel público de Instagram.

⚠️ Solo enlaces públicos. Máximo aproximado: 45 MB.
Spotify se usa para identificar la canción; el bot no rompe el DRM de Spotify.`

export const downloadCommands = {
  play,
  ytplay: play,
  'youtube.play': play,
  spotify: play,
  sp: play,
  ytmp3: play,
  yta: play,
  ytmp4: youtubeVideo,
  ytvideo: youtubeVideo,
  playvideo: youtubeVideo,
  'youtube.video': youtubeVideo,
  tiktok: async ctx => socialVideo(ctx, 'tiktok'),
  tt: async ctx => socialVideo(ctx, 'tiktok'),
  tiktoknowm: async ctx => socialVideo(ctx, 'tiktok'),
  ttnowm: async ctx => socialVideo(ctx, 'tiktok'),
  instagram: async ctx => socialVideo(ctx, 'instagram'),
  ig: async ctx => socialVideo(ctx, 'instagram'),
  mediahelp: async ctx => ctx.reply(mediaHelp),
  descargas: async ctx => ctx.reply(mediaHelp)
}
