"""`run.py --self-test` is what the build checks start the application with: it has to say whether the window and the
credential store work, and nothing else."""
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import keyring
from keyring.backends import fail

import run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SelfTestTest(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter
            tkinter.Tk().destroy()
        except Exception:
            self.skipTest("no display available")

    def test_an_application_that_can_start_passes(self):
        self.assertEqual(run.self_test(), 0)

    def test_it_works_on_a_configuration_of_its_own_that_is_gone_afterwards(self):
        from unittest.mock import MagicMock
        from util.paths import default_logins_file
        used = []

        def build(config):
            used.append(config)
            self.assertTrue(os.path.exists(config))
            return MagicMock()

        with patch("run.DSMediaplayApp", side_effect=build):
            self.assertEqual(run.self_test(), 0)

        (config,) = used
        self.assertNotEqual(os.path.abspath(config), os.path.abspath(str(default_logins_file())))
        self.assertFalse(os.path.exists(config))
        with open(os.path.join(ROOT, "run.py"), encoding="utf-8") as file:
            self.assertIn('"lang": "cz"', file.read())  # a start with no language would ask for one and wait

    def test_a_missing_credential_store_fails_it_with_a_reason(self):
        keyring.set_keyring(fail.Keyring())

        with patch("sys.stderr") as stderr:
            result = run.self_test()

        self.assertEqual(result, 1)
        self.assertIn("credential store", "".join(call.args[0] for call in stderr.write.call_args_list))

    def test_a_window_that_cannot_be_built_fails_it(self):
        with patch("run.DSMediaplayApp", side_effect=RuntimeError("no Tk")):
            self.assertEqual(run.self_test(), 1)

    def test_the_program_started_with_the_switch_reports_by_its_exit_code(self):
        environment = {**os.environ, "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}  # not the real store
        result = subprocess.run([sys.executable, os.path.join(ROOT, "run.py"), "--self-test"], capture_output=True,
                                text=True, cwd=ROOT, timeout=120, env=environment)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Self-test passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
