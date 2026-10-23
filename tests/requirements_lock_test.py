"""The build installs the lock files: every package at an exact version with its hash. They have to say what the
requirements say."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as file:
        return file.read()


def wanted(name):
    """The packages (and the files they include) that a requirements file names, with the version it asks for."""
    result = {}
    for line in read(name).splitlines():
        line = line.split("#")[0].strip()
        if line.startswith("-r "):
            result.update(wanted(line[3:].strip()))
        elif line:
            package, operator, version = re.match(r"([A-Za-z0-9_.-]+)\s*(?:([=~<>!]+)\s*(.*))?$", line).groups()
            result[package.lower().replace("_", "-")] = version if operator == "==" else None  # only an exact pin
    return result


def locked(name):
    """{package: (version, number of hashes)} of a lock file."""
    packages = {}
    for block in re.split(r"\n(?=[A-Za-z0-9_.-]+==)", read(name)):
        found = re.match(r"([A-Za-z0-9_.-]+)==([^\s;\\]+)", block)
        if found:
            packages[found.group(1).lower().replace("_", "-")] = (found.group(2), block.count("--hash=sha256:"))
    return packages


class LockTest(unittest.TestCase):
    def test_every_package_has_an_exact_version_and_at_least_one_hash(self):
        for name in ("requirements-build.lock", "requirements-dev.lock"):
            packages = locked(name)
            self.assertGreater(len(packages), 10, name)
            for package, (version, hashes) in packages.items():
                with self.subTest(lock=name, package=package):
                    self.assertGreater(hashes, 0)
                    self.assertRegex(version, r"^\d")

    def test_what_the_requirements_name_is_in_the_lock_at_the_version_they_ask_for(self):
        for source, lock in (("requirements-build.txt", "requirements-build.lock"),
                             ("requirements-dev.txt", "requirements-dev.lock")):
            packages = locked(lock)
            for package, version in wanted(source).items():
                with self.subTest(lock=lock, package=package):
                    self.assertIn(package, packages)
                    if version:  # an exact pin: the lock has that version
                        self.assertEqual(packages[package][0], version)

    def test_the_workflow_installs_only_from_the_locks(self):
        workflow = read(".github/workflows/build.yml")

        self.assertNotRegex(workflow, r"pip install -r requirements")
        self.assertEqual(workflow.count("--require-hashes"), 2)
        self.assertIn("pip_audit -r requirements-build.lock", workflow)


if __name__ == "__main__":
    unittest.main()
