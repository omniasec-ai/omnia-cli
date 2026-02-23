FROM mcr.microsoft.com/devcontainers/python:3.12
COPY requirements.txt .
RUN pip install -r requirements.txt
