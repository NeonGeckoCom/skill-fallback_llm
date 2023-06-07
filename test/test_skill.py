# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2022 Neongecko.com Inc.
# Contributors: Daniel McKnight, Guy Daniels, Elon Gasper, Richard Leeds,
# Regina Bloomstine, Casimiro Ferreira, Andrii Pernatii, Kirill Hrymailo
# BSD-3 License
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS;  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE,  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import unittest

from os import mkdir
from os.path import dirname, join, exists
from mock import Mock
from ovos_utils.messagebus import FakeBus
from mycroft_bus_client import Message
from lingua_franca import load_language
from mycroft.skills.skill_loader import SkillLoader


class TestSkill(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        bus = FakeBus()
        bus.run_in_thread()
        skill_loader = SkillLoader(bus, dirname(dirname(__file__)))
        skill_loader.load()
        cls.skill = skill_loader.instance

        # Define a directory to use for testing
        cls.test_fs = join(dirname(__file__), "skill_fs")
        if not exists(cls.test_fs):
            mkdir(cls.test_fs)

        # Override the configuration and fs paths to use the test directory
        cls.skill.settings_write_path = cls.test_fs
        cls.skill.file_system.path = cls.test_fs
        cls.skill._init_settings()
        cls.skill.initialize()

        # Override speak and speak_dialog to test passed arguments
        cls.skill.speak = Mock()
        cls.skill.speak_dialog = Mock()

    def setUp(self):
        self.skill.speak.reset_mock()
        self.skill.speak_dialog.reset_mock()

    def test_handle_enable_fallback(self):
        self.skill.handle_enable_fallback(None)
        self.skill.speak_dialog.assert_called_once_with("fallback_enabled")
        self.assertTrue(self.skill.fallback_enabled)

    def test_handle_disable_fallback(self):
        self.skill.handle_disable_fallback(None)
        self.skill.speak_dialog.assert_called_once_with("fallback_disabled")
        self.assertFalse(self.skill.fallback_enabled)

    def test_chat_timeout_seconds(self):
        self.assertIsInstance(self.skill.chat_timeout_seconds, int)
        self.skill.settings['chat_timeout_seconds'] = 500
        self.assertEqual(self.skill.chat_timeout_seconds, 500)

    def test_handle_ask_chatgpt(self):
        real_get_response = self.skill._get_llm_response
        mock = Mock()
        self.skill._get_llm_response = mock
        mock.return_value = "test"

        fake_msg = Message("test", {"utterance": "testing"},
                           {"username": "test_user"})
        self.skill.handle_ask_chatgpt(fake_msg)
        mock.assert_called_once_with("testing", "test_user")
        self.skill.speak.assert_called_once_with("test")

        def raise_exception():
            raise Exception()

        mock.side_effect = raise_exception
        self.skill.handle_ask_chatgpt(fake_msg)
        self.skill.speak.assert_called_once()
        self.skill.speak_dialog.assert_called_once_with("no_chatgpt")

        self.skill._get_llm_response = real_get_response

    def test_handle_chat_with_llm(self):
        self.skill.settings['chat_timeout_seconds'] = 300
        load_language(self.skill.lang)
        fake_msg = Message("test", {},
                           {"username": "test_user"})
        self.skill.chatting = dict()
        self.skill.handle_chat_with_llm(fake_msg)
        self.assertIsInstance(self.skill.chatting["test_user"], float)
        self.skill.speak_dialog.assert_called_once_with(
            "start_chat", {"llm": "Chat GPT", "timeout": "five minutes"},
            private=True)

    def test_handle_email_chat_history(self):
        real_send_email = self.skill._send_email
        self.skill._send_email = Mock()

        from neon_utils.user_utils import get_default_user_config
        default_profile = get_default_user_config()
        default_profile['user']['username'] = 'test_user'
        default_profile['user']['email'] = ''
        test_message = Message("", {}, {"username": "test_user",
                                        "user_profiles": [default_profile]})
        # No Chat History
        self.skill.handle_email_chat_history(test_message)
        self.skill.speak_dialog.assert_called_once_with("no_chat_history",
                                                        private=True)

        # No Email Address
        self.skill.chat_history['test_user'] = [("user", "hey"), ("llm", "hi")]
        self.skill.handle_email_chat_history(test_message)
        self.skill.speak_dialog.assert_called_with("no_email_address",
                                                   private=True)

        # Valid Request
        test_message.context['user_profiles'][0]['user']['email'] = \
            "test@neon.ai"
        self.skill.handle_email_chat_history(test_message)
        self.skill.speak_dialog.assert_called_with("sending_chat_history",
                                                   {"email": "test@neon.ai"},
                                                   private=True)
        self.skill._send_email.assert_called_once_with("test_user",
                                                       "test@neon.ai")

        self.skill._send_email = real_send_email

    def test_converse(self):
        # TODO
        pass

    def test_threaded_converse(self):
        # TODO
        pass

    def test_reset_expiration(self):
        # TODO
        pass

    def test_stop_chatting(self):
        # TODO
        pass

    def test_send_email(self):
        # TODO
        pass


if __name__ == '__main__':
    unittest.main()
