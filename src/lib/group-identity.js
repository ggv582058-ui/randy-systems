// WhatsApp participants can use a phone-number JID, a privacy LID, or both.
export function normalizeWhatsAppJid(value) {
  if (typeof value !== 'string') return ''
  const at = value.indexOf('@')
  if (at <= 0) return ''
  return `${value.slice(0, at).split(':')[0]}${value.slice(at).toLowerCase()}`
}

const participantJids = participant => [
  participant?.id,
  participant?.phoneNumber,
  participant?.lid
].map(normalizeWhatsAppJid).filter(Boolean)

export function matchGroupParticipant(participants, candidateJids) {
  const candidates = new Set(candidateJids.map(normalizeWhatsAppJid).filter(Boolean))
  if (!candidates.size) return undefined
  return participants.find(participant => participantJids(participant).some(id => candidates.has(id)))
}

export async function findGroupParticipant(sock, participants, candidateJids) {
  const candidates = new Set(candidateJids.map(normalizeWhatsAppJid).filter(Boolean))
  const mapping = sock?.signalRepository?.lidMapping

  // Some Baileys sessions have the LID only in metadata, not on sock.user.
  // Use a stored PN/LID mapping when available. Never guess one from digits.
  if (mapping) {
    for (const jid of [...candidates]) {
      try {
        const mapped = jid.endsWith('@lid')
          ? await mapping.getPNForLID?.(jid)
          : jid.endsWith('@s.whatsapp.net')
            ? await mapping.getLIDForPN?.(jid)
            : null
        const normalized = normalizeWhatsAppJid(mapped)
        if (normalized) candidates.add(normalized)
      } catch {
        // Mapping may be absent. Direct IDs and metadata alternatives still work.
      }
    }
  }

  return matchGroupParticipant(participants, [...candidates])
}
