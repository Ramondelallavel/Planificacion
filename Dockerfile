# Imagen única de HIDRAL-Plan: API REST + interfaz web compilada.
# El mismo contenedor, con otro comando, hace de trabajador de la cola de documentos.
#
#   docker build -t hidral-plan .
#
# Opcional detrás de un proxy corporativo con inspección TLS:
#   docker build --build-arg HTTPS_PROXY=http://proxy:3128 --secret id=ca,src=ca-proxy.crt -t hidral-plan .
ARG NODE_IMAGE=node:22-slim
ARG PYTHON_IMAGE=python:3.11-slim

# ---------------------------------------------------------------- interfaz web
FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- API + worker
FROM ${PYTHON_IMAGE}
# OCR (tesseract) solo se usa en páginas sin texto extraíble; INSTALAR_OCR=0 da una imagen más ligera.
ARG INSTALAR_OCR=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN if [ "$INSTALAR_OCR" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa && rm -rf /var/lib/apt/lists/*; \
    fi
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/hidral_plan ./hidral_plan
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    extras=postgres; if [ "$INSTALAR_OCR" = "1" ]; then extras="$extras,ocr"; fi; \
    pip install --no-cache-dir ".[$extras]"
COPY backend/config ./config
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --system --uid 10001 hidral && mkdir -p /datos && chown hidral /datos
USER hidral
# Sin HIDRAL_DB_URL se usa SQLite en el volumen /datos (instalación de un solo puesto).
ENV HIDRAL_DB_URL=sqlite:////datos/hidral.db \
    HIDRAL_ALMACEN_DIR=/datos/almacen \
    HIDRAL_FRONTEND_DIR=/app/frontend/dist
VOLUME ["/datos"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/salud', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "hidral_plan.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
