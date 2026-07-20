# KYC Sentinel — testbed drivers. Everything here runs offline (fake mode).
# Live-Temporal usage: see README "Running live".

PY ?= python3
export KYC_FAKE_LLM ?= 1

.PHONY: test demo-all demo-f1 demo-f2 demo-f3 demo-f4 demo-f5 demo-f6 demo-f7 demo-f8 worker

test:
	$(PY) -m pytest test/ -q

demo-all:
	$(PY) demo.py all

demo-f%:
	$(PY) demo.py f$*

worker:
	KYC_FAKE_LLM=$(KYC_FAKE_LLM) $(PY) worker.py
