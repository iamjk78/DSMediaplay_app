import json
import textwrap
from functools import lru_cache
from typing import Dict, List

from util.paths import resource_path

LANGUAGES = ("cz", "en")
COMMENT_PREFIX = "# "
WRAP_WIDTH = 90  # characters; the input window shows about 100 without scrolling sideways


@lru_cache(maxsize=1)
def _templates() -> Dict[str, dict]:
    with open(resource_path("assets/input_templates.json"), encoding="utf-8") as file:
        return json.load(file)


def has_template(action: str) -> bool:
    return all(action in _templates()[language]["actions"] for language in LANGUAGES)


def template_lines(action: str, language: str) -> List[str]:
    """The description as comment lines, followed by one example line whose cells are separated by tabs."""
    data = _templates()[language]
    common, item = data["common"], data["actions"][action]
    description = [f"{common['title']}: {item['summary']}", common["tab"], common["names"],
                   *item["columns"], *item["notes"], common["skip"]]
    comments = [wrapped for line in description
                for wrapped in textwrap.wrap(line, width=WRAP_WIDTH, initial_indent=COMMENT_PREFIX,
                                             subsequent_indent="#   ", break_long_words=False)]
    return comments + ["\t".join(item["example"])]


def build_template(action: str, language: str) -> str:
    return "\n".join(template_lines(action, language)) + "\n"


def strip_template(text: str, action: str) -> str:
    """
    Removes the lines of an inserted template that the user left unchanged (in either language), so that a template
    left in the input window is never processed as data. Only exact copies are removed: a line the user has edited
    or added, even one starting with "#", is data.
    """
    if not has_template(action):
        return text
    known = {line for language in LANGUAGES for line in template_lines(action, language)}
    return "\n".join(line for line in text.split("\n") if line.rstrip("\r") not in known)
