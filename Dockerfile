FROM python:3.11-slim

# Install system dependencies for Tesseract
RUN apt-get update && apt-get install -y \
    git \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Migrations run at startup, so they have to ship with the image
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini

# The sibling worker container runs this image with `python worker.py`
COPY worker.py ./worker.py

# Expose port
EXPOSE 7031

# Run the application. Migrations first, matching every other DB-backed
# service; alembic also provisions the database if it does not exist yet.
CMD ["bash", "-c", "alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 7031"]

