import { findGroupParticipant } from './group-identity.js'
import { quotedMessage, quotedParticipant } from './utils.js'

// Reply-based copying is allowed only when the command author also authored
// the source photo. No background archiving or third-party view-once recovery.
export async function isAuthorOfQuotedMessage(sock, participants, msg, sender) {
  const authorJid = quotedParticipant(msg)
  if (!authorJid || !sender || !Array.isArray(participants) || !participants.length) return false
  const [requester, author] = await Promise.all([
    findGroupParticipant(sock, participants, [sender, msg?.key?.participantAlt]),
    findGroupParticipant(sock, participants, [authorJid])
  ])
  return Boolean(requester && author && requester.id === author.id)
}

export function getQuotedImage(msg) {
  let contents = quotedMessage(msg)
  const wrappers = [
    'ephemeralMessage',
    'viewOnceMessage',
    'viewOnceMessageV2',
    'viewOnceMessageV2Extension',
    'documentWithCaptionMessage'
  ]
  for (let n = 0; n < 6 && contents; n++) {
    if (contents.imageMessage) return contents.imageMessage
    const wrapper = wrappers.find(key => contents[key]?.message)
    if (!wrapper) return null
    contents = contents[wrapper].message
  }
  return null
}
