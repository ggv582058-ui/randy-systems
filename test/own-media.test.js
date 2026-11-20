import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getQuotedImage, isAuthorOfQuotedMessage } from '../src/lib/own-media.js'

const me = '12345@lid'
const other = '67890@lid'
const groupMembers = [
  { id: me, phoneNumber: '15550001111@s.whatsapp.net', admin: 'admin' },
  { id: other, phoneNumber: '15550002222@s.whatsapp.net', admin: null }
]
function reply(participant, quotedMessage = { imageMessage: { mimetype: 'image/jpeg' } }) {
  return {
    key: { remoteJid: '123@g.us' },
    message: { extendedTextMessage: { contextInfo: { participant, quotedMessage } } }
  }
}

test('author can request own quoted photo', async () => {
  assert.equal(await isAuthorOfQuotedMessage({}, groupMembers, reply(me), me), true)
})

test('cross PN/LID variants identify the same author', async () => {
  assert.equal(await isAuthorOfQuotedMessage({}, groupMembers, reply(me), '15550001111@s.whatsapp.net'), true)
})

test('other users cannot request someone else photo', async () => {
  assert.equal(await isAuthorOfQuotedMessage({}, groupMembers, reply(me), other), false)
})

test('missing quote author is rejected', async () => {
  assert.equal(await isAuthorOfQuotedMessage({}, groupMembers, { message: {} }, me), false)
})

test('normal photo can be extracted from quote', () => {
  assert.equal(getQuotedImage(reply(me))?.mimetype, 'image/jpeg')
})

test('nested view-once photo can be extracted only if still present', () => {
  const nested = { viewOnceMessageV2: { message: { imageMessage: { mimetype: 'image/jpeg' } } } }
  assert.equal(getQuotedImage(reply(me, nested))?.mimetype, 'image/jpeg')
})

test('a withdrawn view-once placeholder is not recoverable from quote', () => {
  assert.equal(getQuotedImage(reply(me, { conversation: 'Photo' })), null)
})
