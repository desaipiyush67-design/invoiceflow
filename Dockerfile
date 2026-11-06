FROM python:3.11-slim
WORKDIR /app
# OpenCV (used by the OCR engine) needs these system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY data data
COPY samples samples
ENV INVOICEFLOW_RUNTIME=/tmp/invoiceflow
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
