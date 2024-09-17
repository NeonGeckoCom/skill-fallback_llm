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

from lingua_franca.format import nice_duration
from ovos_bus_client.message import Message
from ovos_utils import classproperty
from ovos_utils.log import LOG
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.skills.fallback import FallbackSkill
from ovos_workshop.decorators import intent_handler, fallback_handler
from neon_utils.message_utils import get_message_user, dig_for_message
from neon_utils.user_utils import get_user_prefs
from neon_utils.hana_utils import request_backend
from neon_mq_connector.utils.client_utils import send_mq_request


class LLM(Enum):
    GPT = "Chat GPT"
    FASTCHAT = "FastChat"


class LLMSkill(FallbackSkill):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chat_history = dict()
        self._default_user = "local"
        self._default_llm = LLM.FASTCHAT
        self.chatting = dict()
        self.register_entity_file("llm.entity")

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

    @property
    def chat_timeout_seconds(self):
        return self.settings.get("chat_timeout_seconds") or 300

    @property
    def fallback_enabled(self):
        return self.settings.get("fallback_enabled", False)

    @fallback_handler(85)
    def fallback_llm(self, message):
        if not self.fallback_enabled:
            LOG.info("LLM Fallback Disabled")
            return False
        utterance = message.data['utterance']
        LOG.info(f"Getting LLM response to: {utterance}")
        user = get_message_user(message) or self._default_user

        def _threaded_get_response(utt, usr):
            answer = self._get_llm_response(utt, usr, self._default_llm)
            if not answer:
                LOG.info(f"No fallback response")
                return
            self.speak(answer)

        # TODO: Speak filler?
        Thread(target=_threaded_get_response, args=(utterance, user), daemon=True).start()
        return True

    @intent_handler("enable_fallback.intent")
    def handle_enable_fallback(self, message):
        if not self.fallback_enabled:
            self.settings['fallback_enabled'] = True
        self.speak_dialog("fallback_enabled")

    @intent_handler("disable_fallback.intent")
    def handle_disable_fallback(self, message):
        if self.fallback_enabled:
            self.settings['fallback_enabled'] = False
        self.speak_dialog("fallback_disabled")

    @intent_handler("ask_llm.intent")
    def handle_ask_chatgpt(self, message):
        utterance = message.data['utterance']
        llm = self._get_requested_llm(message)
        user = get_message_user(message) or self._default_user
        try:
            resp = self._get_llm_response(utterance, user, llm)
            self.speak(resp)
        except Exception as e:
            LOG.exception(e)
            self.speak_dialog("no_chatgpt")

    @intent_handler("chat_with_llm.intent")
    def handle_chat_with_llm(self, message):
        user = get_message_user(message) or self._default_user
        self.gui.show_controlled_notification(
            self.translate("notify_llm_active"))
        llm = self._get_requested_llm(message)
        timeout_duration = nice_duration(self.chat_timeout_seconds)
        self.speak_dialog("start_chat", {"llm": llm.value,
                                         "timeout": timeout_duration})
        self._reset_expiration(user, llm)

    @intent_handler("email_chat_history.intent")
    def handle_email_chat_history(self, message):
        user_prefs = get_user_prefs(message)['user']
        username = user_prefs['username']
        email_addr = user_prefs['email']
        if username not in self.chat_history:
            LOG.debug(f"No history for {username}")
            self.speak_dialog("no_chat_history")
            return
        if not email_addr:
            LOG.debug("No email address")
            # TODO: Capture Email address
            self.speak_dialog("no_email_address")
            return
        self.speak_dialog("sending_chat_history",
                          {"email": email_addr})
        self._send_email(username, email_addr)

    def _send_email(self, username: str, email: str):
        history = self.chat_history.get(username)
        email_text = ""
        for entry in history:
            formatted = entry[1].replace('\n\n', '\n').replace('\n', '\n\t...')
            email_text += f"[{entry[0]}] {formatted}\n"
        self.send_email("LLM Conversation", email_text, email_addr=email)

    def _stop_chatting(self, message):
        user = get_message_user(message) or self._default_user
        self.gui.remove_controlled_notification()
        self.chatting.pop(user)
        self.speak_dialog("end_chat")
        event_name = f"end_converse.{user}"
        self.cancel_scheduled_event(event_name)

    def _get_llm_response(self, query: str, user: str, llm: LLM) -> str:
        """
        Get a response from an LLM
        :param query: User utterance to generate a response to
        :param user: Username making the request
        :returns: Speakable response to the user's query
        """
        if llm == LLM.GPT:
            endpoint = "chatgpt"
        elif llm == LLM.FASTCHAT:
            endpoint = "fastchat"
        else:
            raise ValueError(f"Expected LLM, got: {llm}")
        self.chat_history.setdefault(user, list())
        resp = request_backend(f"/llm/{endpoint}", {"query": query, "history": self.chat_history[user]})

        resp = resp.get("response") or ""
        if resp:
            username = "user" if user == self._default_user else user
            self.chat_history[user].append((username, query))
            self.chat_history[user].append(("llm", resp))
        LOG.debug(f"Got LLM response: {resp}")
        return resp

    def _get_requested_llm(self, message: Message) -> LLM:
        request = message.data.get('llm') or message.data.get('utterance')
        if self.voc_match(request, "chat_gpt"):
            llm = LLM.GPT
        elif self.voc_match(request, "fastchat"):
            llm = LLM.FASTCHAT
        else:
            LOG.warning(f"No valid LLM in request: {request}")
            llm = LLM.GPT
        return llm

    def converse(self, message=None):
        user = get_message_user(message) or self._default_user
        if user not in self.chatting:
            return False
        last_message = self.chatting[user][0]
        if time() - last_message > self.chat_timeout_seconds:
            LOG.info(f"Chat session timed out")
            self._stop_chatting(message)
            return False
        # Take final utterance as one that wasn't normalized
        utterance = message.data.get('utterances', [""])[-1]
        if self.voc_match(utterance, "exit") and len(utterance.split()) < 4:
            # TODO: Imperfect check for "stop" or "exit"
            self._stop_chatting(message)
            return True
        Thread(target=self._threaded_converse, args=(utterance, user),
               daemon=True).start()
        return True

    def _threaded_converse(self, utterance, user):
        try:
            llm = self.chatting[user][1]
            resp = self._get_llm_response(utterance, user, llm)
            self.speak(resp)
            self._reset_expiration(user, llm)
        except Exception as e:
            LOG.exception(e)
            self.speak_dialog("no_chatgpt")

    def _reset_expiration(self, user, llm):
        self.chatting[user] = (time(), llm)
        event_name = f"end_converse.{user}"
        self.cancel_scheduled_event(event_name)
        self.schedule_event(self._stop_chatting, self.chat_timeout_seconds,
                            {'user': user}, event_name)

    # TODO: copied from NeonSkill. This method should be moved to a standalone
    #       utility
    def send_email(self, title, body, message=None, email_addr=None,
                   attachments=None):
        """
        Send an email to the registered user's email.
        Method here for backwards compatibility with Mycroft skills.
        Email address priority: email_addr, user prefs from message,
         fallback to DeviceApi for Mycroft method

        Arguments:
            title (str): Title of email
            body  (str): HTML body of email. This supports
                         simple HTML like bold and italics
            email_addr (str): Optional email address to send message to
            attachments (dict): Optional dict of file names to Base64 encoded files
            message (Message): Optional message to get email from
        """
        message = message or dig_for_message()
        if not email_addr and message:
            email_addr = get_user_prefs(message)["user"].get("email")

        if email_addr and send_mq_request:
            LOG.info("Send email via Neon Server")
            request_data = {"recipient": email_addr,
                            "subject": title,
                            "body": body,
                            "attachments": attachments}
            data = send_mq_request("/neon_emails", request_data,
                                   "neon_emails_input")
            return data.get("success")
        else:
            LOG.warning("Attempting to send email via Mycroft Backend")
            super().send_email(title, body)
