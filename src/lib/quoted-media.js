// Preserve the original WhatsApp message key when asking for an expired
// *ordinary* quoted attachment to be re-uploaded.
export function buildQuotedMediaEnvelope(msg, botJid) {
  const contexts = [
    msg?.message?.extendedTextMessage?.contextInfo,
    msg?.message?.imageMessage?.contextInfo,
    msg?.message?.videoMessage?.contextInfo
  ]
  const ctx = contexts.find(item => item?.quotedMessage && item?.stanzaId)
  if (!ctx) return null
  const remoteJid = msg?.key?.remoteJid
  if (!remoteJid) return null
  const participant = ctx.participant || undefined
  const ownIds = [botJid, msg?.key?.participantAlt].filter(Boolean)
  const fromMe = ownIds.some(id => participant && id === participant)
  return {
    key: {
      remoteJid,
      id: ctx.stanzaId,
      ...(participant ? { participant } : {}),
      fromMe
    },
    message: ctx.quotedMessage
  }
}
