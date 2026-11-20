import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildQuotedMediaEnvelope } from '../src/lib/quoted-media.js'

const group = '111@g.us'
const author = '123456@lid'
const quoted = {
  key: { remoteJid: group, participant: '22222@lid' },
  message: {
    extendedTextMessage: {
      text: '.ske albert',
      contextInfo: {
        stanzaId: 'ABCDEF',
        participant: author,
        quotedMessage: { stickerMessage: { mimetype: 'image/webp' } }
      }
    }
  }
}

test('constructs quoted sticker original key for download retry', () => {
  const src = buildQuotedMediaEnvelope(quoted, ['22222@lid'])
  assert.equal(src.key.remoteJid, group)
  assert.equal(src.key.id, 'ABCDEF')
  assert.equal(src.key.participant, author)
  assert.equal(src.key.fromMe, false)
  assert.equal(src.message.stickerMessage.mimetype, 'image/webp')
})

test('identifies the bot as original author without using the requesting sender', () => {
  const src = buildQuotedMediaEnvelope(quoted, [author])
  assert.equal(src.key.fromMe, true)
})

test('does not attempt to reupload if WhatsApp omitted the original stanza ID', () => {
  const source = structuredClone(quoted)
  delete source.message.extendedTextMessage.contextInfo.stanzaId
  assert.equal(buildQuotedMediaEnvelope(source, [author]), null)
})

test('never retrieves original media from a plain text reply without quoted payload', () => {
  const source = structuredClone(quoted)
  source.message.extendedTextMessage.contextInfo.quotedMessage = { conversation: '.ver' }
  const env = buildQuotedMediaEnvelope(source, [])
  assert.equal(env.message.conversation, '.ver')
  assert.equal(env.message.stickerMessage, undefined)
})
