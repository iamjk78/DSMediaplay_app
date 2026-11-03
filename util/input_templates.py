import json
import re
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

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


@dataclass(frozen=True)
class ColumnInfo:
    """One column of the input of an action as its template describes it."""
    number: int
    name: str
    expected: str
    block: Optional[int] = None  # which of the repeated blocks of columns it is in (the playlists of a group)


def _name_and_expected(text: str) -> "tuple[str, str]":
    """The name of a column and what it takes out of its description ("2. resolution (text as in the CSV, e.g. 1080p)")."""
    if ": " in text:
        name, expected = text.split(": ", 1)
        return name.strip(), expected.strip()
    found = re.fullmatch(r"(.+?) \((.*)\)\.?", text)
    if found:
        return found.group(1).strip(), found.group(2).strip()
    return text.strip(), text.strip()


def _layout(action: str, language: str):
    """The fixed columns of an action, and the one that repeats (a list of names, or blocks of columns) if there is one."""
    fixed: Dict[int, str] = {}
    repeated_from, repeated_text, parts = None, "", []
    for text in _templates()[language]["actions"][action]["columns"]:
        found = re.match(r"\s*(\d+)\.\s*(.*)$", text)
        part = re.match(r"\s*[a-z]\)\s*(.*)$", text)
        if found and re.match(r"(a další|a dál|and more|and on)\b", found.group(2)):
            repeated_from, repeated_text = int(found.group(1)), re.sub(r"^(a další|a dál|and more|and on)\s*:?\s*", "", found.group(2))
        elif found:
            fixed[int(found.group(1))] = found.group(2)
        elif part:
            parts.append(part.group(1))
    return fixed, repeated_from, repeated_text, parts


def column_info(action: str, language: str, column: int) -> Optional[ColumnInfo]:
    """What column number `column` (1 is the first) of the input of the action is; None for an action without a template."""
    if not has_template(action):
        return None
    fixed, repeated_from, repeated_text, parts = _layout(action, language)
    if column in fixed:
        name, expected = _name_and_expected(fixed[column])
        return ColumnInfo(column, name, expected)
    if repeated_from is None or column < repeated_from:
        return None
    if parts:
        block, index = divmod(column - repeated_from, len(parts))
        name, expected = _name_and_expected(parts[index])
        return ColumnInfo(column, name, expected, block + 1)
    name, expected = _name_and_expected(repeated_text)
    return ColumnInfo(column, name, expected)


def example_line(action: str, language: str) -> str:
    """The example line of the template with the tabs written as ⇥, so that it can be shown in a line of the log."""
    return "⇥".join(_templates()[language]["actions"][action]["example"])


def columns_overview(action: str, language: str) -> str:
    """The columns of an action in one line, as the template names them."""
    return "; ".join(text.strip() for text in _templates()[language]["actions"][action]["columns"]
                     if re.match(r"\s*\d+\.", text))
