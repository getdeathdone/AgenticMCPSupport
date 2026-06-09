FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN python -m support_agent.db_setup

EXPOSE 8000

CMD ["uvicorn", "support_agent.web:app", "--host", "0.0.0.0", "--port", "8000"]
