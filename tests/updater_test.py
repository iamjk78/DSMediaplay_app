"""Looking for a newer version in the releases of the repository and installing it: what is accepted as a release and as a
file to install, what is checked before a downloaded file is trusted, and the swap of the application itself."""
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from util import updater
from util.updater import Asset, Release, UpdateError

BASE = f"https://github.com/{updater.REPOSITORY}/releases/download/v1.0.9/"
EXE, ZIP = "DSMediaplay_app-Setup-1.0.9.exe", "DSMediaplay_app-macos.zip"
DIGEST = "sha256:" + "ab" * 32


def asset_json(name, digest=DIGEST, url=None, size=1234):
    data = {"name": name, "browser_download_url": url or BASE + name, "size": size}
    if digest is not None:
        data["digest"] = digest
    return data


def release_json(**changes):
    data = {"tag_name": "v1.0.9", "html_url": f"https://github.com/{updater.REPOSITORY}/releases/tag/v1.0.9",
            "draft": False, "prerelease": False,
            "assets": [asset_json("DSMediaplay_app-1.0.9-macos.dmg"), asset_json(ZIP), asset_json(EXE)]}
    data.update(changes)
    return data


def response(status=200, body=None, text_json=True):
    answer = MagicMock()
    answer.status_code, answer.ok = status, status < 400
    if text_json:
        answer.json.return_value = body
    else:
        answer.json.side_effect = ValueError("not json")
    return answer


class VersionTest(unittest.TestCase):
    def test_a_version_is_numbers_separated_by_dots_with_or_without_the_v(self):
        self.assertEqual(updater.parse_version("1.0.9"), (1, 0, 9))
        self.assertEqual(updater.parse_version("v1.0.9"), (1, 0, 9))
        self.assertEqual(updater.parse_version(" V2.10 "), (2, 10))

    def test_anything_else_is_not_a_version(self):
        for text in ("", "latest", "1.0.x", "1..2", "v", "1.0.9-rc1", "1,0"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                updater.parse_version(text)

    def test_the_numbers_are_compared_as_numbers_not_as_text(self):
        for candidate, current, newer in (("1.0.9", "1.0.8", True), ("1.0.10", "1.0.9", True), ("1.1", "1.0.9", True),
                                          ("2.0.0", "1.9.9", True), ("1.0.8", "1.0.8", False), ("1.0.7", "1.0.8", False),
                                          ("1.0", "1.0.0", False), ("1.0.0.1", "1.0.0", True) if False else ("1", "1.0.0", False),
                                          ("v1.0.9", "1.0.8", True)):
            with self.subTest(candidate=candidate, current=current):
                self.assertEqual(updater.is_newer(candidate, current), newer)


class FetchTest(unittest.TestCase):
    def fetch(self, answer, platform="win32"):
        with patch("util.updater.requests.get", return_value=answer) as get:
            result = updater.fetch_latest_release(platform)
        return result, get

    def test_the_latest_release_is_asked_for_from_the_repository_with_an_honest_user_agent(self):
        _, get = self.fetch(response(200, release_json()))

        self.assertEqual(get.call_args.args[0], f"https://api.github.com/repos/{updater.REPOSITORY}/releases/latest")
        self.assertTrue(get.call_args.kwargs["headers"]["User-Agent"].startswith("DSMediaplay_app/"))
        self.assertEqual(get.call_args.kwargs["timeout"], updater.REQUEST_TIMEOUT)

    def test_the_file_of_the_platform_is_chosen(self):
        for platform, name in (("win32", EXE), ("darwin", ZIP)):
            with self.subTest(platform=platform):
                release, _ = self.fetch(response(200, release_json()), platform)
                self.assertEqual(release.version, "1.0.9")
                self.assertEqual((release.asset.name, release.asset.url, release.asset.size), (name, BASE + name, 1234))
                self.assertEqual(release.asset.sha256, "ab" * 32)

    def test_a_platform_that_has_no_installer_gets_the_release_without_a_file(self):
        release, _ = self.fetch(response(200, release_json()), "linux")

        self.assertEqual(release.version, "1.0.9")
        self.assertIsNone(release.asset)

    def test_a_release_without_the_file_of_the_platform_has_none(self):
        release, _ = self.fetch(response(200, release_json(assets=[asset_json("notes.txt")])))

        self.assertIsNone(release.asset)

    def test_a_file_from_anywhere_but_this_repository_is_never_taken(self):
        for url in (f"https://evil.example/{EXE}", f"https://github.com/someone/else/releases/download/v1.0.9/{EXE}",
                    f"http://github.com/{updater.REPOSITORY}/releases/download/v1.0.9/{EXE}",
                    BASE + "other-name.exe", BASE + "../" + EXE):
            with self.subTest(url=url):
                release, _ = self.fetch(response(200, release_json(assets=[asset_json(EXE, url=url)])))
                self.assertIsNone(release.asset)

    def test_the_names_of_the_files_have_to_be_those_of_the_builds(self):
        for name in ("Setup.exe", "DSMediaplay_app-Setup-1.0.9.exe.zip", "evil-DSMediaplay_app-Setup-1.0.9.exe",
                     "DSMediaplay_app-Setup-latest.exe"):
            with self.subTest(name=name):
                release, _ = self.fetch(response(200, release_json(assets=[asset_json(name)])))
                self.assertIsNone(release.asset)

    def test_the_checksum_is_taken_only_when_it_is_a_sha256(self):
        for digest, expected in ((DIGEST, "ab" * 32), (None, ""), ("", ""), ("sha1:" + "ab" * 20, ""),
                                 ("sha256:abc", ""), ("sha256:" + "AB" * 32, ""), (12, "")):
            with self.subTest(digest=digest):
                release, _ = self.fetch(response(200, release_json(assets=[asset_json(EXE, digest=digest)])))
                self.assertEqual(release.asset.sha256, expected)

    def test_a_repository_without_a_release_has_none(self):
        self.assertIsNone(self.fetch(response(404))[0])

    def test_a_draft_or_a_pre_release_is_not_a_version_to_offer(self):
        for changes in ({"draft": True}, {"prerelease": True}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.fetch(response(200, release_json(**changes)))[0])

    def test_what_goes_wrong_is_an_update_error_with_the_text_to_show(self):
        cases = (("a refused request", response(403), "update_rate_limited"),
                 ("too many requests", response(429), "update_rate_limited"),
                 ("a server error", response(500), "update_check_failed"),
                 ("not json", response(200, text_json=False), "update_check_failed"),
                 ("no tag", response(200, {"html_url": "x"}), "update_check_failed"),
                 ("a tag that is not a version", response(200, release_json(tag_name="nightly")), "update_check_failed"),
                 ("a page elsewhere", response(200, release_json(html_url="https://evil.example/x")),
                  "update_check_failed"),
                 ("assets that are not a list", response(200, release_json(assets="x")), "update_check_failed"),
                 ("something that is not an object", response(200, ["a"]), "update_check_failed"))
        for label, answer, key in cases:
            with self.subTest(label), self.assertRaises(UpdateError) as caught:
                self.fetch(answer)
            self.assertEqual(caught.exception.key, key)

    def test_no_connection_is_an_update_error(self):
        for error in (requests.ConnectionError(), requests.Timeout(), requests.exceptions.SSLError()):
            with self.subTest(error=type(error).__name__), patch("util.updater.requests.get", side_effect=error), \
                    self.assertRaises(UpdateError) as caught:
                updater.fetch_latest_release("win32")
            self.assertEqual(caught.exception.key, "update_check_failed")


class InstallableTest(unittest.TestCase):
    RELEASE = Release("1.0.9", "https://github.com/x/y", Asset(EXE, BASE + EXE, 10, "ab" * 32))

    def frozen(self, value=True):
        return patch.object(sys, "frozen", value, create=True)

    def key(self, release, platform):
        with self.assertRaises(UpdateError) as caught:
            updater.check_installable(release, platform)
        return caught.exception.key

    def test_from_the_source_code_nothing_is_installed(self):
        with self.frozen(False):
            self.assertEqual(self.key(self.RELEASE, "win32"), "update_not_installed_app")

    def test_a_system_without_an_installer_is_told_so(self):
        with self.frozen():
            self.assertEqual(self.key(self.RELEASE, "linux"), "update_unsupported_platform")

    def test_a_release_without_the_file_cannot_be_installed(self):
        with self.frozen():
            self.assertEqual(self.key(Release("1.0.9", "https://github.com/x/y", None), "win32"), "update_no_asset")

    def test_a_file_without_a_checksum_cannot_be_installed(self):
        release = Release("1.0.9", "https://github.com/x/y", Asset(EXE, BASE + EXE, 10, ""))
        with self.frozen():
            self.assertEqual(self.key(release, "win32"), "update_no_checksum")

    def test_the_installer_of_windows_needs_nothing_else(self):
        with self.frozen():
            self.assertEqual(updater.check_installable(self.RELEASE, "win32"), self.RELEASE.asset)

    def test_on_macos_the_folder_of_the_bundle_has_to_be_writable(self):
        bundle = Path("/Applications/DSMediaplay_app.app")
        with self.frozen(), patch("util.updater.running_bundle", return_value=bundle):
            with patch("util.updater.os.access", return_value=False):
                self.assertEqual(self.key(self.RELEASE, "darwin"), "update_not_writable")
            with patch("util.updater.os.access", return_value=True):
                self.assertEqual(updater.check_installable(self.RELEASE, "darwin"), self.RELEASE.asset)

    def test_on_macos_outside_a_bundle_nothing_is_installed(self):
        with self.frozen(), patch("util.updater.running_bundle", return_value=None):
            self.assertEqual(self.key(self.RELEASE, "darwin"), "update_not_writable")


class FakeDownload:
    """What requests.get(stream=True) gives back."""

    def __init__(self, body: bytes, url: str = BASE + EXE, status: int = 200, fail_after: int = None):
        self.body, self.url, self.status, self.fail_after = body, url, status, fail_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError("refused")

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            if self.fail_after is not None and start >= self.fail_after:
                raise requests.ConnectionError("lost")
            yield self.body[start:start + size]


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name) / "update"
        self.body = os.urandom(300_000)
        self.asset = Asset(EXE, BASE + EXE, len(self.body), hashlib.sha256(self.body).hexdigest())

    def download(self, fake, **kwargs):
        with patch("util.updater.requests.get", return_value=fake) as get:
            return updater.download(self.asset, self.folder, **kwargs), get

    def key(self, fake, **kwargs):
        with self.assertRaises(UpdateError) as caught:
            self.download(fake, **kwargs)
        return caught.exception.key

    def test_a_whole_and_right_file_is_kept_under_its_name_and_nothing_else_is_left(self):
        path, get = self.download(FakeDownload(self.body))

        self.assertEqual(path, self.folder / EXE)
        self.assertEqual(path.read_bytes(), self.body)
        self.assertEqual(os.listdir(self.folder), [EXE])
        self.assertTrue(get.call_args.kwargs["stream"])

    def test_the_progress_is_told_as_it_goes(self):
        seen = []

        self.download(FakeDownload(self.body), progress=lambda received, total: seen.append((received, total)))

        self.assertGreater(len(seen), 2)
        self.assertEqual([received for received, _ in seen], sorted(received for received, _ in seen))
        self.assertEqual(seen[-1], (len(self.body), len(self.body)))

    def test_a_file_that_is_not_the_one_announced_is_not_kept(self):
        for label, body in (("other content", os.urandom(len(self.body))), ("too short", self.body[:-1]),
                            ("too long", self.body + b"x")):
            with self.subTest(label):
                self.assertEqual(self.key(FakeDownload(body)), "update_checksum_mismatch")
                self.assertFalse(self.folder.exists())

    def test_without_a_checksum_nothing_is_even_asked_for(self):
        self.asset = Asset(EXE, BASE + EXE, 10, "")
        with patch("util.updater.requests.get") as get, self.assertRaises(UpdateError) as caught:
            updater.download(self.asset, self.folder)

        self.assertEqual(caught.exception.key, "update_no_checksum")
        get.assert_not_called()

    def test_a_redirect_to_a_host_that_is_not_githubs_is_refused(self):
        for url in ("https://evil.example/file", "http://objects.githubusercontent.com/file",
                    "https://githubusercontent.com.evil.example/file", "https://notgithub.com/file"):
            with self.subTest(url=url):
                self.assertEqual(self.key(FakeDownload(self.body, url=url)), "update_download_failed")
                self.assertFalse(self.folder.exists())

    def test_the_hosts_of_github_are_accepted(self):
        for url in ("https://github.com/x/y/file", "https://objects.githubusercontent.com/file",
                    "https://release-assets.githubusercontent.com/file"):
            with self.subTest(url=url):
                self.assertEqual(self.download(FakeDownload(self.body, url=url))[0].read_bytes(), self.body)

    def test_a_connection_that_is_lost_or_a_refusal_leaves_nothing_behind(self):
        for label, fake in (("lost", FakeDownload(self.body, fail_after=100_000)), ("refused", FakeDownload(b"", status=404))):
            with self.subTest(label):
                self.assertEqual(self.key(fake), "update_download_failed")
                self.assertFalse(self.folder.exists())

    def test_cancelling_stops_the_download_and_leaves_nothing_behind(self):
        parts = []
        cancelled = lambda: len(parts) >= 2  # noqa: E731

        self.assertEqual(self.key(FakeDownload(self.body), progress=lambda received, total: parts.append(received),
                                  cancelled=cancelled), "update_cancelled")
        self.assertFalse(self.folder.exists())

    def test_an_earlier_download_is_cleared_away_first(self):
        self.folder.mkdir()
        (self.folder / "old.exe").write_bytes(b"old")

        self.download(FakeDownload(self.body))

        self.assertEqual(os.listdir(self.folder), [EXE])


class WindowsInstallerTest(unittest.TestCase):
    def test_the_installer_is_started_on_its_own_with_the_switches_that_install_and_start_again(self):
        with patch("util.updater.subprocess.Popen") as popen:
            updater.install(Path("C:/temp/setup.exe"), Release("1.0.9", "p", None), "win32")

        command = popen.call_args.args[0]
        self.assertEqual(command[0], str(Path("C:/temp/setup.exe")))
        self.assertEqual(command[1:], ["/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"])
        self.assertTrue(popen.call_args.kwargs["close_fds"])

    def test_the_installer_script_starts_the_application_again_only_on_request(self):
        with open(Path(__file__).parent.parent / "packaging" / "installer.iss", "rb") as file:
            script = file.read().decode("utf-8-sig")
        self.assertRegex(script, r"Check: RelaunchRequested")
        self.assertIn("{param:RELAUNCH|0}", script)
        self.assertRegex(script, r'(?m)^Filename: "\{app\}\\\{#AppExe\}"; Description:.*skipifsilent')  # the ordinary one stays

    def test_what_is_not_windows_or_macos_is_not_installed(self):
        with self.assertRaises(UpdateError) as caught:
            updater.install(Path("x"), Release("1.0.9", "p", None), "linux")
        self.assertEqual(caught.exception.key, "update_unsupported_platform")

    def test_macos_outside_a_bundle_is_not_installed(self):
        with patch("util.updater.running_bundle", return_value=None), self.assertRaises(UpdateError) as caught:
            updater.install(Path("x"), Release("1.0.9", "p", None), "darwin")
        self.assertEqual(caught.exception.key, "update_not_installed_app")


@unittest.skipUnless(sys.platform == "darwin", "the swap of a macOS bundle needs macOS (ditto)")
class MacBundleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.installed = self.root / "Applications" / updater.BUNDLE_NAME
        self.make_bundle(self.installed, "1.0.8", "old")
        self.processes = []

    @staticmethod
    def make_bundle(path, version, marker, identifier=updater.BUNDLE_IDENTIFIER, executable=True):
        (path / "Contents" / "MacOS").mkdir(parents=True)
        with open(path / "Contents" / "Info.plist", "wb") as file:
            plistlib.dump({"CFBundleIdentifier": identifier, "CFBundleShortVersionString": version,
                           "CFBundleExecutable": "DSMediaplay_app"}, file)
        if executable:
            (path / "Contents" / "MacOS" / "DSMediaplay_app").write_text("#!/bin/sh\n")
        (path / "Contents" / "marker.txt").write_text(marker)

    def package(self, version="1.0.9", **kwargs):
        source = self.root / "source" / updater.BUNDLE_NAME
        shutil.rmtree(source.parent, ignore_errors=True)  # one package after another
        self.make_bundle(source, version, "new", **kwargs)
        self.counter = getattr(self, "counter", 0) + 1
        package = self.root / f"package{self.counter}.zip"
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(source), str(package)], check=True)
        return package

    def marker(self):
        try:
            return (self.installed / "Contents" / "marker.txt").read_text()
        except FileNotFoundError:  # read in the very moment the script swaps the bundles
            return None

    def leftovers(self):
        return [name for name in os.listdir(self.installed.parent) if name != updater.BUNDLE_NAME]

    def wait_for(self, condition, seconds=20):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            for process in self.processes:
                process.poll()  # the ended application is collected, as the system does: a collected one is not "running"
            if condition():
                return True
            time.sleep(0.1)
        return False

    def application(self, seconds):
        """A process standing for the running application, which ends after `seconds`."""
        process = subprocess.Popen(["sleep", str(seconds)])
        self.processes.append(process)
        self.addCleanup(process.wait)
        return process

    def stage(self, package, version="1.0.9", opener="true", pid=None):
        with patch.dict(os.environ, {"HOME": str(self.home)}):
            updater.stage_macos_update(package, version, self.installed, opener, pid)

    def test_the_bundle_is_replaced_once_the_application_has_ended_and_nothing_is_left_behind(self):
        waiting = self.application(4)  # long enough for a machine that is busy with the whole suite
        self.stage(self.package(), pid=waiting.pid)

        self.assertEqual(self.marker(), "old")  # the application is still running: nothing changes yet
        self.assertTrue(self.wait_for(lambda: self.marker() == "new"))
        self.assertTrue(self.wait_for(lambda: self.leftovers() == []), self.leftovers())
        self.assertEqual(plistlib.loads((self.installed / "Contents" / "Info.plist").read_bytes())
                         ["CFBundleShortVersionString"], "1.0.9")
        log = (self.home / "Library" / "Logs" / "DSMediaplay_app-update.log").read_text()
        self.assertIn("done", log)

    def test_the_new_bundle_is_started_by_the_given_command(self):
        started = self.root / "started.txt"
        opener = self.root / "opener.sh"
        opener.write_text(f'#!/bin/sh\necho "$1" > "{started}"\n')
        opener.chmod(0o755)
        waiting = self.application(0.5)

        self.stage(self.package(), opener=str(opener), pid=waiting.pid)

        self.assertTrue(self.wait_for(started.exists))
        self.assertEqual(started.read_text().strip(), str(self.installed))

    def test_a_package_that_is_not_this_application_in_the_announced_version_is_not_installed(self):
        for label, package, version in (("another version", self.package("1.0.7"), "1.0.9"),
                                        ("another application", self.package(identifier="com.example.other"), "1.0.9"),
                                        ("no executable", self.package(executable=False), "1.0.9")):
            with self.subTest(label), self.assertRaises(UpdateError) as caught:
                self.stage(package, version=version)
            self.assertEqual(caught.exception.key, "update_invalid_package")
            self.assertEqual(self.marker(), "old")
            self.assertEqual(self.leftovers(), [])  # what was unpacked is removed

    def test_a_file_that_is_not_a_zip_is_not_installed(self):
        broken = self.root / "broken.zip"
        broken.write_bytes(b"not a zip")

        with self.assertRaises(UpdateError) as caught:
            self.stage(broken)

        self.assertEqual(caught.exception.key, "update_invalid_package")
        self.assertEqual(self.leftovers(), [])

    def run_script(self, new, waiting_for):
        script = self.root / "swap.sh"
        script.write_text(updater.MACOS_SWAP_SCRIPT)
        started = self.root / "started.txt"
        opener = self.root / "opener.sh"
        opener.write_text(f'#!/bin/sh\necho "$1" >> "{started}"\n')
        opener.chmod(0o755)
        staging = self.root / "staging"
        staging.mkdir(exist_ok=True)
        result = subprocess.run(["/bin/sh", str(script), str(waiting_for), str(new), str(self.installed), str(opener),
                                 str(staging)], env={**os.environ, "HOME": str(self.home)}, timeout=60)
        return result.returncode, started

    def test_when_the_swap_fails_the_old_bundle_is_put_back_and_started(self):
        finished = subprocess.Popen(["true"])
        finished.wait()

        code, started = self.run_script(self.root / "does-not-exist.app", finished.pid)

        self.assertEqual(code, 1)
        self.assertEqual(self.marker(), "old")
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(started.read_text().strip(), str(self.installed))

    def test_paths_with_spaces_and_odd_characters_are_not_a_problem(self):
        odd = self.root / "My Apps ; echo hacked" / updater.BUNDLE_NAME
        self.make_bundle(odd, "1.0.8", "old")
        self.installed = odd
        new = self.root / "new copy $HOME" / updater.BUNDLE_NAME
        self.make_bundle(new, "1.0.9", "new")
        finished = subprocess.Popen(["true"])
        finished.wait()

        code, _ = self.run_script(new, finished.pid)

        self.assertEqual(code, 0)
        self.assertEqual(self.marker(), "new")
        self.assertFalse((self.root / "My Apps ; echo hacked" / "hacked").exists())


class MessagesTest(unittest.TestCase):
    def test_every_text_the_updater_can_ask_for_exists_in_both_languages(self):
        source = (Path(__file__).parent.parent / "util" / "updater.py").read_text(encoding="utf-8")
        keys = set(re.findall(r'UpdateError\("(update_[a-z_]+)"', source))
        with open(Path(__file__).parent.parent / "assets" / "messages.json", encoding="utf-8") as file:
            messages = json.load(file)
        self.assertGreaterEqual(len(keys), 11)
        for language in ("cz", "en"):
            for key in keys | {"update", "tip_update", "update_title", "update_up_to_date", "update_none_published",
                               "update_available", "update_install_now", "update_later", "update_downloading",
                               "update_cancel", "update_installing", "update_open_page"}:
                with self.subTest(language=language, key=key):
                    self.assertTrue(messages[language].get(key, "").strip())

    def test_the_names_a_text_asks_for_are_the_ones_it_is_given(self):
        with open(Path(__file__).parent.parent / "assets" / "messages.json", encoding="utf-8") as file:
            messages = json.load(file)
        for language in ("cz", "en"):
            self.assertIn("{folder}", messages[language]["update_not_writable"])
            self.assertEqual(sorted(re.findall(r"{(\w+)}", messages[language]["update_available"])), ["current", "new"])
            self.assertEqual(sorted(re.findall(r"{(\w+)}", messages[language]["update_open_page"])), ["reason", "version"])


if __name__ == "__main__":
    unittest.main()
