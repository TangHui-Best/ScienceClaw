from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from rpa_agent.contracts.validators import find_architecture_violations


BACKEND = Path(__file__).parents[2]


def test_new_domain_has_no_legacy_or_compiler_boundary_imports() -> None:
    violations = find_architecture_violations(BACKEND / "rpa_agent")
    assert violations == []


def test_guard_detects_legacy_import() -> None:
    with TemporaryDirectory(dir=BACKEND) as directory:
        package = Path(directory) / "rpa_agent"
        package.mkdir()
        (package / "bad.py").write_text("from backend.rpa import manager\n", encoding="utf-8")

        assert find_architecture_violations(package) == [
            "bad.py:1: forbidden import 'backend.rpa'"
        ]


def test_guard_detects_compiler_creation_and_agent_dependencies() -> None:
    with TemporaryDirectory(dir=BACKEND) as directory:
        package = Path(directory) / "rpa_agent"
        compiler = package / "compiler"
        compiler.mkdir(parents=True)
        (compiler / "bad.py").write_text(
            "import browser_use\nfrom rpa_agent.contracts import TraceCandidate\nimport openai\n",
            encoding="utf-8",
        )

        assert find_architecture_violations(package) == [
            "compiler/bad.py:1: compiler forbidden import 'browser_use'",
            "compiler/bad.py:2: compiler forbidden symbol 'TraceCandidate'",
            "compiler/bad.py:3: compiler forbidden import 'openai'",
        ]


def test_guard_detects_all_legacy_import_spellings() -> None:
    with TemporaryDirectory(dir=BACKEND) as directory:
        package = Path(directory) / "rpa_agent"
        package.mkdir()
        (package / "bad.py").write_text(
            "import rpa\nfrom backend import rpa\nfrom backend.rpa.sub import value\n",
            encoding="utf-8",
        )
        assert len(find_architecture_violations(package)) == 3


def test_compiler_rejects_creation_module_and_relative_imports() -> None:
    with TemporaryDirectory(dir=BACKEND) as directory:
        package = Path(directory) / "rpa_agent"
        compiler = package / "compiler"
        compiler.mkdir(parents=True)
        (compiler / "bad.py").write_text(
            "import rpa_agent.creation\nfrom ..creation import session\n",
            encoding="utf-8",
        )
        assert len(find_architecture_violations(package)) == 2


def test_compiler_guard_is_third_party_fail_closed_and_blocks_aliases() -> None:
    with TemporaryDirectory(dir=BACKEND) as directory:
        package = Path(directory) / "rpa_agent"
        compiler = package / "compiler"
        compiler.mkdir(parents=True)
        (compiler / "bad.py").write_text(
            "import google.generativeai\n"
            "import mistralai\n"
            "import cohere\n"
            "import rpa_agent.contracts as contracts\n"
            "import rpa_agent.contracts.models as models\n"
            "from rpa_agent import creation\n",
            encoding="utf-8",
        )
        assert len(find_architecture_violations(package)) == 6


def test_compiler_guard_allows_only_stdlib_internal_and_published_contracts() -> None:
    with TemporaryDirectory(dir=BACKEND) as directory:
        package = Path(directory) / "rpa_agent"
        compiler = package / "compiler"
        compiler.mkdir(parents=True)
        (compiler / "good.py").write_text(
            "from __future__ import annotations\n"
            "import json\n"
            "from pathlib import Path\n"
            "from .plan import CompilePlan\n"
            "from rpa_agent.contracts import CoreTrace, CoreTraceTimeline, SkillDefinition, SkillManifest\n",
            encoding="utf-8",
        )
        assert find_architecture_violations(package) == []


def test_root_compiler_module_cannot_bypass_compiler_guard() -> None:
    with TemporaryDirectory(dir=BACKEND) as directory:
        package = Path(directory) / "rpa_agent"
        package.mkdir()
        (package / "compiler.py").write_text(
            "import browser_use\nfrom rpa_agent import creation\n",
            encoding="utf-8",
        )
        assert len(find_architecture_violations(package)) == 2
