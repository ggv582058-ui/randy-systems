import axios from 'axios'
import sharp from 'sharp'
import ffmpegPath from 'ffmpeg-static'
import { spawn } from 'node:child_process'
import { mkdtemp, writeFile, readFile, rm, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { jidToNumber } from '../lib/utils.js'

const actions = {
  kiss: ['kiss','le mandó un beso a','💙'], hug: ['hug','abrazó a','🫂'],
  pat: ['pat','acarició a','✨'], slap: ['slap','le dio una bofetada de broma a','💫'],
  highfive: ['highfive','chocó los cinco con','🙌'], poke: ['poke','le dio un toque a','👉'],
  dance: ['dance','está bailando con','🎶'], wave: ['wave','saludó a','👋'],
  smile: ['smile','le sonrió a','😊'], wink: ['wink','le guiñó un ojo a','😉'],
  cuddle: ['cuddle','se acurrucó con','🫶'], blush: ['blush','se sonrojó frente a','🌸'],
  cry: ['cry','está llorando junto a','🥺'], happy: ['happy','celebra con','🎉'],
  bonk: ['bonk','le dio un golpecito de caricatura a','⭐'], handhold: ['handhold','tomó de la mano a','🤝']
}
const http = { timeout: 8000, maxRedirects: 0, headers: { 'User-Agent': 'RandySystems/2.0 (+https://github.com/ggv582058-ui/randy-systems)' } }
let mediaBusy = false
async function convertGif(buffer) {
  const dir = await mkdtemp(join(tmpdir(), 'rs-gif-'))
  try {
    const input = join(dir, 'in.gif'), output = join(dir, 'out.mp4')
    await writeFile(input, buffer)
    await new Promise((resolve, reject) => {
      const child = spawn(ffmpegPath, ['-nostdin','-y','-threads','1','-i',input,'-t','6','-filter_threads','1','-vf','fps=15,scale=384:384:force_original_aspect_ratio=decrease:force_divisible_by=2','-an','-c:v','libx264','-threads','1','-preset','ultrafast','-crf','28','-pix_fmt','yuv420p','-movflags','+faststart',output], {stdio:'ignore'})
      const timer = setTimeout(() => child.kill('SIGKILL'), 12000)
      child.once('error', e => { clearTimeout(timer); reject(e) })
      child.once('close', code => { clearTimeout(timer); code === 0 ? resolve() : reject(new Error('gif conversion failed')) })
    })
    const size = (await stat(output)).size
    if (!size || size > 4 * 1024 * 1024) throw new Error('gif size')
    return await readFile(output)
  } finally { await rm(dir, {recursive:true,force:true}).catch(()=>{}) }
}


// Original RS reaction artwork, independent of external GIF providers.
const localLabels = {kiss:'BESO',hug:'ABRAZO',pat:'CARICIA',slap:'BROMA',highfive:'CHOCA LOS CINCO',poke:'TOQUE',dance:'BAILE',wave:'SALUDO',smile:'SONRISA',wink:'GUIÑO',cuddle:'CARIÑO',blush:'TIMIDEZ',cry:'CONSUELO',happy:'CELEBRACIÓN',bonk:'BROMA',handhold:'DE LA MANO'}
function localFrame(action,i) {
  const t = i * Math.PI / 12
  const close = ['kiss','hug','cuddle','handhold'].includes(action)
  const shift = close ? 13 + 12 * Math.sin(t/2)**2 : 3*Math.sin(t)
  const jump = ['dance','happy','highfive'].includes(action) ? 8*Math.sin(t*2) : 2*Math.sin(t)
  const a = 91+shift, b = 229-shift
  function face(x,y,hair,flip) {
    const eye = action==='kiss' || action==='wink' ? '<path d="M-22 -4 q8 -7 16 0 M6 -4 q8 -7 16 0" stroke="#20304a" stroke-width="3" fill="none" stroke-linecap="round"/>' : '<ellipse cx="-14" cy="-5" rx="4" ry="7" fill="#20304a"/><ellipse cx="14" cy="-5" rx="4" ry="7" fill="#20304a"/>'
    return '<g transform="translate('+x+' '+y+')"><path d="M-42 65 Q-41 24 0 23 Q41 24 42 65" fill="'+hair+'" stroke="#c2d8ff" stroke-width="2"/><circle r="43" fill="'+hair+'"/><ellipse cy="7" rx="34" ry="35" fill="#ffe1cf"/><path d="M-34 -8 Q-39 -45 0 -42 Q39 -42 36 -7 Q20 -19 8 -27 Q-2 -8 -13 -17 Q-22 -7 -34 -8" fill="'+hair+'"/>'+eye+'<ellipse cx="-23" cy="12" rx="7" ry="4" fill="#ef9bad"/><ellipse cx="23" cy="12" rx="7" ry="4" fill="#ef9bad"/><path d="M-6 14 Q0 20 6 14" fill="none" stroke="#9d5364" stroke-width="2" stroke-linecap="round"/></g>'
  }
  const pulse=1+0.18*Math.sin(t*2)
  return '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320" viewBox="0 0 320 320"><defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#081225"/><stop offset="1" stop-color="#163e75"/></linearGradient></defs><rect width="320" height="320" rx="20" fill="url(#bg)"/><rect x="9" y="9" width="302" height="302" rx="18" fill="none" stroke="#5c98e8" stroke-opacity=".55"/><text x="160" y="32" text-anchor="middle" fill="#cbe1ff" font-family="sans-serif" font-size="13" font-weight="bold">RS ANIME EXPERIENCE</text><circle cx="160" cy="153" r="112" fill="#7cb6ff" fill-opacity=".08"/>'+face(a,155+jump,'#76a9ff',false)+face(b,155-jump,'#eaa1c9',true)+'<g transform="translate(160 '+(82-6*Math.sin(t))+') scale('+pulse+')"><path d="M0 21 C-8 10 -26 1 -23 -11 C-20 -24 -5 -24 0 -13 C5 -24 20 -24 23 -11 C26 1 8 10 0 21" fill="'+(close?'#ff91bd':'#79b9ff')+'"/></g><text x="160" y="253" text-anchor="middle" fill="#edf6ff" font-size="18" font-family="sans-serif" font-weight="bold">'+localLabels[action]+'</text><text x="160" y="281" text-anchor="middle" fill="#8db9ef" font-size="12" font-family="sans-serif">RANDY SYSTEMS</text></svg>'
}
async function localReaction(action) {
  const dir = await mkdtemp(join(tmpdir(),'rs-reaction-'))
  try {
    for(let i=0;i<24;i++) {
      const frame=join(dir,'frame-'+String(i).padStart(3,'0')+'.png')
      await sharp(Buffer.from(localFrame(action,i))).png().toFile(frame)
    }
    const output=join(dir,'out.mp4')
    await new Promise((resolve,reject)=>{
      const child=spawn(ffmpegPath,['-nostdin','-y','-threads','1','-framerate','12','-i',join(dir,'frame-%03d.png'),'-an','-c:v','libx264','-threads','1','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart',output],{stdio:'ignore'})
      const timer=setTimeout(()=>child.kill('SIGKILL'),12000)
      child.once('error',e=>{clearTimeout(timer);reject(e)})
      child.once('close',code=>{clearTimeout(timer);code===0?resolve():reject(new Error('local ffmpeg '+code))})
    })
    const size=(await stat(output)).size
    if(!size||size>4*1024*1024)throw new Error('local video size')
    return await readFile(output)
  } finally {await rm(dir,{recursive:true,force:true}).catch(()=>{})}
}
async function remoteReaction(category) {
  const response = await axios.get('https://api.waifu.pics/sfw/' + category, {...http,timeout:4500,maxContentLength:16000})
  const url = new URL(response.data.url)
  if (url.protocol !== 'https:' || url.hostname !== 'i.waifu.pics' || url.username || url.password || url.port) throw new Error('unexpected asset host')
  const asset = await axios.get(url.href, {...http,timeout:4500,responseType:'arraybuffer',maxContentLength:4*1024*1024})
  const bytes = Buffer.from(asset.data)
  if (bytes.length > 4*1024*1024 || !/^GIF8[79]a$/.test(bytes.subarray(0,6).toString())) throw new Error('invalid gif content')
  return convertGif(bytes)
}

async function anime(ctx, action) {
  const [category, phrase, icon] = actions[action]
  const target = ctx.getTargetJid()
  if (!target || target === ctx.sender) return ctx.reply('💎 Etiqueta a otra persona o responde a su mensaje con .' + action)
  if (!/^\d+(?::\d+)?@(lid|s\.whatsapp\.net)$/.test(target)) return ctx.reply('❌ Mención inválida.')
  if (mediaBusy) return ctx.reply('⏳ Otra animación está en proceso. Intenta en unos segundos.')
  const text = icon + ' *RS ANIME EXPERIENCE*\n\n@' + jidToNumber(ctx.sender) + ' ' + phrase + ' @' + jidToNumber(target) + '\n\n✦ RANDY SYSTEMS'
  const mentions = [...new Set([ctx.sender,target])]
  mediaBusy = true
  try {
    let video
    try { video = await remoteReaction(category) }
    catch (error) {
      console.warn('RS anime external fallback:', category, error?.response?.status || error?.code || String(error?.message||'unknown').slice(0,100))
      video = await localReaction(action)
    }
    try {
      return await ctx.sock.sendMessage(ctx.jid,{video,gifPlayback:true,mimetype:'video/mp4',caption:text,mentions},{quoted:ctx.msg})
    } catch (error) {
      console.warn('RS anime GIF upload failed:', category, error?.code || String(error?.message||'unknown').slice(0,100))
      return await ctx.sock.sendMessage(ctx.jid,{video,mimetype:'video/mp4',caption:text,mentions},{quoted:ctx.msg})
    }
  } catch (error) {
    console.error('RS anime delivery failed:', category, error?.code || String(error?.message||'unknown').slice(0,100))
    return await ctx.sock.sendMessage(ctx.jid,{text:text+'\n⚠️ WhatsApp no pudo enviar la animación.',mentions},{quoted:ctx.msg})
  } finally { mediaBusy = false }
}

const games = new Map()
const words = ['sistema','planeta','cristal','codigo','galaxia','robot','diamante','musica','estrella','teclado']
const quiz = [
  ['¿Cuál es el planeta rojo?','marte'],['¿Cuántos lados tiene un hexágono?','6'],
  ['¿Cuál es la capital de Japón?','tokio'],['¿Qué lenguaje se usa normalmente para dar estilo a una web?','css'],
  ['¿Cuál es el océano más grande?','pacifico'],['¿Cuánto es 9 × 7?','63']
]
const normalize = s => String(s||'').trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'')
const key = (ctx,game) => JSON.stringify([ctx.sock.user?.id,ctx.jid,ctx.sender,game])
function getGame(k) { const g = games.get(k); if (!g || g.expires <= Date.now()) {games.delete(k);return null} return g }
function setGame(k,g) { if(games.size>=200 && !games.has(k)) games.delete(games.keys().next().value);games.set(k,{...g,expires:Date.now()+10*60*1000}) }
const board = g => [...g.word].map(c=>g.guesses.includes(c)?c:'_').join(' ')
async function hangman(ctx) {
  const k=key(ctx,'hangman'), arg=normalize(ctx.argText)
  let g=getGame(k)
  if (!arg || arg==='nuevo') {
    if (g && !arg) return ctx.reply('🎮 *RS AHORCADO*\n'+board(g)+'\nIntentos restantes: '+g.left+'\n.ahorcado letra')
    g={word:words[Math.floor(Math.random()*words.length)],guesses:[],left:6}
    setGame(k,g)
    return ctx.reply('🎮 *RS AHORCADO*\n'+board(g)+'\n6 intentos. Usa .ahorcado letra')
  }
  if (!g) return ctx.reply('Inicia con .ahorcado')
  if (arg==='salir') {games.delete(k);return ctx.reply('Juego cerrado.')}
  if (!/^[a-z]$/.test(arg)) return ctx.reply('Escribe una letra: .ahorcado a')
  if (g.guesses.includes(arg)) return ctx.reply('Ya usaste esa letra.\n'+board(g))
  g.guesses.push(arg)
  if(!g.word.includes(arg))g.left--
  if([...g.word].every(c=>g.guesses.includes(c))){games.delete(k);return ctx.reply('🏆 ¡Ganaste! Palabra: '+g.word)}
  if(g.left<=0){games.delete(k);return ctx.reply('Fin del juego. Palabra: '+g.word)}
  setGame(k,g);return ctx.reply('🎮 '+board(g)+'\nIntentos restantes: '+g.left)
}
async function trivia(ctx) {
  const k=key(ctx,'quiz'),arg=normalize(ctx.argText),g=getGame(k)
  if(!arg || arg==='nuevo'){
    if(g&&!arg)return ctx.reply('🧠 '+g.question+'\nResponde con .trivia respuesta')
    const [question,answer]=quiz[Math.floor(Math.random()*quiz.length)];setGame(k,{question,answer,left:3})
    return ctx.reply('🧠 *RS TRIVIA*\n'+question+'\nResponde con .trivia respuesta')
  }
  if(!g)return ctx.reply('Inicia con .trivia')
  if(arg===g.answer){games.delete(k);return ctx.reply('🏆 ¡Correcto!')}
  if(--g.left===0){games.delete(k);return ctx.reply('La respuesta era: '+g.answer)}
  setGame(k,g);return ctx.reply('❌ Incorrecto. Intentos restantes: '+g.left)
}
async function resize(ctx) {
  const [w,h]=ctx.args.map(Number)
  if(ctx.args.length!==2||![w,h].every(n=>Number.isInteger(n)&&n>=32&&n<=2048)||w*h>4000000)return ctx.reply('Uso: .resize 720 720 (32–2048 px)')
  try {
    const {buffer,type}=await ctx.downloadQuotedOrCurrent()
    if(!['imageMessage','stickerMessage'].includes(type))return ctx.reply('Responde a una imagen o sticker.')
    const image=await sharp(buffer,{limitInputPixels:16000000}).resize(w,h,{fit:'contain',background:'#0a1424'}).png().toBuffer()
    return ctx.sock.sendMessage(ctx.jid,{image,caption:'💎 RANDY SYSTEMS · '+w+' × '+h},{quoted:ctx.msg})
  }catch{return ctx.reply('❌ No pude redimensionar la imagen.')}
}
export const premiumCommands = {
  ...Object.fromEntries(Object.keys(actions).map(action=>[action,ctx=>anime(ctx,action)])),
  muak:ctx=>anime(ctx,'kiss'), beso:ctx=>anime(ctx,'kiss'), abrazo:ctx=>anime(ctx,'hug'),
  ahorcado:hangman, hangman, trivia, quiz:trivia,
  resize, redimensionar:resize,
  say:async ctx=>ctx.argText&&ctx.argText.length<=1000?ctx.reply('💬 RS · '+ctx.argText):ctx.reply('Uso: .say texto (máx. 1000 caracteres)')
}
