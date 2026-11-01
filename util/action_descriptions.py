import json
from functools import lru_cache
from typing import Dict

from util.paths import resource_path


@lru_cache(maxsize=1)
def _descriptions() -> Dict[str, Dict[str, str]]:
    with open(resource_path("assets/action_descriptions.json"), encoding="utf-8") as file:
        return json.load(file)


def describe(action: str, language: str) -> str:
    """What an action does, in a sentence or two; "" for an action that has no description."""
    return _descriptions().get(language, {}).get(action, "")
