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
	# Covers golden, fairness AND hallucination. Hallucination was outside this
	# loop for a while and its pins silently stopped matching the pipeline, so
	# the suite judged text the app no longer produced (DEVLOG 2026-08-09).
	# Without it, run-evals.py generates responses with the FRAMEWORK's generic
	# code-writing pipeline and judges those against KYC references — scoring
	# ~0 no matter how the agents behave. Re-run after any deliberate change to
	# agent behaviour and commit the diff.
	$(PY) scripts/pin_eval_outputs.py
