import { createHash, randomBytes } from 'node:crypto'

// WhatsApp clients may keep an earlier favorite with its original metadata.
// A fresh pack ID lets the updated sticker be stored as a separate version.
export function makeStickerPackId(pack, author, { fresh = false } = {}) {
  const version = fresh ? randomBytes(16).toString('hex') : ''
  const digest = createHash('sha256')
    .update(JSON.stringify([String(pack), String(author), version]))
    .digest('hex')
    .slice(0, 32)
  return `randy-${digest}`
}
