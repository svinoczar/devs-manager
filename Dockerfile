FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
	gcc \
	g++ \
	libpq-dev \
	postgresql-client \
	&& rm -rf /var/lib/apt/lists/*

COPY required.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r required.txt

COPY . .


CMD ["uvicorn", "src.api.main:app", "--reload"]
