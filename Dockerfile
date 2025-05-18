# This is the Dockerfile that builds an image form the current directory.
# It is provided as-is; the Bugsink team does not use this in their own
# development. Tips:

# * Configure your database/filestore/etc _outside_ of the current path
#     to avoid copying them into the image.

ARG PYTHON_VERSION=3.12

# Build image: non-slim, in particular to build the mysqlclient wheel
FROM python:${PYTHON_VERSION} AS build

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
RUN apt update && apt install default-libmysqlclient-dev -y

COPY --from=build /wheels /wheels

RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install --find-links /wheels --no-index mysqlclient

RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install "psycopg[binary]"

COPY requirements.txt /app/
RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install -r requirements.txt

COPY . /app/
COPY bugsink/conf_templates/docker.py.template bugsink_conf.py

# Git is needed by setuptools_scm to get the version from the git tag
RUN apt update && apt install -y git
RUN pip install -e .

RUN ["bugsink-manage", "migrate", "snappea", "--database=snappea"]

HEALTHCHECK CMD python -c 'import requests; requests.get("http://localhost:8000/health/ready").raise_for_status()'

CMD [ "monofy", "bugsink-manage", "check", "--deploy", "--fail-level", "WARNING", "&&", "bugsink-manage", "migrate", "&&", "bugsink-manage", "prestart", "&&", "gunicorn", "--config", "gunicorn.docker.conf.py", "--bind=0.0.0.0:$PORT", "--access-logfile", "-", "bugsink.wsgi", "|||", "bugsink-runsnappea"]
