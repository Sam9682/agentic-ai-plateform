FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    sqlite3 \
    curl \
    git \
    openssh-client \
    docker.io \
    docker-compose \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Create ubuntu user and add to docker group
RUN useradd -m -s /bin/bash ubuntu && usermod -aG docker ubuntu

# Copy application code
COPY . .

# Create directory for database
RUN mkdir -p /app/data

# Change ownership to ubuntu user
RUN chown -R ubuntu:ubuntu /app

# Switch to ubuntu user
USER ubuntu

# Expose the internal HTTP port. The 12 external ports (6 HTTP + 6 HTTPS)
# are mapped to the container's internal 80/443 via docker-compose.
EXPOSE 80

# Set environment variables
ENV FLASK_APP=ControlPlanFlaskApp.py
ENV FLASK_ENV=production
ENV SECRET_KEY=change-this-in-production

# Create SSH setup script
RUN echo '#!/bin/bash\n\
eval "$(ssh-agent -s)"\n\
for key in /home/ubuntu/.ssh/OVH_SW_AUTOMORPH*; do\n\
  if [ -f "$key" ] && [[ "$key" != *.pub ]]; then\n\
    ssh-add "$key" 2>/dev/null || true\n\
  fi\n\
done\n\
exec "$@"' > /app/start.sh && chmod +x /app/start.sh

# Initialize database and start application
CMD ["/app/start.sh", "python3", "ControlPlanFlaskApp.py"]