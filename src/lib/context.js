import { downloadContentFromMessage, getContentType } from '@whiskeysockets/baileys'
import { config } from '../config.js'
import { jidToNumber, quotedMessage, quotedParticipant } from './utils.js'

export async function buildContext(sock, msg, parsed) {
  const jid = msg.key.remoteJid
  const isGroup = jid?.endsWith('@g.us')
  const sender = msg.key.participant || msg.key.remoteJid
  const senderNumber = jidToNumber(sender)
  let groupMetadata = null
  let participants = []
  let isAdmin = false
  let isBotAdmin = false

  if (isGroup) {
    groupMetadata = await sock.groupMetadata(jid).catch(() => null)
    participants = groupMetadata?.participants || []
    const me = sock.user?.id
    const senderP = participants.find(p => p.id === sender)
    const botP = participants.find(p => p.id === me || jidToNumber(p.id) === jidToNumber(me))
    isAdmin = Boolean(senderP?.admin)
    isBotAdmin = Boolean(botP?.admin)
  }

  const isOwner = config.ownerNumber && senderNumber === config.ownerNumber
  const reply = async text => sock.sendMessage(jid, { text }, { quoted: msg })
  const react = async emoji => sock.sendMessage(jid, { react: { text: emoji, key: msg.key } })

  const getTargetJid = () => {
    const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid?.[0]
    return mentioned || quotedParticipant(msg) || (parsed.args?.[0]?.replace(/\D/g, '') ? `${parsed.args[0].replace(/\D/g, '')}@s.whatsapp.net` : null)
  }

  const downloadQuotedOrCurrent = async () => {
    const q = quotedMessage(msg)
    const container = q || msg.message
    const type = getContentType(container)
    const content = container?.[type]
    if (!type || !content) throw new Error('No se encontró multimedia.')
    const mediaType = type.replace('Message', '')
    const stream = await downloadContentFromMessage(content, mediaType)
    const chunks = []
    for await (const chunk of stream) chunks.push(chunk)
    return { buffer: Buffer.concat(chunks), type, content }
  }

  return { sock, msg, jid, sender, senderNumber, isGroup, groupMetadata, participants, isAdmin, isBotAdmin, isOwner, reply, react, getTargetJid, downloadQuotedOrCurrent, ...parsed }
}
