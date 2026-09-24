import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ava_agent_training.dataset import DatasetValidationError, granite_messages, load_jsonl, validate_example, validate_splits


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_dataset.py")], check=True)
        cls.train = load_jsonl(ROOT / "datasets" / "train.jsonl")
        cls.validation = load_jsonl(ROOT / "datasets" / "validation.jsonl")

    def test_split_and_holdout_separation(self):
        self.assertGreaterEqual(len(self.train), 20)
        self.assertGreaterEqual(len(self.validation), 5)
        validate_splits(self.train, self.validation)

    def test_native_tool_schema_and_template_messages(self):
        messages = granite_messages(self.train[0])
        self.assertEqual(messages[0]["role"], "system")
        terminal = next(call for message in self.train[0]["messages"] for call in message.get("tool_calls", []) if call["name"] == "ava_terminal")
        self.assertEqual(terminal["arguments"]["executable"], "python")
        self.assertEqual(terminal["arguments"]["arguments"][:2], ["-m", "unittest"])

    def test_rejects_pseudo_call_unknown_tool_and_missing_result(self):
        for mutate in ("pseudo", "unknown", "missing"):
            item = json.loads(json.dumps(self.train[0]))
            if mutate == "pseudo":
                item["messages"][2]["pseudo_tool_call"] = '{"name":"ava_terminal"}'
            elif mutate == "unknown":
                item["messages"][2]["tool_calls"][0]["name"] = "bash"
            else:
                item["messages"] = item["messages"][:-2] + [item["messages"][-1]]
            with self.assertRaises(DatasetValidationError):
                validate_example(item)

    def test_rejects_false_success_and_malformed_terminal(self):
        item = json.loads(json.dumps(self.train[0]))
        call = next(call for message in item["messages"] for call in message.get("tool_calls", []) if call["name"] == "ava_terminal")
        call["arguments"]["executable"] = "python -m unittest"
        with self.assertRaises(DatasetValidationError):
            validate_example(item)
        item = json.loads(json.dumps(self.train[0]))
        for message in item["messages"]:
            if message.get("name") == "ava_terminal":
                message["verified_tests_passed"] = False
        with self.assertRaises(DatasetValidationError):
            validate_example(item)


if __name__ == "__main__":
    unittest.main()
