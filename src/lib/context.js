import { downloadContentFromMessage, downloadMediaMessage, getContentType } from '@whiskeysockets/baileys'
import pino from 'pino'
import { config } from '../config.js'
import { jidToNumber, quotedMessage, quotedParticipant } from './utils.js'
import { findGroupParticipant, matchGroupParticipant } from './group-identity.js'
import { buildQuotedMediaEnvelope } from './quoted-media.js'

const GROUP_METADATA_COMMANDS = new Set([
  'menu',
  'admins', 'tagall', 'hidetag', 'kick', 'add', 'promote', 'demote',
  'link', 'revoke', 'subject', 'desc', 'open', 'close', 'groupinfo', 'ver'
])

// Role-changing commands must fetch fresh permissions, not a cached admin list.
const GROUP_ADMIN_ACTIONS = new Set([
  'kick', 'add', 'promote', 'demote', 'link', 'revoke',
  'subject', 'desc', 'open', 'close'
])

const GROUP_METADATA_TTL_MS = 30_000
const groupMetadataCache = new Map()

async function getGroupMetadata(sock, jid, forceRefresh = false) {
  const cached = groupMetadataCache.get(jid)
  const now = Date.now()
  if (!forceRefresh && cached && now - cached.at < GROUP_METADATA_TTL_MS) return cached.value

  const value = await sock.groupMetadata(jid).catch(() => null)
  if (value) groupMetadataCache.set(jid, { at: now, value })
  return value
}

export async function buildContext(sock, msg, parsed) {
  const jid = msg.key.remoteJid
  const isGroup = jid?.endsWith('@g.us')
  const sender = msg.key.fromMe ? (msg.key.participant || sock.user?.id || msg.key.remoteJid) : (msg.key.participant || msg.key.remoteJid)
  const senderNumber = jidToNumber(sender)
  let groupMetadata = null
  let participants = []
  let isAdmin = false
  let isBotAdmin = false

  // Most commands (stickers, downloads, IA, tools, etc.) do not need a
  // WhatsApp group-metadata network request. Skipping it makes them react
  // immediately instead of waiting on an extra round trip to WhatsApp.
  if (isGroup && GROUP_METADATA_COMMANDS.has(parsed.command)) {
    groupMetadata = await getGroupMetadata(sock, jid, (GROUP_ADMIN_ACTIONS.has(parsed.command) || parsed.command === 'ver'))
    participants = groupMetadata?.participants || []
    const senderP = await findGroupParticipant(sock, participants, [sender, msg.key.participantAlt])
    const botP = await findGroupParticipant(sock, participants, [sock.user?.id, sock.user?.lid])
    isAdmin = Boolean(senderP?.admin)
    isBotAdmin = Boolean(botP?.admin)
  }

  const isOwner = config.ownerNumber && senderNumber === config.ownerNumber
  const reply = async text => sock.sendMessage(jid, { text }, { quoted: msg })
  const react = async emoji => sock.sendMessage(jid, { react: { text: emoji, key: msg.key } })

  const getTargetJid = () => {
    const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid?.[0]
    const target = mentioned || quotedParticipant(msg) || (parsed.args?.[0]?.replace(/\D/g, '') ? `${parsed.args[0].replace(/\D/g, '')}@s.whatsapp.net` : null)
    return matchGroupParticipant(participants, [target])?.id || target
  }

  const downloadQuotedOrCurrent = async () => {
    const q = quotedMessage(msg)
    const raw = q || msg.message
    const container = raw?.audioStickerMessage?.message?.stickerMessage ? raw.audioStickerMessage.message : raw
    const type = getContentType(container)
    const content = container?.[type]
    if (!type || !content) throw new Error('No se encontró multimedia.')
    const mediaType = type.replace('Message', '')
    try {
      const stream = await downloadContentFromMessage(content, mediaType)
      const chunks = []
      let total = 0
      for await (const chunk of stream) {
        total += chunk.length
        if (total > 16 * 1024 * 1024) throw new Error('media too large')
        chunks.push(chunk)
      }
      if (!total) throw new Error('empty media')
      return { buffer: Buffer.concat(chunks), type, content }
    } catch (error) {
      // Re-upload is supported for ordinary quoted media when the original key
      // is available. No view-once bypass or persistent media archive.
      if (!q || !['stickerMessage', 'imageMessage', 'videoMessage'].includes(type) || typeof sock.updateMediaMessage !== 'function') throw error
      const original = buildQuotedMediaEnvelope(msg, [sock.user?.id, sock.user?.lid])
      if (!original) throw error
      const buffer = await downloadMediaMessage(
        original,
        'buffer',
        {},
        { logger: pino({ level: 'silent' }), reuploadRequest: sock.updateMediaMessage.bind(sock) }
      )
      if (!buffer?.length || buffer.length > 16 * 1024 * 1024) throw new Error('media unavailable or too large')
      return { buffer, type, content }
    }
  }

  return { sock, msg, jid, sender, senderNumber, isGroup, groupMetadata, participants, isAdmin, isBotAdmin, isOwner, reply, react, getTargetJid, downloadQuotedOrCurrent, ...parsed }
}
