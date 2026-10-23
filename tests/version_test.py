"""The version of the application is written in one place and everything that shows it is made from that."""
import os
import re
import subprocess
import unittest

from util.version import VERSION
from settings_and_log_window_test import WindowCase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as file:
        return file.read()


class VersionTest(unittest.TestCase):
    def test_it_is_three_numbers(self):
        self.assertRegex(VERSION, r"^\d+\.\d+\.\d+$")

    def test_the_build_takes_it_from_that_file_and_nowhere_else(self):
        spec = read("DSMediaplay_app.spec")

        self.assertIn("from util.version import VERSION", spec)
        self.assertIn("version=VERSION", spec)  # the macOS bundle
        self.assertIn("version=version_info", spec)  # the Windows file properties
        self.assertNotRegex(spec, r'version="\d')

    def test_the_workflow_refuses_a_tag_that_is_not_the_version(self):
        workflow = read(".github", "workflows", "build.yml")
        script = re.search(r"version=\$\(sed -n '(.+?)' util/version.py\)", workflow).group(1)

        found = subprocess.run(["sed", "-n", script, os.path.join(ROOT, "util", "version.py")], capture_output=True,
                               text=True).stdout.strip()

        self.assertEqual(found, VERSION)
        self.assertIn('[ "$RELEASE_TAG" = "v$version" ]', workflow)


class VersionInTheWindowTest(WindowCase):
    def test_the_title_of_the_window_says_the_version_in_both_languages(self):
        self.assertTrue(self.app.title().endswith(VERSION))
        self.app.all_data["lang"] = "en"
        self.app.lang.set_language("en")
        self.app.refresh_ui()

        self.assertTrue(self.app.title().endswith(VERSION))
        self.assertIn("DSMediaplay", self.app.title())


if __name__ == "__main__":
    unittest.main()
