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
from enum import Enum
from threading import Thread
from time import time

from ovos_utils import classproperty
from ovos_utils.log import LOG
from ovos_utils.process_utils import RuntimeRequirements
# from ovos_workshop.skills.fallback import FallbackSkill
from neon_utils.skills.neon_fallback_skill import NeonFallbackSkill, NeonSkill
from neon_utils.message_utils import get_message_user
from neon_utils.user_utils import get_user_prefs
from neon_mq_connector.utils.client_utils import send_mq_request
from mycroft.skills.mycroft_skill.decorators import intent_file_handler


class LLM(Enum):
    GPT = "Chat GPT"


class LLMSkill(NeonFallbackSkill):
    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(internet_before_load=True,
                                   network_before_load=True,
                                   gui_before_load=False,
                                   requires_internet=True,
                                   requires_network=True,
                                   requires_gui=False,
                                   no_internet_fallback=False,
                                   no_network_fallback=False,
                                   no_gui_fallback=True)

    def __init__(self):
        super().__init__("LLM")
        self.chat_history = dict()
        self._default_user = "local"
        self.chatting = dict()

    @property
    def chat_timeout_seconds(self):
        return self.settings.get("chat_timeout_seconds") or 300

    @property
    def fallback_enabled(self):
        return self.settings.get("fallback_enabled", False)

    def initialize(self):
        self.register_entity_file("llm")
        if self.fallback_enabled:
            self.register_fallback(self.fallback_llm, 85)

    def fallback_llm(self, message):
        utterance = message.data['utterance']
        user = get_message_user(message) or self._default_user
        answer = self._get_llm_response(utterance, user)
        if not answer:
            LOG.info(f"No fallback response")
            return False
        self.speak(answer)
        return True

    @intent_file_handler("enable_fallback.intent")
    def handle_enable_fallback(self, message):
        if not self.fallback_enabled:
            self.settings['fallback_enabled'] = True
            self.register_fallback(self.fallback_llm, 85)
        self.speak_dialog("fallback_enabled")

    @intent_file_handler("disable_fallback.intent")
    def handle_disable_fallback(self, message):
        if self.fallback_enabled:
            self.settings['fallback_enabled'] = False
            self.remove_fallback(self.fallback_llm)
        self.speak_dialog("fallback_disabled")

    @intent_file_handler("ask_chatgpt.intent")
    def handle_ask_chatgpt(self, message):
        utterance = message.data['utterance']
        user = get_message_user(message) or self._default_user
        try:
            resp = self._get_llm_response(utterance, user)
            self.speak(resp)
        except Exception as e:
            LOG.exception(e)
            self.speak_dialog("no_chatgpt")

    @intent_file_handler("chat_with_llm.intent")
    def handle_chat_with_llm(self, message):
        user = get_message_user(message) or self._default_user
        self.gui.show_controlled_notification(
            self.translate("notify_llm_active"))
        llm = message.data.get('llm')
        if self.voc_match(llm, "chat_gpt"):
            llm = LLM.GPT
        else:
            LOG.warning(f"Requested invalid LLM: {llm}")
            llm = LLM.GPT
        self.speak_dialog("start_chat", {"llm": llm.value})
        self._reset_expiration(user)

    @intent_file_handler("email_chat_history.intent")
    def handle_email_chat_history(self, message):
        user_prefs = get_user_prefs(message)['user']
        username = user_prefs['username']
        email_addr = user_prefs['email']
        if username not in self.chat_history:
            LOG.debug(f"No history for {username}")
            self.speak_dialog("no_chat_history", private=True)
            return
        if not email_addr:
            LOG.debug("No email address")
            # TODO: Capture Email address
            self.speak_dialog("no_email_address", private=True)
            return
        self.speak_dialog("sending_chat_history",
                          {"email": email_addr}, private=True)
        self._send_email(username, email_addr)

    def _send_email(self, username: str, email: str):
        history = self.chat_history.get(username)
        email_text = ""
        for entry in history:
            email_text += f"[{entry[0]}] {entry[1]}\n"
        NeonSkill.send_email(self, "LLM Conversation", email_text,
                             email_addr=email)

    def _stop_chatting(self, message):
        user = get_message_user(message) or self._default_user
        self.gui.remove_controlled_notification()
        self.chatting.pop(user)
        self.speak_dialog("end_chat")
        event_name = f"end_converse.{user}"
        self.cancel_scheduled_event(event_name)

    def _get_llm_response(self, query: str, user: str) -> str:
        """
        Get a response from an LLM
        :param query: User utterance to generate a response to
        :param user: Username making the request
        :returns: Speakable response to the user's query
        """
        # TODO: support multiple LLM backends?
        self.chat_history.setdefault(user, list())
        mq_resp = send_mq_request("/llm", {"query": query,
                                           "history": self.chat_history[user]},
                                  "chat_gpt_input")
        resp = mq_resp.get("response") or ""
        if resp:
            username = "user" if user == self._default_user else user
            self.chat_history[user].append((username, query))
            self.chat_history[user].append(("llm", resp))
        LOG.debug(f"Got LLM response: {resp}")
        return resp

    def converse(self, message=None):
        user = get_message_user(message) or self._default_user
        if user not in self.chatting:
            return False
        last_message = self.chatting[user]
        if time() - last_message > self.chat_timeout_seconds:
            LOG.info(f"Chat session timed out")
            self._stop_chatting(message)
            return False
        # Take final utterance as one that wasn't normalized
        utterance = message.data.get('utterances', [""])[-1]
        if self.voc_match(utterance, "exit"):
            self._stop_chatting(message)
            return True
        Thread(target=self._threaded_converse, args=(utterance, user),
               daemon=True).start()
        return True

    def _threaded_converse(self, utterance, user):
        try:
            resp = self._get_llm_response(utterance, user)
            self.speak(resp)
            self._reset_expiration(user)
        except Exception as e:
            LOG.exception(e)
            self.speak_dialog("no_chatgpt")

    def _reset_expiration(self, user):
        self.chatting[user] = time()
        event_name = f"end_converse.{user}"
        self.cancel_scheduled_event(event_name)
        self.schedule_event(self._stop_chatting, self.chat_timeout_seconds,
                            {'user': user}, event_name)


def create_skill():
    return LLMSkill()
