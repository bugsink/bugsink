# This is the Dockerfile that builds an image form the current directory.
# It is provided as-is; the Bugsink team does not use this in their own
# development. Tips:

# * Configure your database/filestore/etc _outside_ of the current path
#     to avoid copying them into the image.

ARG PYTHON_VERSION=3.12

# Build pdbparse with Python 3.11 (separate stage due to compatibility issues)
FROM python:3.11 AS pdbparse-builder

RUN apt-get update && apt-get install -y \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Build pdbparse wheel with Python 3.11 - install it first to get dependencies
RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install git+https://github.com/moyix/pdbparse.git@master

# Build image: non-slim, in particular to build wheels
FROM python:${PYTHON_VERSION} AS build

# Install build dependencies + git
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# mysqlclient is not available as a .whl on PyPI, so we need to build it from
# source and store the .whl. This is both the most expensive part of the build
# and the one that is least likely to change, so we do it first.
RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip wheel --wheel-dir /wheels mysqlclient

# Actual image (based on slim)
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONUNBUFFERED=1

ENV PORT=8000

WORKDIR /app

# mysqlclient dependencies; needed here too, because the built wheel depends on .o files
RUN apt update && apt install default-libmysqlclient-dev -y && rm -rf /var/lib/apt/lists/*

# Install git for setuptools_scm (needed later) and requirements.txt if needed
RUN apt update && apt install git -y && rm -rf /var/lib/apt/lists/*

# Copy wheels from build stage
COPY --from=build /wheels /wheels

# Copy pdbparse installation from Python 3.11 builder
COPY --from=pdbparse-builder /usr/local/lib/python3.11/site-packages /tmp/pdbparse-site-packages

RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install --find-links /wheels --no-index mysqlclient

# Install pdbparse by copying from Python 3.11 (pure Python, should be compatible)
RUN cp -r /tmp/pdbparse-site-packages/pdbparse* /usr/local/lib/python3.12/site-packages/ && \
    rm -rf /tmp/pdbparse-site-packages

RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install "psycopg[binary]"

COPY requirements.txt /app/
RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install -r requirements.txt

COPY . /app/
COPY bugsink/conf_templates/docker.py.template bugsink_conf.py

# Git is already installed above, install the package
RUN pip install -e .

RUN groupadd --gid 14237 bugsink \
 && useradd --uid 14237 --gid bugsink bugsink \
 && mkdir -p /data \
 && chown -R bugsink:bugsink /data

USER bugsink

RUN ["bugsink-manage", "migrate", "snappea", "--database=snappea"]

HEALTHCHECK CMD python -c 'import requests; requests.get("http://localhost:8000/health/ready").raise_for_status()'

CMD [ "monofy", "bugsink-show-version", "&&", "bugsink-manage", "check", "--deploy", "--fail-level", "WARNING", "&&", "bugsink-manage", "migrate", "&&", "bugsink-manage", "prestart", "&&", "gunicorn", "--config", "bugsink/gunicorn.docker.conf.py", "--bind=0.0.0.0:$PORT", "--access-logfile", "-", "bugsink.wsgi", "|||", "bugsink-runsnappea"]