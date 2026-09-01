"""
test/test_readme_commands_work.py — every `make` target README tells a reader to
run must actually have a recipe.

THE FAILURE THIS EXISTS FOR. README's Quick start has said `make demo-f4` since
the repo was published. The Makefile serves it with a `demo-f%` pattern rule —
and also named `demo-f1` … `demo-f8` in `.PHONY`. GNU make does not apply
implicit or pattern rules to a target declared .PHONY, so the .PHONY line
disabled the only rule that could build them. All eight scenario targets
printed

    make: Nothing to be done for `demo-f4'.

and exited **0**.

That exit code is the whole point of this test. A missing target is loud —
"No rule to make target" and a non-zero exit, which any reader or CI step would
catch. A phony target with no recipe is silent: success, no output, nothing
saying which of the two you got. The first thing a visitor to a public repo
copy-pastes did nothing, and said it had worked.

`make -n` is the check: it prints the recipe a target would run without running
it, so this stays fast and offline. What it cannot print, it cannot run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"

# `make <target>` inside a fenced block or inline code in the README.
MAKE_INVOCATION = re.compile(r"\bmake\s+([a-z0-9][a-z0-9-]*)\b")

# Targets a reader is told to run but which need credentials, a network or
# infrastructure. Their RECIPE must still resolve — that is what is checked —
# but nothing here executes them.
NO_EXECUTE = frozenset({"worker"})


def _readme_make_targets() -> set[str]:
    return set(MAKE_INVOCATION.findall(README.read_text(encoding="utf-8")))


def test_readme_actually_names_some_make_targets() -> None:
    """Guard the guard: if the README stops using `make`, or the regex drifts,
    every other test in this file passes over an empty set and proves nothing.
    """
    targets = _readme_make_targets()
    assert len(targets) >= 3, f"only found {targets} — has the README or the regex changed?"
    assert "demo-f4" in targets, "the Quick start's single-scenario example is gone"


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
@pytest.mark.parametrize("target", sorted(_readme_make_targets()))
def test_make_target_has_a_recipe(target: str) -> None:
    proc = subprocess.run(
        ["make", "-n", target],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = proc.stdout + proc.stderr

    assert "No rule to make target" not in combined, (
        f"README tells the reader to run `make {target}`, but the Makefile has "
        f"no such target."
    )
    # The silent one. Phrasing differs across make versions, so match on the
    # stable part rather than the whole sentence.
    assert "Nothing to be done" not in combined, (
        f"`make {target}` resolves to a target with NO RECIPE and exits 0 — it "
        f"does nothing and reports success. Usually a pattern rule ("
        f"`demo-f%:`) whose targets are also listed in .PHONY, which stops make "
        f"applying the rule."
    )
    assert proc.returncode == 0, f"`make -n {target}` failed:\n{combined}"
    assert combined.strip(), f"`make -n {target}` printed no recipe at all"


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_every_f_scenario_target_resolves() -> None:
    """The README's F-table promises F1–F8. The Quick start only demonstrates
    one of them, so the other seven are not covered by the test above."""
    broken = []
    for n in range(1, 9):
        proc = subprocess.run(
            ["make", "-n", f"demo-f{n}"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        out = proc.stdout + proc.stderr
        if "Nothing to be done" in out or "No rule to make target" in out:
            broken.append(f"demo-f{n}")
    assert not broken, f"scenario targets with no recipe: {', '.join(broken)}"
