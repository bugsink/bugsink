# How to Deploy Bugsink for production on a single-server

The recommended way to deploy Bugsink is on a single (possibly virtualized) server.

This minimizes complexity and increases robustness and performance.
It also scales well: A single cheap (e.g. 2GiB RAM, 1 vCPU, XXX disk) server can easily handle up to TODO events per
month, and if you need more than that scaling up the starting point provides ample room for scaling up (bigger
hardware).

The components you'll set up are:

* Python
* Bugsink and its dependencies (including Gunicorn)
* A reverse proxy (Nginx) to handle incoming HTTP requests
* Snappea, a background process to handle longer-running tasks

Note that you will _not_ need to set up some of the "usual suspects" like a database server or a message broker. This is
by design: Bugsink uses SQLite (a serverless database) and Snappea (which is brokerless) for its background tasks.

This guide assumes Ubuntu 24.04 LTS as the operating system. Feel free to use another (Linux) system, though you may
need to substitute commands here and there.

This guide assumes you know your way around the command line and have (root) `ssh` access to a fresh system with the
single purpose of running Bugsink.

## Python & pip

You can verify that Python and Pip are installed by running the following commands:

```bash
python3 --version
```

and

```bash
pip3 --version
```

If either is not, install with

```bash
apt update
apt upgrade
apt install python3 python3-pip
```


## Install Bugsink and its dependencies

We install Bugsink and its dependencies straight into the system Python. (On a server that's used for more than Bugsink
alone, you will likely want to use a virtual environment to avoid conflicts between different projects)

```
python3 -m pip install bugsink
```

This will install Bugsink and its dependencies. After the installation is complete, you can verify that Bugsink is
installed by running:

```bash
bugsink-show-version
```

## Set up a non-root user

It's a good practice to use a non-root user to run the Bugsink server. You can create a new user by running (as root):

```bash
adduser bugsink
```

You can then switch to the new user by running:

```bash
su - bugsink
```

You should now be in `/home/bugsink`. This is where we'll put both the configuration for Bugsink and the database.

## Create configuration template

Bugsink relies on a configuration file to determine how it should run.

You can create a configuration file that's suitable for production by running:

```bash
bugsink-create-conf --template=default
```

This will create a file `bugsink_conf.py` in the current directory (which is, assuming you're following along, the
`bugsink` home directory). Open this file in your favorite editor.

```bash
nano bugsink_conf.py
```

The generated template matches the current guide, so in principle you will not need to change much. However, you'll
probably will need to adjust at least:

* `BASE_URL` to match the URL where you want to access Bugsink
* `SITE_NAME` to match the name of your site if you want to distinguish it from other Bugsink instances
* `DEFAULT_FROM_EMAIL` to match the email address from which Bugsink will send emails
* `EMAIL_HOST` and associated variables to match the SMTP server you want to use to send emails
* `TIME_ZONE` to match your timezone (if you want to see times in your local timezone rather than UTC)

TODO should there not be another template then? "recommended"
TODO should contain `STATIC_ROOT` too


## Initialize the database

Bugsink uses a database to store the data it collects.

You can initialize the database by running:

```bash
bugsink-manage migrate
```

This will create a new SQLite database in the location specified in the configuration file (by default: `/home/bugsink`)
and set up the necessary tables. You may verify the presence of the database by running

```bash
ls db.sqlite3
```

## Create a superuser

You can create a superuser account to access the Bugsink admin interface.

Run the following command and follow the prompts:

```bash
bugsink-manage createsuperuser
```

This will create a new user account with administrative privileges.

## Collect static files

Bugsink uses static files for its web interface.

You can collect the static files by running:

```bash
bugsink-manage collectstatic --noinput
```

You should see something like

```
123 static files copied to '/home/bugsink/collectedstatic/'
```


## Set up Gunicorn

We will run Bugsink using Gunicorn, a WSGI server. Rather than running Gunicorn directly, we will use a systemd service
to manage the process.

Exit the `bugsink` user by running:

```bash
exit
```

This should bring you back to the root user.

Create a new file `/etc/systemd/system/bugsink.service` with the following contents:

```ini
ACTUALLY READ THIS FROM TFM PLEASE






```



```bash
PYTHONUNBUFFERED=1 gunicorn --bind="127.0.0.1:9000" --access-logfile - --capture-output --error-logfile - bugsink.wsgi
```

You should see output indicating that the server is running. You can now access Bugsink by visiting
http://127.0.0.1:9000/ in your web browser.



## Next steps

* Backups
* Upgrades.

