import { test } from 'node:test'
import assert from 'node:assert/strict'
import { makeStickerPackId } from '../src/lib/sticker-identity.js'

test('ordinary metadata keeps a stable pack ID', () => {
  const first = makeStickerPackId('randy', '')
  const second = makeStickerPackId('randy', '')
  assert.equal(first, second)
  assert.match(first, /^randy-[a-f0-9]{32}$/)
})

test('renamed sticker copies receive new pack IDs even with the same visible name', () => {
  const first = makeStickerPackId('randy', '', { fresh: true })
  const second = makeStickerPackId('randy', '', { fresh: true })
  assert.notEqual(first, second)
})

test('fresh metadata is not confused with the previously saved copy', () => {
  const older = makeStickerPackId('randy matando a pija a Albert', '')
  const newer = makeStickerPackId('randy', '', { fresh: true })
  assert.notEqual(older, newer)
})
