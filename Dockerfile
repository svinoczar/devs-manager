FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
	gcc \
	g++ \
	libpq-dev \
	postgresql-client \
	netcat-openbsd \
	&& rm -rf /var/lib/apt/lists/*

COPY required.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r required.txt

COPY . .

# Сделай entrypoint исполняемым
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]