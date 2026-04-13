FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY omnia/ ./omnia/
RUN pip install --no-cache-dir -e .

ENV OMNIA_ENV=prod
ENV OMNIA_API_TOKEN=""

CMD ["omnia"]
