FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Install the package
COPY omnia/ ./omnia/
RUN pip install --no-cache-dir -e .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Production endpoint — override with OMNIA_ENV=dev or OMNIA_API_URL for other envs
ENV OMNIA_ENV=prod
ENV OMNIA_API_TOKEN=""

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["omnia"]
