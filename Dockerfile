# Imagem de runtime enxuta e sem root (CAD-066).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Só o necessário em runtime: psycopg2-binary dispensa gcc/libpq-dev; o postgresql-client
# fornece o pg_dump usado pelo comando de backup.
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# OCR opcional (CAD-163): documentos digitalizados. Desligado por padrão (aumenta a imagem e a superfície de CVEs); ligue com
# --build-arg WITH_OCR=1 (no servidor: WITH_OCR=1 no .env do ambiente e redeploy). Sem OCR, escaneados ficam "não processados" com o motivo.
ARG WITH_OCR=0
RUN if [ "$WITH_OCR" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por tesseract-ocr-eng poppler-utils \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# Dependências pinadas e com hash (supply chain): requirements.txt é gerado de requirements.in.
COPY requirements.txt /app/
RUN pip install --require-hashes -r requirements.txt

# Utilizador sem privilégios (uid 1000 casa com o utilizador típico do host nos bind mounts de dev).
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin app \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app

COPY --chown=app:app . /app/

USER app

EXPOSE 8000
