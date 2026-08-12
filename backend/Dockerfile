FROM rust:1.88-slim-bookworm AS anydoc-builder

ARG ANYDOC_REF=82e23481480d5b54a4f4e0b3d99950f09108685c

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/rujirapongsn2/Anydoc-ocr.git /src/anydoc \
    && git -C /src/anydoc checkout "$ANYDOC_REF" \
    && python3 -m venv /opt/maturin \
    && /opt/maturin/bin/pip install --no-cache-dir maturin \
    && /opt/maturin/bin/maturin build --release --manifest-path /src/anydoc/python/Cargo.toml --out /wheels

FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    iputils-ping \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-tha \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app

COPY requirements.txt .
COPY --from=anydoc-builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R appuser:appuser /app

USER appuser

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4}"]
