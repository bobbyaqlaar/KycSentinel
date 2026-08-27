"""
test/test_pin_satisfies_the_code.py — this repo must be able to run against the
framework version it pins.

THE FAILURE THIS EXISTS FOR. On 2026-08-25 this repo's `requirements.txt`
pinned `agentsmith-runtime@v1.2.0` while `worker.py` imported
`runtime.config` and `pipeline.py` imported `runtime.tenancy` — neither of
which exists at that tag. A `docker build`, or a Cloud Run `--source` deploy,
would have failed at worker startup. Both artifacts are owned by this repo, so
no framework change caused it and no framework change could fix it.

CI did not catch it because `ci.yml` installs the framework from the checked-out
path (`pip install -e "$AGENTSMITH_DIR"`), which is deliberate — PRs should test
against the framework's HEAD. The cost is that CI validates a version this repo
does not run, and `requirements.txt` says in its own comment that its line is
what a standalone build resolves. So the one thing CI proved was the one thing
that was not in question.

The pin exists to insulate the business's cadence from IT's. It can only do that
if it describes what the business actually built.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_PIN = re.compile(r"agentsmith-runtime\[[^\]]*\]\s*@\s*git\+\S+@(v\d+\.\d+\.\d+)")


def _pinned_tag() -> str:
    text = (REPO / "requirements.txt").read_text(encoding="utf-8")
    m = _PIN.search(text)
    assert m, "requirements.txt has no agentsmith-runtime git pin to check"
    return m.group(1)


def _framework_checkout() -> Path | None:
    """A framework checkout that has the tags. `AGENTSMITH_DIR` in CI, the
    sibling directory locally."""
    import os

    for candidate in (os.environ.get("AGENTSMITH_DIR", ""), str(REPO.parent / "AgenticFramework")):
        if candidate and (Path(candidate) / "runtime").is_dir():
            return Path(candidate)
    return None


def _runtime_imports() -> dict[str, set[str]]:
    """`from runtime.X import a, b` across this repo → {X: {a, b}}."""
    found: dict[str, set[str]] = {}
    for py in REPO.rglob("*.py"):
        if "__pycache__" in py.parts or ".venv" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("runtime."):
                mod = node.module.split(".", 1)[1]
                found.setdefault(mod, set()).update(a.name for a in node.names)
    return found



def _module_level_names(source: str) -> set[str]:
    """Names a module exports, from the TAG's source — parsed, not grepped.

    Walks `if`/`try` bodies as well as the module body, because the framework
    guards Temporal-dependent definitions behind `if _HAS_TEMPORAL:` and
    `dlq_enqueue_activity` lives in there. A column-anchored regex missed both
    of those and reported them absent from a tag that has them — the same
    read-the-AST-not-the-text lesson the framework's own orphan sweep is built
    around.

    Class METHODS are deliberately not collected: they are not importable
    module attributes, and counting them would turn a real miss into a pass.
    """
    names: set[str] = set()

    def walk(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.If):
                walk(node.body)
                walk(node.orelse)
            elif isinstance(node, ast.Try):
                walk(node.body)
                walk(node.orelse)
                for handler in node.handlers:
                    walk(handler.body)
    try:
        walk(ast.parse(source).body)
    except SyntaxError:
        pass
    return names


def test_the_sweep_finds_this_repos_framework_imports() -> None:
    """A sweep that matches nothing passes for the wrong reason."""
    imports = _runtime_imports()
    assert len(imports) >= 8, f"expected this repo to import many runtime modules, got {imports}"


def test_every_framework_module_this_repo_imports_exists_at_the_pinned_tag() -> None:
    fw = _framework_checkout()
    if fw is None:
        pytest.skip("no AgentSmith checkout with tags (set AGENTSMITH_DIR)")
    tag = _pinned_tag()

    if subprocess.run(["git", "rev-parse", "--verify", tag], cwd=fw,
                      capture_output=True).returncode != 0:
        pytest.skip(f"{tag} is not present in the framework checkout (shallow clone?)")

    missing: list[str] = []
    for mod, names in sorted(_runtime_imports().items()):
        # `runtime.workflows.base_workflow` is a PATH, not a filename — the
        # first version of this built `runtime/workflows.base_workflow.py` and
        # reported the module missing at every tag, including ones that have it.
        path = f"runtime/{mod.replace('.', '/')}.py"
        blob = subprocess.run(
            ["git", "show", f"{tag}:{path}"], cwd=fw, capture_output=True, text=True
        )
        if blob.returncode != 0:
            missing.append(f"{path} (whole module)")
            continue
        exported = _module_level_names(blob.stdout)
        for name in sorted(names):
            if name not in exported:
                missing.append(f"runtime.{mod}.{name}")

    assert not missing, (
        f"this repo pins agentsmith-runtime@{tag} but imports things that tag "
        f"does not have — a docker build or Cloud Run --source deploy fails at "
        f"startup, while CI passes because it installs the framework from "
        f"$AGENTSMITH_DIR instead of the pin:\n  " + "\n  ".join(missing)
    )


def test_the_declared_framework_version_matches_the_pin() -> None:
    """`framework.version` in tenant.yaml and the requirements pin are the same
    fact written twice. They drifted once already."""
    import yaml

    declared = str(
        yaml.safe_load((REPO / ".agenticframework" / "tenant.yaml").read_text(encoding="utf-8"))
        ["framework"]["version"]
    )
    tag = _pinned_tag().lstrip("v")
    major_minor = ".".join(tag.split(".")[:2])
    assert declared in (tag, f"{major_minor}.x"), (
        f"tenant.yaml declares framework.version={declared!r} while "
        f"requirements.txt pins {tag}"
    )
