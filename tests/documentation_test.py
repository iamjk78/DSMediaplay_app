"""The user guide is generated from what the application knows itself (tools/generate_documentation.py): it has every
action under the name the window shows, it is up to date with the generator, and its links lead somewhere."""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.chdir(ROOT)  # the generator reads the files with paths from the repository root

import generate_documentation as generator  # noqa: E402
from documentation.server import CustomHTTPRequestHandler  # noqa: E402
from util.actions import entity_actions  # noqa: E402

PAGES_DIR = os.path.join(ROOT, "documentation", "pages")


def read(language, name):
    with open(os.path.join(PAGES_DIR, language, f"{name}.html"), encoding="utf-8") as file:
        return file.read()


class GuideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rendered = generator.render()

    def test_the_pages_on_disk_are_what_the_generator_makes_now(self):
        for (language, name), text in self.rendered.items():
            with self.subTest(language=language, page=name):
                self.assertEqual(read(language, name), text, "run: python tools/generate_documentation.py")

    def test_there_are_no_other_pages_on_disk(self):
        for language in generator.LANGUAGES:
            on_disk = {name[:-5] for name in os.listdir(os.path.join(PAGES_DIR, language))}
            made = {name for lang, name in self.rendered if lang == language}
            self.assertEqual(on_disk, made)

    def test_both_languages_have_the_same_pages_and_every_action_of_the_window_is_on_its_page(self):
        with open(os.path.join(ROOT, "assets", "messages.json"), encoding="utf-8") as file:
            messages = json.load(file)
        for language in generator.LANGUAGES:
            actions = entity_actions(messages[language]["actions"])
            for category, labels in actions.items():
                page = self.rendered[(language, category.lower())]
                for label, key in labels.items():
                    with self.subTest(language=language, action=key):
                        self.assertIn(f'<section id="{key}">', page)
                        self.assertIn(f"<h3>{label.replace('&', '&amp;')}</h3>", page)
        self.assertEqual({name for lang, name in self.rendered if lang == "cz"},
                         {name for lang, name in self.rendered if lang == "en"})

    def test_no_text_of_the_application_is_left_unfilled(self):
        for (language, name), text in self.rendered.items():
            with self.subTest(language=language, page=name):
                self.assertNotRegex(text, r"\{[a-z_]+\}")

    def test_every_link_of_the_guide_leads_to_a_page_and_every_anchor_to_a_section(self):
        for (language, name), text in self.rendered.items():
            for target in re.findall(r'href="(/[a-z]{2}/[a-z_]+\.html)"', text):
                with self.subTest(language=language, page=name, link=target):
                    self.assertIn((target.split("/")[1], target.split("/")[2][:-5]), self.rendered)
            for anchor in re.findall(r'href="#([a-z_]+)"', text):
                with self.subTest(language=language, page=name, anchor=anchor):
                    self.assertIn(f'id="{anchor}"', text)

    def test_the_server_finds_every_page_and_the_style(self):
        handler = CustomHTTPRequestHandler.__new__(CustomHTTPRequestHandler)
        for language, name in self.rendered:
            with self.subTest(language=language, page=name):
                self.assertTrue(os.path.isfile(handler.resolve_path(f"/{language}/{name}.html")))
        self.assertTrue(os.path.isfile(handler.resolve_path("/assets/css/style.css")))
        self.assertTrue(os.path.isfile(handler.resolve_path("/cz/")))
        self.assertTrue(os.path.isfile(handler.resolve_path("/en/")))

    def test_the_pictures_that_are_there_are_the_ones_the_pages_ask_for(self):
        for (language, name), text in self.rendered.items():
            for picture in re.findall(r'src="/assets/images/([^"]+)"', text):
                with self.subTest(page=name, picture=picture):
                    self.assertRegex(picture, rf"_{language}\.png$")  # a picture in the language of the page

    def test_every_picture_the_pages_ask_for_exists(self):
        handler = CustomHTTPRequestHandler.__new__(CustomHTTPRequestHandler)
        for (language, name), text in self.rendered.items():
            for picture in re.findall(r'src="(/assets/images/[^"]+)"', text):
                with self.subTest(page=name, picture=picture):
                    self.assertTrue(os.path.isfile(handler.resolve_path(picture)),
                                    "run: tools/capture_documentation_images.sh")

    def test_the_guide_does_not_mention_what_the_application_does_not_have(self):
        for (language, name), text in self.rendered.items():
            with self.subTest(language=language, page=name):
                self.assertNotIn("Kopírování parametrů", text)
                self.assertNotIn("bez dalšího potvrzení", text)


class LanguageBarTest(unittest.TestCase):
    """The bar that switches the language is at the end of the page, under the text, and goes away once a language is picked."""

    @classmethod
    def setUpClass(cls):
        cls.rendered = generator.render()

    def test_on_every_page_it_comes_after_the_whole_text(self):
        for (language, name), text in self.rendered.items():
            with self.subTest(language=language, page=name):
                self.assertEqual(text.count('<footer id="language-bar">'), 1)
                self.assertGreater(text.index('<footer id="language-bar">'), text.rindex("</section>"))

    def test_every_page_loads_the_script_that_hides_it(self):
        for (language, name), text in self.rendered.items():
            with self.subTest(language=language, page=name):
                self.assertIn('<script src="/assets/js/language-bar.js"></script>', text)

    def test_it_is_not_fixed_to_the_bottom_of_the_window_where_it_would_cover_the_last_lines(self):
        with open(os.path.join(ROOT, "documentation", "web_assets", "css", "style.css"), encoding="utf-8") as file:
            css = file.read()
        rule = re.search(r"(?m)^footer\s*\{([^}]*)\}", css).group(1)

        self.assertNotRegex(rule, r"position\s*:\s*(fixed|sticky|absolute)")
        self.assertNotIn("bottom", rule)
        self.assertRegex(css, r"footer\[hidden\]\s*\{\s*display\s*:\s*none")

    def test_the_server_serves_the_script(self):
        handler = CustomHTTPRequestHandler.__new__(CustomHTTPRequestHandler)
        self.assertTrue(os.path.isfile(handler.resolve_path("/assets/js/language-bar.js")))

    def test_the_script_remembers_a_click_on_a_language_and_hides_the_bar_from_then_on(self):
        with open(os.path.join(ROOT, "documentation", "web_assets", "js", "language-bar.js"), encoding="utf-8") as file:
            script = file.read()

        for part in ('getElementById("language-bar")', 'localStorage.getItem(KEY)', 'localStorage.setItem(KEY',
                     "bar.hidden = true", 'addEventListener("click"', 'closest("a")'):
            self.assertIn(part, script)
        self.assertEqual(script.count("bar.hidden = true"), 2)  # at the load when it was picked before, and at the click

    def test_without_storage_the_bar_stays_and_nothing_breaks(self):
        with open(os.path.join(ROOT, "documentation", "web_assets", "js", "language-bar.js"), encoding="utf-8") as file:
            script = file.read()

        self.assertEqual(script.count("try {"), 2)  # both uses of the storage are guarded
        self.assertEqual(script.count("catch (error)"), 2)

    def test_the_script_is_part_of_what_the_build_bundles(self):
        with open(os.path.join(ROOT, "DSMediaplay_app.spec"), encoding="utf-8") as file:
            spec = file.read()
        self.assertIn('("documentation/web_assets", "documentation/web_assets")', spec)  # the whole folder, js included


if __name__ == "__main__":
    unittest.main()
