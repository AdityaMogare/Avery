# --- Stage 1: build the React UI (Node is only needed at build time) ---
FROM node:22-alpine AS ui
WORKDIR /ui
COPY apps/insurance_claims/frontend/package.json apps/insurance_claims/frontend/package-lock.json ./
RUN npm ci
COPY apps/insurance_claims/frontend/ ./
RUN npm run build

# --- Stage 2: FastAPI runtime serving API + built UI ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/apps/insurance_claims/backend
COPY apps/insurance_claims/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/insurance_claims/fixtures /app/apps/insurance_claims/fixtures
COPY apps/insurance_claims/backend /app/apps/insurance_claims/backend
COPY --from=ui /ui/dist /app/apps/insurance_claims/frontend/dist
EXPOSE 8000
# Provide a model key at runtime: docker run -e OPENAI_API_KEY=... (or ANTHROPIC_API_KEY, GEMINI_API_KEY, ...; or paste it in the UI)
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
