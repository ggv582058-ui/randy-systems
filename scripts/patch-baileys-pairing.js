import fs from 'node:fs'
import path from 'node:path'

const target = path.resolve('node_modules/@whiskeysockets/baileys/lib/Socket/messages-recv.js')

if (!fs.existsSync(target)) {
  console.warn('[pairing-patch] Baileys messages-recv.js not found; skipping')
  process.exit(0)
}

let source = fs.readFileSync(target, 'utf8')

if (source.includes('[RANDY_PAIRING_GUARD]')) {
  console.log('[pairing-patch] already applied')
  process.exit(0)
}

const pattern = /const primaryIdentityPublicKey = toRequiredBuffer\(\s*getBinaryNodeChildBuffer\(linkCodeCompanionReg, ['"]primary_identity_pub['"]\)\s*\);?/

if (!pattern.test(source)) {
  console.warn('[pairing-patch] target pattern not found; leaving Baileys unchanged')
  process.exit(0)
}

source = source.replace(
  pattern,
  `/* [RANDY_PAIRING_GUARD] WhatsApp can send an empty link_code_companion_reg notification before the real pairing payload. */\n                const primaryIdentityBuffer = getBinaryNodeChildBuffer(linkCodeCompanionReg, 'primary_identity_pub');\n                if (!primaryIdentityBuffer) {\n                    logger.debug({ node }, 'ignoring empty link_code_companion_reg notification');\n                    break;\n                }\n                const primaryIdentityPublicKey = toRequiredBuffer(primaryIdentityBuffer);`
)

fs.writeFileSync(target, source)
console.log('[pairing-patch] applied successfully')
