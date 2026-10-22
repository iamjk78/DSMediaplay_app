"""A message that is asked for under a key or with values the file does not have fails with a KeyError at the moment it
is to be shown, which for a log line in the middle of a batch ends the batch (the message that reports the problem is
the one that crashed)."""
import ast
import json
import os
import string
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# get_message, and the two helpers of the processors that pass the key on to it
LOOKUPS = ("get_message", "_write_log_warning", "_write_log_error")
SOURCE_DIRECTORIES = ("api_testing", "gui_app", "json_manager", "processor", "util")


def placeholders(text: str) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def lookup(messages: dict, key: str):
    for part in key.split("."):
        messages = messages[part]
    return messages


def calls_asking_for_a_message():
    """(file, line, key, names of the values given) of every call written as get_message("key", name=...)."""
    for directory in SOURCE_DIRECTORIES:
        for folder, _, files in os.walk(os.path.join(ROOT, directory)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as file:
                    tree = ast.parse(file.read())
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr in LOOKUPS and node.args
                            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                            and all(keyword.arg for keyword in node.keywords)):  # **values cannot be checked
                        yield (os.path.relpath(path, ROOT), node.lineno, node.args[0].value,
                               {keyword.arg for keyword in node.keywords})


class MessageKeysTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "assets", "messages.json"), encoding="utf-8") as file:
            cls.messages = json.load(file)

    def test_there_are_calls_to_check(self):
        self.assertGreater(len(list(calls_asking_for_a_message())), 100)

    def test_every_message_asked_for_exists_in_both_languages_and_is_given_all_its_values(self):
        problems = []
        for path, line, key, given in calls_asking_for_a_message():
            for language, messages in self.messages.items():
                try:
                    text = lookup(messages, key)
                except KeyError:
                    problems.append(f"{path}:{line} {language}: no message {key!r}")
                    continue
                if isinstance(text, str) and placeholders(text) - given:
                    problems.append(f"{path}:{line} {language}: {key!r} needs {sorted(placeholders(text) - given)}")
        self.assertEqual(problems, [])

    def test_both_languages_have_the_same_messages_with_the_same_values_in_them(self):
        czech, english = self.messages["cz"], self.messages["en"]
        self.assertEqual(sorted(set(czech) ^ set(english)), [])
        different = [key for key in czech if isinstance(czech[key], str) and isinstance(english[key], str)
                     and placeholders(czech[key]) != placeholders(english[key])]
        self.assertEqual(different, [])


if __name__ == "__main__":
    unittest.main()
