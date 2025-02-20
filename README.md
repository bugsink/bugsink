# Bugsink: Self-hosted Error Tracking 

[Bugsink](https://www.bugsink.com/) offers real-time [error tracking](https://www.bugsink.com/error-tracking/) for your applications with full control
through self-hosting. 

* [Built to self-host](https://www.bugsink.com/built-to-self-host/)
* [Sentry-SDK compatible](https://www.bugsink.com/connect-any-application/)
* [Scalable and reliable](https://www.bugsink.com/scalable-and-reliable/)

### Screenshot

This is what you'll get:

![Screenshot](https://www.bugsink.com/static/images/JsonSchemaDefinitionException.5e02c1544273.png)


### Installation & docs

The **quickest way to evaluate Bugsink** is to spin up a throw-away instance using Docker:

```
docker pull bugsink/bugsink:latest

docker run \
  -e SECRET_KEY={{ random_secret }} \
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
