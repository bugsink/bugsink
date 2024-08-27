ARG PYTHON_VERSION=3.12

# Build image: non-slim, in particular to build the mysqlclient wheel
FROM python:${PYTHON_VERSION} AS build

COPY ./requirements.txt .
RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip wheel --wheel-dir /wheels -r requirements.txt


# Actual image (based on slim)
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

# mysqlclient dependencies; needed here too, because the built wheel depends on .o files
RUN apt update && apt install default-libmysqlclient-dev -y

COPY requirements.txt ./
COPY --from=build /wheels /wheels
RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install --find-links /wheels --no-index -r requirements.txt

COPY . .

EXPOSE 9000

CMD ["gunicorn", "--bind=0.0.0.0:9000", "--access-logfile", "-", "bugsink.wsgi"]
