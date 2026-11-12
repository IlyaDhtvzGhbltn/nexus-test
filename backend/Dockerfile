# Базовый образ Astra Linux.
# Образ общий для backend и jobber: различаются командой запуска в docker-compose
FROM registry.astralinux.ru/library/astra/ubi18:latest

# Python 3.11 из репозиториев Астры + Trivy (сканер уязвимостей для Jobber'а)
ARG TRIVY_VERSION=0.76.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv wget ca-certificates \
    && wget -qO- "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
       | tar xz -C /usr/local/bin trivy \
    && apt-get purge -y wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Зависимости — в venv (системный Python в Astra 1.8 защищён от прямого pip, PEP 668)
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
