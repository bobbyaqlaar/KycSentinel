# KYC Sentinel — testbed drivers. Everything here runs offline (fake mode).
# Live-Temporal usage: see README "Running live".

PY ?= python3
export KYC_FAKE_LLM ?= 1

.PHONY: test pin-evals demo-all demo-f1 demo-f2 demo-f3 demo-f4 demo-f5 demo-f6 demo-f7 demo-f8 worker

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
