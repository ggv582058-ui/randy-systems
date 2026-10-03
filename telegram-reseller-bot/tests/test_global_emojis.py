import unittest
from unittest.mock import patch, AsyncMock
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.error import BadRequest
from emoji_style import decorate_data
from typography import DeveloperBot

class GlobalEmojiTests(unittest.IsolatedAsyncioTestCase):
    def test_global_icons_keep_html_specific_icons_and_button_action(self):
        markup = InlineKeyboardMarkup([[InlineKeyboardButton('✅ Continuar', callback_data='keep:action')]])
        with patch('emoji_style.resolve_icon', return_value='1234567890123456789'):
            result = decorate_data({'text': '✅ <b>Listo</b> <code>✅ key</code> <tg-emoji emoji-id="9">✅</tg-emoji>', 'parse_mode': 'HTML', 'reply_markup': markup})
        self.assertEqual(result['text'].count('emoji-id="1234567890123456789"'), 1)
        self.assertIn('<code>✅ key</code>', result['text'])
        self.assertIn('emoji-id="9"', result['text'])
        button=result['reply_markup'].inline_keyboard[0][0]
        self.assertEqual(button.callback_data,'keep:action')
        self.assertEqual(button.text,'Continuar')
        self.assertEqual(markup.inline_keyboard[0][0].text,'✅ Continuar')

    async def test_entity_offsets_are_not_changed_by_developer_font(self):
        client=DeveloperBot('123:TEST_TOKEN')
        entities=[MessageEntity('custom_emoji',0,2,custom_emoji_id='1234567890123456789')]
        with patch.object(DeveloperBot,'_do_post',new_callable=AsyncMock,return_value={}) as send:
            await client._post('sendMessage',{'text':'✅ Hello','entities':entities})
        self.assertEqual(send.await_args.kwargs['data']['text'],'✅ Hello')
        self.assertEqual(send.await_args.kwargs['data']['entities'],entities)

    async def test_rejected_custom_icons_retry_without_losing_action(self):
        client=DeveloperBot('123:TEST_TOKEN')
        with patch('emoji_style.resolve_icon',return_value='1234567890123456789'), patch.object(DeveloperBot,'_do_post',new_callable=AsyncMock,side_effect=[BadRequest('custom emoji invalid'),{}]) as send:
            await client._post('sendMessage',{'text':'✅ Listo','reply_markup':InlineKeyboardMarkup([[InlineKeyboardButton('✅ Continuar',callback_data='next')]])})
        self.assertEqual(send.await_count,2)
        fallback=send.await_args.kwargs['data']
        self.assertNotIn('<tg-emoji',fallback['text'])
        self.assertEqual(fallback['reply_markup'].inline_keyboard[0][0].callback_data,'next')
