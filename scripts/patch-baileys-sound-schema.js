import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'
import assert from 'node:assert/strict'

const dir = path.resolve('node_modules/@whiskeysockets/baileys/WAProto')
const schema = path.join(dir,'WAProto.proto')
const index = path.join(dir,'index.js')
const temp = path.join(dir,'rs-sound-schema.proto')
const generated = path.join(dir,'rs-sound-schema.mjs')
const original = fs.readFileSync(schema,'utf8')
function addField(input, anchor, field) {
  if (input.includes(field)) return input
  if (input.split(anchor).length!==2) throw Error('Unexpected pinned WAProto schema: '+anchor)
  return input.replace(anchor,anchor+'\n'+field)
}
let patched = addField(original,'    optional FutureProofMessage lottieStickerMessage = 74;','    optional FutureProofMessage audioStickerMessage = 134;')
patched = addField(patched,'    message StickerMessage {','        optional AudioMessage audioMessage = 26;')
try {
  fs.writeFileSync(temp,patched)
  const p=spawnSync('npm',['exec','--yes','--package=protobufjs-cli@1.1.3','--','pbjs','-t','static-module','--no-beautify','-w','es6','--no-bundle','--no-delimited','--no-verify','--no-comments','-o',generated,temp],{stdio:'inherit',timeout:180000})
  if(p.status!==0) throw p.error || Error('WAProto generation failed: '+p.status)
  const js=fs.readFileSync(generated,'utf8').replace(/import \* as (\$protobuf) from/g,'import $1 from').replace(/(['"])protobufjs\/minimal(['"])/g,'$1protobufjs/minimal.js$2')
  fs.writeFileSync(generated,js)
  const {proto}=await import(pathToFileURL(generated).href)
  const audio={mediaKey:Buffer.alloc(32,7),fileEncSha256:Buffer.alloc(32,8),fileSha256:Buffer.alloc(32,9),directPath:'/synthetic-test',seconds:7,mimetype:'audio/ogg; codecs=opus'}
  const sticker={isAnimated:true,audioMessage:audio}
  const wrapper={audioStickerMessage:{message:{stickerMessage:sticker}}}
  const check=a=>{assert.equal(a.seconds,7);assert.equal(a.directPath,audio.directPath);assert.equal(a.mimetype,audio.mimetype);assert.deepEqual(Buffer.from(a.mediaKey),audio.mediaKey);assert.deepEqual(Buffer.from(a.fileEncSha256),audio.fileEncSha256)}
  const round=m=>proto.Message.decode(proto.Message.encode(proto.Message.fromObject(m)).finish())
  check(round(wrapper).audioStickerMessage.message.stickerMessage.audioMessage)
  check(round({stickerMessage:sticker}).stickerMessage.audioMessage)
  check(round({extendedTextMessage:{text:'.ske Randy',contextInfo:{quotedMessage:wrapper}}}).extendedTextMessage.contextInfo.quotedMessage.audioStickerMessage.message.stickerMessage.audioMessage)
  const obj=proto.Message.toObject(round(wrapper),{bytes:String,longs:String})
  check(round(obj).audioStickerMessage.message.stickerMessage.audioMessage)
  assert.equal(round({stickerMessage:{isAnimated:true}}).stickerMessage.audioMessage,null)
  assert.equal(round({conversation:'ping'}).conversation,'ping')
  fs.writeFileSync(index,js)
  fs.writeFileSync(schema,patched)
  console.log('[RS native schema] 6 regression checks passed: wire, flat, quote, object, normal sticker, text')
} finally {
  fs.rmSync(temp,{force:true})
  fs.rmSync(generated,{force:true})
}
