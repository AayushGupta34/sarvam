# Backend image. Port comes from $PORT so it runs unchanged on Render, Railway, Fly or Hugging Face.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY edge-sensing/vision ./edge-sensing/vision
ENV PORT=8000 PYTHONPATH=/srv/backend:/srv/edge-sensing
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
