import { test } from 'node:test'
import assert from 'node:assert/strict'
import { findGroupParticipant, matchGroupParticipant, normalizeWhatsAppJid } from '../src/lib/group-identity.js'

const pn = '5215551002000@s.whatsapp.net'
const lid = '987654321@lid'
const other = '111222333@lid'

test('normalizes device JIDs without losing the address type', () => {
  assert.equal(normalizeWhatsAppJid('5215551002000:4@s.whatsapp.net'), pn)
  assert.equal(normalizeWhatsAppJid(other), other)
  assert.equal(normalizeWhatsAppJid(undefined), '')
})

test('detects admin by matching the bot LID against participant ID', async () => {
  const members = [{ id: lid, admin: 'admin' }]
  assert.equal((await findGroupParticipant({ user: { id: pn, lid } }, members, [pn, lid]))?.admin, 'admin')
})

test('detects admin through participant phoneNumber even without bot LID', async () => {
  const members = [{ id: lid, phoneNumber: pn, admin: 'superadmin' }]
  assert.equal((await findGroupParticipant({}, members, [pn]))?.admin, 'superadmin')
})

test('detects admin with saved PN to LID mapping', async () => {
  const sock = { signalRepository: { lidMapping: { getLIDForPN: async x => x === pn ? lid : null } } }
  assert.equal((await findGroupParticipant(sock, [{ id: lid, admin: 'admin' }], [pn]))?.admin, 'admin')
})

test('identifies sender from alternate participant id', async () => {
  const p = await findGroupParticipant({}, [{ id: lid, admin: 'admin' }], [pn, lid])
  assert.equal(p?.id, lid)
})

test('does not give permissions to a different member', async () => {
  const p = await findGroupParticipant({}, [{ id: other, admin: 'admin' }], [pn])
  assert.equal(p, undefined)
})

test('resolves target by matching phoneNumber in group metadata', () => {
  const p = matchGroupParticipant([{ id: lid, phoneNumber: pn }], [pn])
  assert.equal(p?.id, lid)
})
