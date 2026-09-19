import json

from util.paths import resource_path


class LanguageManager:
    def __init__(self, language="en", config_path=str(resource_path("assets/messages.json"))):
        self.language = language
        self.config_path = config_path
        self.messages = self.load_messages()

    def set_language(self, language: "str"):
        self.language = language
        self.messages = self.load_messages()

    def load_messages(self):
        with open(self.config_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def get_message(self, key, **kwargs):
        keys = key.split('.')
        message = self.messages[self.language]
        for k in keys:
            message = message[k]
        if isinstance(message, str):
            return message.format(**kwargs)
        return message
