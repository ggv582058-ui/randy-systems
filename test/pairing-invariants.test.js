import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'

test('pairing endpoint never deletes or ends the existing primary connection', async () => {
  const source = await fs.readFile(new URL('../src/index.js', import.meta.url), 'utf8')
  const pairing = source.split("app.post('/api/pair'")[1].split("const healthServer =")[0]
  assert.ok(pairing.includes('extraAccounts.pair(phone)'))
  assert.ok(!pairing.includes('clearUnlinkedSession'))
  assert.ok(!pairing.includes('oldSock.end'))
  assert.ok(!pairing.includes('currentSock = null'))
  assert.ok(!pairing.includes('fs.rm('))
})

test('each secondary account has its own auth and session backup store', async () => {
  const source = await fs.readFile(new URL('../src/lib/multi-session.js', import.meta.url), 'utf8')
  assert.ok(source.includes('useMultiFileAuthState(account.directory)'))
  assert.ok(source.includes('key: backupKey'))
  assert.ok(source.includes('registry.sAdd(registryKey, number)'))
})

test('production launcher does not apply the old pairing patch', async () => {
  const launcher = await fs.readFile(new URL('../scripts/start-production.sh', import.meta.url), 'utf8')
  assert.ok(!launcher.includes('node scripts/patch-app-pairing.js'))
})

test('account pairing requires a private token', async () => {
  const source = await fs.readFile(new URL('../src/index.js', import.meta.url), 'utf8')
  assert.ok(source.includes("if (!config.setupToken) return res.status(503)"))
  assert.ok(source.includes("if (!setupAuthorized(req)) return res.status(401)"))
})
