FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# نسخ المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات البوت بالكامل
COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "main.py"]
