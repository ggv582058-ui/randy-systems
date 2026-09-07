import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
import axios from 'axios'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const ytdlp = require('youtube-dl-exec')

const MAX_MEDIA_BYTES = 45 * 1024 * 1024
const DOWNLOAD_TIMEOUT_MS = 150000

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
    socketTimeout: 20,
    retries: 2,
    extractorRetries: 2
  }, { timeout: 45000 })
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
    socketTimeout: 20,
    retries: 3,
    fragmentRetries: 3,
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

async function sendAudio(ctx, target, label = '') {
  await ctx.react('⏳')
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
    await ctx.react('✅')
  } finally {
    await fs.rm(filePath, { force: true }).catch(() => {})
  }
}

async function sendVideo(ctx, target, label = '', format = 'best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]/best') {
  await ctx.react('⏳')
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
    await ctx.react('✅')
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
    return ctx.reply(`❌ No pude sacar esa música ahora. ${error?.message || 'Intenta con otro enlace o nombre.'}`)
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
    return ctx.reply(`❌ No pude descargar ese video. ${error?.message || 'Intenta con otro enlace.'}`)
  }
}

async function socialVideo(ctx, platform) {
  const url = ctx.args[0]
  if (!url || !looksLikeUrl(url)) return ctx.reply(`📥 Usa *.${platform} link* con un enlace público.`)
  try {
    const host = new URL(url).hostname.toLowerCase()
    if (platform === 'tiktok' && !host.includes('tiktok.com')) return ctx.reply('❌ Ese enlace no parece ser de TikTok.')
    if (platform === 'instagram' && !host.includes('instagram.com')) return ctx.reply('❌ Ese enlace no parece ser de Instagram.')

    // yt-dlp exposes TikTok's play_addr as the direct video and marks download_addr
    // as watermarked when TikTok reports that flag. Prefer play_addr first.
    const format = platform === 'tiktok'
      ? 'play_addr/best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]/best'
      : 'best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]/best'

    return await sendVideo(ctx, url, '', format)
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
🎵 *.tiktok link* / *.tt link* → video de TikTok, priorizando la versión directa sin watermark cuando TikTok la ofrece.
📸 *.instagram link* / *.ig link* → video/Reel público de Instagram.

⚠️ Solo enlaces públicos. WhatsApp limita el tamaño de archivos; el bot usa un máximo de 45 MB.
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
