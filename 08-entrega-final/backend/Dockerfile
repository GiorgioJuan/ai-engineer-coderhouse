FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/backend
COPY backend/ ./
RUN pip install --no-cache-dir -c requirements.lock -r requirements.txt
COPY config/ /srv/config/
COPY demo/ /srv/demo/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
