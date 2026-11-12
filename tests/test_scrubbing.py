"""lib/ecctools.py scrub_json and scrub_toml: what a snapshot drops and keeps.

Run from the repository root: python3 -m unittest discover -s tests
Fake secret values are assembled at runtime so this file passes the scan.
These tests pin current behavior; scrub_toml is stricter than scrub_json
(it drops authType and secret-named booleans), which is intended for now.
"""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "ecctools.py")

spec = importlib.util.spec_from_file_location("ecctools_under_test", LIB)
ecc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecc)

GH = "gh" + "p_" + "Q" * 24
PLAIN = "not-shaped-but-secret"


def scrub(data):
    removed = []
    return ecc.scrub_json(data, removed=removed), removed


class ScrubJson(unittest.TestCase):
    def test_nested_secret_keys(self):
        out, removed = scrub({"a": {"b": {"apiKey": PLAIN, "password": PLAIN, "name": "keep"}}})
        self.assertEqual(out, {"a": {"b": {"name": "keep"}}})
        self.assertEqual(removed, ["a.b.apiKey", "a.b.password"])

    def test_env_and_headers_blocks_lose_strings(self):
        out, removed = scrub({"servers": {"x": {
            "command": "npx", "env": {"FOO": "bar", "N": 3},
            "headers": {"X-Thing": "y"}}}})
        self.assertEqual(out, {"servers": {"x": {"command": "npx", "env": {"N": 3}, "headers": {}}}})
        self.assertEqual(removed, ["servers.x.env.FOO", "servers.x.headers.X-Thing"])

    def test_token_shapes_under_ordinary_keys_and_lists(self):
        out, removed = scrub({"note": GH, "items": ["ok", GH, {"url": GH, "k": 1}], "fine": "yes"})
        self.assertEqual(out, {"items": ["ok", {"k": 1}], "fine": "yes"})
        self.assertEqual(removed, ["note", "items[1]", "items[2].url"])

    def test_lists_under_secret_keys(self):
        out, removed = scrub({"tokens": ["a", 1, True], "servers": [{"token": PLAIN}]})
        self.assertEqual(out, {"tokens": [1, True], "servers": [{}]})
        self.assertEqual(removed, ["tokens[0]", "servers[0].token"])

    def test_safe_keys_keep_harmless_values(self):
        data = {"selectedType": "oauth-personal", "enforcedType": "x", "type": "stdio",
                "useExternal": "yes", "authType": "oauth-personal"}
        # Kept even inside a block whose key looks secret (Gemini's security.auth).
        out, removed = scrub({"security": {"auth": dict(data, token=PLAIN)}})
        self.assertEqual(out, {"security": {"auth": data}})
        self.assertEqual(removed, ["security.auth.token"])
        out, removed = scrub(data)
        self.assertEqual((out, removed), (data, []))

    def test_safe_keys_still_drop_token_shapes(self):
        out, removed = scrub({"authType": GH, "type": GH})
        self.assertEqual((out, removed), ({}, ["authType", "type"]))

    def test_booleans_and_null_survive_secret_keys(self):
        data = {"useAuth": True, "sessionPersist": False, "apiKey": None}
        out, removed = scrub(data)
        self.assertEqual((out, removed), (data, []))

    def test_numbers_under_secret_keys_are_removed(self):
        out, removed = scrub({"tokenLimit": 5, "count": 5})
        self.assertEqual((out, removed), ({"count": 5}, ["tokenLimit"]))


TOML = f'''model = "gpt-5"
api_key = "{PLAIN}"
authType = "oauth"
use_token = true

[mcp_servers.x]
command = "npx"
env = {{ FOO = "bar" }}

[mcp_servers.x.env]
FOO = "bar"

[http_headers]
"X-Thing" = "y"

[other]
url = "{GH}"
private_key = """
line one
line two
"""
args = [
  "{GH}",
]
keep = 1
'''

TOML_OUT = '''model = "gpt-5"

[mcp_servers.x]
command = "npx"

[mcp_servers.x.env]

[http_headers]

[other]
args = [
]
keep = 1
'''


class ScrubToml(unittest.TestCase):
    def test_pins_current_behavior(self):
        removed = []
        out = ecc.scrub_toml(TOML, removed)
        self.assertEqual(out, TOML_OUT)
        self.assertEqual(removed, [
            "api_key", "authType", "use_token",
            "mcp_servers.x.env",
            "mcp_servers.x.env.FOO",
            "http_headers.X-Thing",
            "other.url", "other.private_key",
            "other: line 12",
        ])
        self.assertNotIn(GH, out)
        self.assertNotIn(PLAIN, out)

    def test_ordinary_settings_unchanged(self):
        text = 'model = "o3"\n[profiles.fast]\nmodel_reasoning_effort = "low"\n'
        removed = []
        self.assertEqual(ecc.scrub_toml(text, removed), text)
        self.assertEqual(removed, [])

    def test_trailing_newline_follows_input(self):
        self.assertEqual(ecc.scrub_toml('a = 1', []), 'a = 1')


if __name__ == "__main__":
    unittest.main()
