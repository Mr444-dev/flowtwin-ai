from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowtwin import cli


class CliTests(unittest.TestCase):
    def test_serve_disables_access_logs_and_defaults_to_localhost(self) -> None:
        captured: dict[str, object] = {}
        fake_uvicorn = ModuleType("uvicorn")

        def fake_run(*args: object, **kwargs: object) -> None:
            captured["args"] = args
            captured.update(kwargs)

        fake_uvicorn.run = fake_run  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"uvicorn": fake_uvicorn}), patch.object(sys, "argv", ["flowtwin", "serve"]):
            cli.main()

        self.assertEqual(captured["host"], "127.0.0.1")
        self.assertEqual(captured["port"], 8000)
        self.assertFalse(captured["access_log"])


if __name__ == "__main__":
    unittest.main()
