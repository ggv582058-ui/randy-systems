import { generalCommands } from './general.js'
import { toolCommands } from './tools.js'
import { mediaCommands } from './media.js'
import { aiCommands } from './ai.js'
import { groupCommands } from './groups.js'
import { stickerCommands } from './stickers.js'
import { socialCommands } from './social.js'
import { funCommands } from './fun.js'
import { downloadCommands } from './downloads.js'
import { ownerCommands } from './owner.js'
import { premiumCommands } from './premium.js'

export const commands = {
  ...generalCommands,
  ...toolCommands,
  ...mediaCommands,
  ...aiCommands,
  ...groupCommands,
  ...stickerCommands,
  ...socialCommands,
  ...funCommands,
  ...downloadCommands,
  ...ownerCommands,
  ...premiumCommands,
  s2: stickerCommands.sa,
  toimage: stickerCommands.toimg,
  getpic: toolCommands.avatar,
  pfp: toolCommands.avatar,
  qrcode: toolCommands.qr,
  reel: downloadCommands.ig,
  play2: downloadCommands.playvideo,
  mp4: downloadCommands.playvideo,
  mp3: downloadCommands.play,
  profile: socialCommands.perfil,
  allmenu: generalCommands.comandos,
  info: generalCommands.botinfo,
  status: generalCommands.estado,
  p: generalCommands.ping
}
