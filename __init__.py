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

from ovos_utils import classproperty
from ovos_utils.log import LOG
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.skills.fallback import FallbackSkill
from neon_utils.message_utils import get_message_user
from neon_mq_connector.utils.client_utils import send_mq_request
from mycroft.skills.mycroft_skill.decorators import intent_file_handler


class LLMSkill(FallbackSkill):
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

    def initialize(self):
        self.register_fallback(self.fallback_llm, 85)

    def fallback_llm(self, message):
        utterance = message.data['utterance']
        user = get_message_user(message) or self._default_user
        answer = self._get_response(utterance, user)
        if not answer:
            LOG.info(f"No fallback response")
            return False
        self.speak(answer)
        return True

    @intent_file_handler("ask_chatgpt.intent")
    def handle_ask_chatgpt(self, message):
        utterance = message.data['utterance']
        user = get_message_user(message) or self._default_user
        resp = self._get_response(utterance, user)
        self.speak(resp)

    def _get_response(self, query: str, user: str) -> str:
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
        resp = mq_resp.get("response") or ""  # TODO: Get response from MQ endpoint
        if resp:
            self.chat_history[user].append(("user", query))
            self.chat_history[user].append(("llm", resp))
        LOG.debug(f"Got LLM response: {resp}")
        return resp


def create_skill():
    return LLMSkill()
