# Bugsink: Self-hosted Error Tracking

* [Error Tracking](https://www.bugsink.com/error-tracking/)
* [Built to self-host](https://www.bugsink.com/built-to-self-host/)
* [Sentry-SDK compatible](https://www.bugsink.com/connect-any-application/)
* [Scalable and reliable](https://www.bugsink.com/scalable-and-reliable/)

### Screenshot

![Screenshot](https://www.bugsink.com/static/images/JsonSchemaDefinitionException.5e02c1544273.png)


### Installation & docs

The **quickest way to evaluate Bugsink** is to spin up a throw-away instance using Docker:

```
docker pull bugsink/bugsink:latest

docker run \
  -e SECRET_KEY=PUT_AN_ACTUAL_RANDOM_SECRET_HERE_OF_AT_LEAST_50_CHARS \
  -e CREATE_SUPERUSER=admin:admin \
  -e PORT=8000 \
  -p 8000:8000 \
  bugsink/bugsink
```

Visit [http://localhost:8000/](http://localhost:8000/), where you'll see a login screen. The default username and password
are `admin`.

Now, you can [set up your first project](https://www.bugsink.com/docs/quickstart/) and start tracking errors.

[Detailed installation instructions](https://www.bugsink.com/docs/installation/) are on the Bugsink website.

[More information and documentation](https://www.bugsink.com/)
