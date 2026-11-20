import { test } from 'node:test'
import assert from 'node:assert/strict'
import path from 'node:path'
import {
  accountPaths,
  normalizeAccountNumber,
  maskedAccount,
  isMatchingAccountJid
} from '../src/lib/multi-session-paths.js'

test('each phone uses a different credential folder and Redis backup key', () => {
  const a = accountPaths('/tmp/randy-session', 'randy:whatsapp:session', '15551234567')
  const b = accountPaths('/tmp/randy-session', 'randy:whatsapp:session', '521234567890')
  assert.notEqual(a.directory, b.directory)
  assert.notEqual(a.backupKey, b.backupKey)
  assert.notEqual(a.directory, '/tmp/randy-session')
  assert.notEqual(a.backupKey, 'randy:whatsapp:session')
  assert.equal(a.directory, path.join('/tmp/randy-session-accounts', '15551234567'))
})

test('input normalization does not allow directory traversal', () => {
  assert.throws(() => normalizeAccountNumber('..'), TypeError)
  assert.throws(() => normalizeAccountNumber(''), TypeError)
  assert.throws(() => normalizeAccountNumber('1'), TypeError)
  assert.equal(normalizeAccountNumber('+1 (555) 123-4567'), '15551234567')
})

test('primary number comparison recognizes WhatsApp multi-device suffix', () => {
  assert.equal(isMatchingAccountJid('15551234567:2@s.whatsapp.net', '15551234567'), true)
  assert.equal(isMatchingAccountJid('15551234567@s.whatsapp.net', '521234567890'), false)
})

test('status exposes masked phone, not the whole number', () => {
  const masked = maskedAccount('15551234567')
  assert.ok(masked.endsWith('4567'))
  assert.equal(masked.includes('123'), false)
})
