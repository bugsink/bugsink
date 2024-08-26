# Purpose: Dockerfile for the Bugsink project
# Ubuntu 24.04 rather than the Python image: I want to stick as closely to the "recommended" (single server) deployment
# as possible
FROM ubuntu:24.04
WORKDIR /app

COPY requirements.txt .

RUN apt update
RUN apt install python3 python3-pip python3-venv -y

# mysqlclient dependencies
RUN apt install default-libmysqlclient-dev pkg-config -y

# Venv inside Docker? I'd say yes because [1] PEP 668 and [2] harmonization with "recommended" (single server) deployment
RUN python3 -m venv venv
RUN venv/bin/python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9000

CMD ["venv/bin/gunicorn", "--bind=0.0.0.0:9000", "--access-logfile", "-", "bugsink.wsgi"]
