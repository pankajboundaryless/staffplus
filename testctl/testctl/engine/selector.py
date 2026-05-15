import fnmatch
import subprocess
from pathlib import Path
from typing import Optional

import yaml


class TestSelector:
    def __init__(self, config_path: Path):
        modules_file = config_path / "config" / "modules.yaml"
        with open(modules_file) as f:
            self.modules: dict = yaml.safe_load(f).get("modules", {})
        self.tests_path = config_path / "tests"

    def select(self, mode: str, modules: Optional[list[str]] = None) -> list[Path]:
        if mode == "full":
            return self._all_tests()
        if mode == "modules" and modules:
            return self._tests_for_modules(modules)
        if mode == "changed":
            return self._tests_for_modules(self._changed_modules())
        if mode == "impacted":
            return self._tests_for_modules(self._add_downstream(self._changed_modules()))
        return []

    def _all_tests(self) -> list[Path]:
        return sorted(self.tests_path.rglob("test_*.yaml"))

    def _tests_for_modules(self, names: list[str]) -> list[Path]:
        seen: set[Path] = set()
        tests: list[Path] = []
        for name in names:
            d = self.tests_path / name
            if d.exists():
                for p in sorted(d.rglob("test_*.yaml")):
                    if p not in seen:
                        seen.add(p)
                        tests.append(p)
        return tests

    def _changed_modules(self) -> list[str]:
        try:
            out = subprocess.check_output(
                ["git", "diff", "--name-only", "HEAD~1"],
                text=True, stderr=subprocess.DEVNULL,
            )
            changed_files = out.strip().splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return list(self.modules.keys())

        changed: set[str] = set()
        for mod_name, mod_cfg in self.modules.items():
            for pattern in mod_cfg.get("paths", []):
                if any(fnmatch.fnmatch(f, pattern) for f in changed_files):
                    changed.add(mod_name)
                    break
        return list(changed)

    def _add_downstream(self, names: list[str]) -> list[str]:
        result: set[str] = set(names)
        for name in names:
            result.update(self.modules.get(name, {}).get("downstream", []))
        return list(result)
