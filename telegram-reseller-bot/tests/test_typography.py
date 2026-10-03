import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

import bot
from typography import DeveloperBot, developer_text, style_markup


class TypographyTests(unittest.IsolatedAsyncioTestCase):
    def test_messages_keep_copyable_tokens_and_html(self):
        source = ('Hola <b>Mi cuenta</b> · <code>RANDY-1234-ABCD</code> '
                  'Abre https://example.com/install/abc y escribe a @Randy. &amp;')
        styled = developer_text(source)
        self.assertIn('𝙃𝙤𝙡𝙖 <b>𝙈𝙞 𝙘𝙪𝙚𝙣𝙩𝙖</b>', styled)
        self.assertIn('<code>RANDY-1234-ABCD</code>', styled)
        self.assertIn('https://example.com/install/abc', styled)
        self.assertIn('@Randy', styled)
        self.assertIn('&amp;', styled)

    def test_menus_stay_navigable_with_styled_labels(self):
        source = ReplyKeyboardMarkup([[KeyboardButton('🛒 Comprar keys')]], resize_keyboard=True)
        styled = style_markup(source)
        label = styled.keyboard[0][0].text
        self.assertIn('𝘾𝙤𝙢𝙥𝙧𝙖𝙧', label)
        self.assertEqual(bot.canonical_menu_text(label), '🛒 Comprar keys')
        inline = style_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton('Ver certificado', callback_data='cert:confirm')]]))
        self.assertEqual(inline.inline_keyboard[0][0].callback_data, 'cert:confirm')
        self.assertIn('𝙑𝙚𝙧', inline.inline_keyboard[0][0].text)
        web_app = WebAppInfo('https://example.com/private')
        web_button = style_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton('Abrir web', web_app=web_app)]]))
        self.assertIs(web_button.inline_keyboard[0][0].web_app, web_app)

    async def test_bot_styles_announcements_and_buttons_before_sending(self):
        client = DeveloperBot('123:TEST_TOKEN')
        data = {'chat_id': 2, 'text': 'Anuncio para socios',
                'reply_markup': ReplyKeyboardMarkup([[KeyboardButton('Mi cuenta')]])}
        with patch.object(DeveloperBot, '_do_post', new_callable=AsyncMock, return_value={}) as send:
            await client._post('sendMessage', data)
        sent = send.await_args.kwargs['data']
        self.assertIn('𝘼𝙣𝙪𝙣𝙘𝙞𝙤', sent['text'])
        self.assertIn('𝙈𝙞 𝙘𝙪𝙚𝙣𝙩𝙖', sent['reply_markup'].keyboard[0][0].text)
        self.assertEqual(data['text'], 'Anuncio para socios')


if __name__ == '__main__':
    unittest.main()
