# KYC Sentinel worker image.
#
# Buildable from THIS repo alone (framework G6). It used to require building
# from the parent directory so it could `COPY AgenticFramework/runtime` —
# the runtime wasn't installable, so it had to be vendored in by hand:
#     docker build -f KYC_Sentinel/Dockerfile -t kyc-sentinel .   # old
#
# Now:
#     docker build -t kyc-sentinel .
#
# Pin the framework by ref in requirements.txt for reproducible builds; for
# local development against a live checkout, mount it and set AGENTSMITH_DIR
# (agents/_framework.py prefers an explicit AGENTSMITH_DIR over the installed
# copy, so your edits take effect without reinstalling):
#     docker run -v /path/to/AgenticFramework:/agentsmith \
#                -e AGENTSMITH_DIR=/agentsmith kyc-sentinel
FROM python:3.11-slim

WORKDIR /app

# Dependency layer first so source edits don't invalidate the pip cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "worker.py"]
