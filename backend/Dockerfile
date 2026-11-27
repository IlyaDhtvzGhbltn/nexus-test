ARG BASE_IMAGE=registry.astralinux.ru/library/astra/ubi18:latest
ARG TRIVY_IMAGE=docker.io/aquasec/trivy:0.76.1

FROM ${TRIVY_IMAGE} AS trivy-dist

FROM ${BASE_IMAGE}

# Python 3.11
RUN command -v python3 >/dev/null 2>&1 || ( \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            python3 python3-pip python3-venv ca-certificates \
        && rm -rf /var/lib/apt/lists/* )

COPY --from=trivy-dist /usr/local/bin/trivy /usr/local/bin/trivy

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY app ./app

RUN useradd --system --uid 10001 --home /app appuser \
    && mkdir -p /trivy-cache \
    && chown appuser /trivy-cache
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
