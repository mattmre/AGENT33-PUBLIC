ARG PYTHON_BASE_IMAGE=python:3.11.13-slim-trixie@sha256:9bffe4353b925a1656688797ebc68f9c525e79b1d377a764d232182a519eeec4

FROM ${PYTHON_BASE_IMAGE} AS builder

WORKDIR /build
COPY pyproject.toml hatch_build.py ./
ENV AGENT33_SKIP_FRONTEND_BUILD=1
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir --upgrade "setuptools>=80.9.0" "wheel>=0.46.2" && \
    pip install --no-cache-dir .

FROM ${PYTHON_BASE_IMAGE}

# The pinned upstream base can lag behind Debian security point releases.
# Refresh shipped OS packages at build time so Trivy gates reflect the current
# security repository state instead of a stale upstream image snapshot.
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r agent33 && useradd -r -g agent33 -d /app agent33
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
COPY agent-definitions/ agent-definitions/
COPY workflow-definitions/ workflow-definitions/
COPY tool-definitions/ tool-definitions/
COPY packs/ packs/
# The canonical workflow templates still live at repo-root `core/workflows`.
# Keeping the engine image build context scoped to `./engine` avoids a broader
# Docker build-policy change in this slice, so template catalog parity remains a
# documented follow-up rather than a silent omission.
COPY templates/ templates/
COPY pyproject.toml hatch_build.py ./

ENV AGENT33_SKIP_FRONTEND_BUILD=1
RUN pip install --no-cache-dir --upgrade "setuptools>=80.9.0" "wheel>=0.46.2" && \
    pip install --no-cache-dir -e .

RUN mkdir -p /app/var && chown -R agent33:agent33 /app

USER agent33
EXPOSE 8000

CMD ["uvicorn", "agent33.main:app", "--host", "0.0.0.0", "--port", "8000"]
