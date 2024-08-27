ARG PYTHON_VERSION=3.12

# Build image: non-slim, in particular to build the mysqlclient wheel
FROM python:${PYTHON_VERSION} AS build

ARG WHEEL_FILE=wheelfile-not-specified.whoops

COPY dist/$WHEEL_FILE /wheels/
RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip wheel --wheel-dir /wheels /wheels/${WHEEL_FILE} mysqlclient


# Actual image (based on slim)
FROM python:${PYTHON_VERSION}-slim

# ARGs are not inherited from the build stage; https://stackoverflow.com/a/56748289/339144
ARG WHEEL_FILE

WORKDIR /app

# mysqlclient dependencies; needed here too, because the built wheel depends on .o files
RUN apt update && apt install default-libmysqlclient-dev -y

COPY --from=build /wheels /wheels
RUN --mount=type=cache,target=/var/cache/buildkit/pip \
    pip install --find-links /wheels --no-index /wheels/$WHEEL_FILE mysqlclient

COPY bugsink_conf.py .

EXPOSE 9000

CMD ["gunicorn", "--bind=0.0.0.0:9000", "--access-logfile", "-", "bugsink.wsgi"]