"""Verify the shared execution boundary without a paid model request."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from execution import ProviderError, run_json
from execution.providers import codex


class CodexExecution(unittest.TestCase):
    @patch.object(codex, "detect", return_value="/test/codex")
    @patch.object(codex, "codex_environment", return_value={})
    def test_provider_enforces_read_only_and_loads_structured_output(self, _env, _detect):
        schema = {"type": "object"}

        def invoke(command, **kwargs):
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertEqual(command[command.index("--disable") + 1], "shell_tool")
            self.assertIn('web_search="disabled"', command)
            self.assertEqual(kwargs["timeout"], 120)
            schema_file = Path(command[command.index("--output-schema") + 1])
            self.assertEqual(json.loads(schema_file.read_text()), schema)
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text('{"decision": "continue"}')
            return subprocess.CompletedProcess(command, 0, stderr="")

        with patch.object(codex.subprocess, "run", side_effect=invoke):
            self.assertEqual(run_json("codex", "研究目标", schema, timeout=120),
                             {"decision": "continue"})

    def test_detect_only_provider_cannot_execute(self):
        with self.assertRaises(ProviderError):
            run_json("claude", "研究目标", {})
