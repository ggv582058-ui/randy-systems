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
  ...ownerCommands
}
