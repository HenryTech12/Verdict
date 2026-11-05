FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY app ./app
COPY seed.py ./
RUN pip install --no-cache-dir .
ENV DATABASE_URL=sqlite:////tmp/verdict.db PAYPAL_MODE=mock LLM_PROVIDER=mock
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
