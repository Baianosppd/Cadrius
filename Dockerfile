# Use uma imagem leve do Python compatível com seu projeto
FROM python:3.11-slim

# Otimizações do Python (logs imediatos e sem .pyc)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1


# Define pasta de trabalho dentro do container
WORKDIR /app

# Instala dependências do sistema para o Postgres (psycopg2)
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copia e instala dependências do Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código do projeto para dentro do container
COPY . /app/