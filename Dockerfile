# Multi-stage build for minimal, secure Docker image
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim

# Security: Run as non-root user
RUN useradd -m -u 1000 czds && \
    mkdir -p /app /data /logs /zone_files && \
    chown -R czds:czds /app /data /logs /zone_files

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/czds/.local

# Copy application code
COPY --chown=czds:czds src/ /app/src/
COPY --chown=czds:czds setup.py /app/

# Install application
USER root
RUN pip install -e .
USER czds

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/home/czds/.local/bin:$PATH \
    DATABASE_PATH=/data/czds.db \
    LOG_FILE=/logs/czds_utils.log \
    ZONE_FILES_DIR=/zone_files

# Expose volumes for data persistence
VOLUME ["/data", "/logs", "/zone_files"]

# Default command (can be overridden)
ENTRYPOINT ["python", "-m", "czds_utils.cli"]
CMD ["--help"]
