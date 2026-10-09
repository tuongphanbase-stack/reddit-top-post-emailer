"""Run: python -m unittest discover tests

Offline checks that run on every push (see .github/workflows/tests.yml).
"""
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "reddit_top_post_emailer.py")
sys.path.insert(0, ROOT)


def setting_names():
    """Every environment variable the script reads."""
    with open(SCRIPT, encoding="utf-8") as f:
        src = f.read()
    return set(re.findall(r'environ(?:\.get)?[(\[]\s*"([A-Z0-9_]+)"', src)) | set(
        re.findall(r'_env\(\s*"([A-Z0-9_]+)"', src))


def load(env=None, unset=()):
    """Import the script as a fresh module, from a scratch working directory."""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env or {}):
        for name in unset:
            os.environ.pop(name, None)
        os.chdir(tmp)
        try:
            spec = importlib.util.spec_from_file_location("emailer_under_test", SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            os.chdir(cwd)


class Settings(unittest.TestCase):
    def test_loads_with_every_setting_empty(self):
        # The workflow passes an unset repository variable as an empty string;
        # float("") once crashed currency-rate-emailer on every run.
        names = setting_names()
        self.assertTrue(names)
        load({n: "" for n in names})

    def test_loads_with_no_settings(self):
        load(unset=setting_names())


class BlockedByReddit(unittest.TestCase):
    def run_generate(self, env):
        m = load(env, unset=["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"] if not env else ())
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env), \
                mock.patch.object(m, "fetch_top_posts", side_effect=RuntimeError("403 Blocked")), \
                mock.patch.object(m, "write_latest"):
            os.chdir(tmp)
            try:
                m.cmd_generate()
                with open(os.path.join(m.EMAIL_DIR, "meta.json"), encoding="utf-8") as f:
                    return f.read()
            finally:
                os.chdir(cwd)

    def test_without_credentials_the_run_is_skipped(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("REDDIT_CLIENT_ID", None)
            os.environ.pop("REDDIT_CLIENT_SECRET", None)
            self.assertIn('"total": 0', self.run_generate({}))

    def test_with_credentials_a_failure_is_real(self):
        with self.assertRaises(RuntimeError):
            self.run_generate({"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"})


if __name__ == "__main__":
    unittest.main()
