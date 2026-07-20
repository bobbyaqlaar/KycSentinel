# KYC Sentinel worker image. The framework runtime is vendored in at build
# time (build from the directory that contains BOTH checkouts):
#   docker build -f KYC_Sentinel/Dockerfile -t kyc-sentinel .
FROM python:3.11-slim

WORKDIR /app
COPY AgenticFramework/runtime /agentsmith/runtime
COPY KYC_Sentinel/ /app/

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r /agentsmith/runtime/requirements-runtime.txt

ENV AGENTSMITH_DIR=/agentsmith
CMD ["python3", "worker.py"]
