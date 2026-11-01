"""
Writes the pages of the user guide (documentation/pages/cz and /en) from what the application knows itself: the names
of its buttons and actions (assets/messages.json), the input templates of the actions (assets/input_templates.json)
and the list of the actions (util/actions.py), plus the texts in tools/documentation_texts.py. So every action of the
application is in the guide, under the name the window shows, and none that is not there.

It also writes assets/action_descriptions.json, the one-sentence descriptions the window shows over an action.

Run from the repository root after changing an action or a text:  python tools/generate_documentation.py
"""
import html
import json
import os
import shutil
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from documentation_texts import ACTIONS, CATEGORIES, PAGES, WORDS  # noqa: E402
from util.actions import action_needs_input, entity_actions  # noqa: E402

PAGES_DIR = os.path.join("documentation", "pages")
IMAGES_DIR = os.path.join("documentation", "web_assets", "images")
LANGUAGES = ("cz", "en")
CATEGORY_ORDER = ("Playlists", "Groups", "Players", "Locations", "Assets", "Deploy")
MESSAGES = json.load(open(os.path.join("assets", "messages.json"), encoding="utf-8"))
TEMPLATES = json.load(open(os.path.join("assets", "input_templates.json"), encoding="utf-8"))


class Words(dict):
    """The texts of the application's own buttons and fields, without the colon that ends a label."""

    def __missing__(self, key):
        raise KeyError(f"the guide uses {{{key}}}, which the application has no text for")


def words(language: str) -> Words:
    messages = MESSAGES[language]
    result = Words({key: value.rstrip(":") for key, value in messages.items() if isinstance(value, str)})
    result["pb_count"] = messages["pb_count"].format(shown="N", total="M")  # the message has the numbers to put in
    return result


def fill(text: str, ui: Words, **more) -> str:
    return text.format_map(Words({**ui, **{k: html.escape(v) for k, v in more.items()}}))


def page(language: str, name: str, title: str, body: str, links: dict) -> str:
    other = "en" if language == "cz" else "cz"
    ui = WORDS[language]
    navigation = "\n".join(f'            <li><a href="/{language}/{target}.html">{html.escape(label)}</a></li>'
                           for target, label in links.items())
    return f"""<!DOCTYPE html>
<html lang="{ui['lang']}">
<head>
    <meta charset="UTF-8">
    <title>{html.escape(title)} - {html.escape(ui['title'])}</title>
    <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
    <h1>{html.escape(title)}</h1>
    <nav>
        <ul>
{navigation}
        </ul>
    </nav>
{body}
    <footer>
        <a href="/{other}/{name}.html">{html.escape(WORDS[other]['english'] if other == 'en' else WORDS[other]['czech'])}</a>
        | <a href="/{language}/{name}.html">{html.escape(ui['czech'] if language == 'cz' else ui['english'])}</a>
    </footer>
</body>
</html>
"""


def example_table(cells) -> str:
    return "<table class=\"example\"><tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells) + "</tr></table>"


def action_section(language: str, category: str, label: str, key: str, ui: Words) -> str:
    word = WORDS[language]
    template = TEMPLATES[language]["actions"].get(key)
    if template:
        summary = html.escape(template["summary"])
    else:
        summary = fill(ACTIONS[key][language], ui)
    if key.startswith("get_"):
        kind = word["kind_csv"]
    elif key.startswith("show_"):
        kind = word["kind_window"]
    elif action_needs_input(key):
        kind = fill(word["kind_input"], ui)
    else:
        kind = fill(word["kind_noinput"], ui)
    input_part = fill(word["how_input"] if action_needs_input(key) else word["how_plain"], ui)
    how = fill(word["how_text"].replace("{input_part}", input_part), ui, category=category, label=label)
    parts = [f'<section id="{key}">', f"<h3>{html.escape(label)}</h3>", f"<p>{summary}</p>",
             f'<p class="kind">{kind}</p>']
    if template:
        parts.append(f"<h4>{word['input']}</h4>")
        parts.append("<ul>" + "".join(f"<li>{html.escape(column)}</li>" for column in template["columns"]) + "</ul>")
        parts.append("<ul class=\"notes\">" + "".join(f"<li>{html.escape(note)}</li>" for note in template["notes"])
                     + "</ul>")
        parts.append(f"<p>{word['example']}:</p>{example_table(template['example'])}")
    parts.append(f'<p class="how">{how}</p>')
    parts.append("</section>")
    return "\n".join(parts)


def category_page(language: str, category: str, ui: Words, links: dict) -> str:
    word = WORDS[language]
    title, intro = CATEGORIES[category][language]
    actions = entity_actions(MESSAGES[language]["actions"])[category]
    body = [f"<section><p>{html.escape(intro)}</p><p>{word['intro_actions']}</p><ul>"]
    for label, key in actions.items():
        body.append(f'<li><a href="#{key}">{html.escape(label)}</a></li>')
    body.append("</ul></section>")
    for label, key in actions.items():
        body.append(action_section(language, category, label, key, ui))
    return page(language, category.lower(), title, "\n".join(body), links)


def render() -> dict:
    """All the pages: {(language, name): the text of the page}."""
    pages = {}
    for language in LANGUAGES:
        ui = words(language)
        word = WORDS[language]
        links = {"index": word["home"], "window": word["window"], "table": word["table"],
                 **{category.lower(): CATEGORIES[category][language][0] for category in CATEGORY_ORDER}}
        for name, (title, body) in PAGES[language].items():
            pages[(language, name)] = page(language, name, title, fill(body, ui), links)
        for category in CATEGORY_ORDER:
            pages[(language, category.lower())] = category_page(language, category, ui, links)
    return pages


def action_descriptions() -> dict:
    """What every action does, as plain text, for the help the window shows over an action: {language: {key: text}}."""
    result = {}
    for language in LANGUAGES:
        ui = words(language)
        result[language] = {}
        for actions in entity_actions(MESSAGES[language]["actions"]).values():
            for key in actions.values():
                template = TEMPLATES[language]["actions"].get(key)
                result[language][key] = template["summary"] if template else fill(ACTIONS[key][language], ui)
    return result


def main() -> None:
    with open(os.path.join("assets", "action_descriptions.json"), "w", encoding="utf-8") as file:
        json.dump(action_descriptions(), file, ensure_ascii=False, indent=2)
        file.write("\n")
    pages = render()
    # Everything the pages could be left over from is replaced: a page of the old guide must not stay behind
    for language in LANGUAGES:
        folder = os.path.join(PAGES_DIR, language)
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
    for (language, name), text in pages.items():
        with open(os.path.join(PAGES_DIR, language, f"{name}.html"), "w", encoding="utf-8") as file:
            file.write(text)
    for language in LANGUAGES:
        print(f"{language}: {sum(1 for key in pages if key[0] == language)} pages")


if __name__ == "__main__":
    main()
