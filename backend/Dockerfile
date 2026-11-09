FROM python:3.12-slim

# Trivy — сканер уязвимостей для Jobber'а. Образ общий для backend и jobber
ARG TRIVY_VERSION=0.76.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates \
    && wget -qO- "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
       | tar xz -C /usr/local/bin trivy \
    && apt-get purge -y wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
