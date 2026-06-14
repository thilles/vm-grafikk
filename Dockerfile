FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Kunnskapsgrafen (RDF/Turtle) som «Utforsk grafen» spør mot. Bare den ferdige
# .ttl-en trengs i runtime; resten av wc2026-kg/ (byggeskript) holdes utenfor.
COPY wc2026-kg/wc2026.ttl ./wc2026-kg/wc2026.ttl
# Render & co. har ikke volumer på gratisplanen – ta med data/ (fasit.json m.m.)
# i imaget. Lokalt monteres ./data over denne uansett.
COPY data /data

EXPOSE 8000

# Skyplattformer (Render, Cloud Run, …) setter PORT; lokalt brukes 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
