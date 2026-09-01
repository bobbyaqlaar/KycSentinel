# KYC Sentinel — testbed drivers. Everything here runs offline (fake mode).
# Live-Temporal usage: see README "Running live".

PY ?= python3
export KYC_FAKE_LLM ?= 1

# demo-f1..demo-f8 are deliberately NOT listed here. They are served by the
# `demo-f%` pattern rule below, and GNU make does not apply implicit or pattern
# rules to a target declared .PHONY — so naming them here disabled the only rule
# that could build them. `make demo-f4`, which README's Quick start tells a
# first-time visitor to run, then printed
#
#     make: Nothing to be done for `demo-f4'.
#
# and exited 0. Not an error, no scenario, success. The worst of the three
# outcomes: a reader checking out a public repo saw a green exit and no output
# and had nothing to tell them which it was.
#
# There is no file named demo-f4 for the pattern rule to be confused by, so
# leaving them off .PHONY costs nothing here.
.PHONY: test pin-evals demo-all worker

test:
	$(PY) -m pytest test/ -q

demo-all:
	$(PY) demo.py all

demo-f%:
	$(PY) demo.py f$*

worker:
	KYC_FAKE_LLM=$(KYC_FAKE_LLM) $(PY) worker.py

pin-evals:
	# Record what this app currently produces as each eval case's actual_output.
	#
	# Covers golden, fairness AND hallucination — but NOT all with the same
	# projection of the Decision. Golden and fairness pin the reviewer-facing
	# render; hallucination pins the rationale alone, because that suite asks
	# whether every claim is grounded in the retrieved set its case declares.
	# Pinning the full render there cited policies those cases never retrieved
	# and drove the hallucination rate from 0.000 to 1.000 on a codebase that
	# had not regressed (DEVLOG 2026-08-12). If you add a suite, decide which
	# projection it judges before adding it to the loop.
	# Without it, run-evals.py generates responses with the FRAMEWORK's generic
	# code-writing pipeline and judges those against KYC references — scoring
	# ~0 no matter how the agents behave. Re-run after any deliberate change to
	# agent behaviour and commit the diff.
	$(PY) scripts/pin_eval_outputs.py
