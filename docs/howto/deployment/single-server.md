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
* SSL certificates
* Snappea, a background process to handle longer-running tasks

Note that you will _not_ need to set up some of the "usual suspects" like a database server or a message broker. This is
by design: Bugsink uses SQLite (a serverless database) and Snappea (which is brokerless) for its background tasks.

This guide assumes Ubuntu 24.04 LTS as the operating system. Feel free to use another (Linux) system, though you may
need to substitute commands here and there.

This guide assumes you know your way around the command line and have (root) `ssh` access to a fresh system with the
single purpose of running Bugsink.

## Python, pip and venv

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
apt install python3 python3-pip python3-venv -y
```

## Set up a non-root user

It's a good practice to use a non-root user to run the Bugsink server. You can create a new user by running (as root):

```bash
adduser bugsink --disabled-password --gecos ""
```

You can then switch to the new user by running:

```bash
su - bugsink
```

You should now be in `/home/bugsink`. This is where we'll put Bugsink's codebase, the configuration for Bugsink and the
database.

## Set up a virtual environment and activate it

It's a good practice to use a virtual environment to manage your Python
dependencies. This way, you can avoid conflicts between different projects.

Run the following commands to create a virtual environment and activate it:

```bash
python3 -m venv venv
source venv/bin/activate
```

After running these commands, you should see the name of the virtual environment i.e. `(venv)` in your shell prompt.

## Install Bugsink and its dependencies

You can install Bugsink using `pip`:

```bash
python3 -m pip install Bugsink
```

You should see output indicating that Bugsink and its dependencies are being installed. After the installation is
complete, you can verify that Bugsink is installed by running:

```bash
bugsink-show-version
```


## Create configuration template

Bugsink relies on a configuration file to determine how it should run.

You can create a configuration file that's suitable for production by running the following command (replace `YOURHOST`
with the hostname of your server):

```bash
bugsink-create-conf --template=recommended --host=YOURHOST
```

This will create a file `bugsink_conf.py` in the current directory (which is, assuming you're following along, the
`bugsink` home directory). Open this file in your favorite editor.

```bash
nano bugsink_conf.py
```

The generated template matches the current guide, so in principle you will not need to change much. However, you'll
probably will need to check or adjust at least:

* `BASE_URL` to match the URL where you want to access Bugsink
* `SITE_NAME` to match the name of your site if you want to distinguish it from other Bugsink instances
* `DEFAULT_FROM_EMAIL` to match the email address from which Bugsink will send emails
* `EMAIL_HOST` and associated variables to match the SMTP server you want to use to send emails
* `TIME_ZONE` to match your timezone (if you want to see times in your local timezone rather than UTC)

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
123 static files copied to '/home/bugsink/venv/lib/python3.12/site-packages/collectedstatic/'
```


## Set up Gunicorn (managed by Systemd)

We will run Bugsink using Gunicorn, a WSGI server.

Gunicorn was already installed as part of the Bugsink dependencies, so we just need to run it.

Rather than running Gunicorn directly, [we will use a systemd service to manage the process](https://docs.gunicorn.org/en/latest/deploy.html#systemd).

Exit the `bugsink` user by running:

```bash
exit
```

This should bring you back to the root user.

Create 2 files:

`/etc/systemd/system/gunicorn.service` with the following contents:

```ini
[Unit]
Description=gunicorn daemon
Requires=gunicorn.socket
After=network.target

[Service]
Type=notify
User=bugsink
Group=bugsink

Environment="PYTHONUNBUFFERED=1"
RuntimeDirectory=gunicorn
WorkingDirectory=/home/bugsink
ExecStart=/home/bugsink/venv/bin/gunicorn --access-logfile - --capture-output --error-logfile - bugsink.wsgi
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/gunicorn.socket` with the following contents:

```
[Unit]
Description=gunicorn socket

[Socket]
ListenStream=/run/gunicorn.sock
SocketUser=www-data

[Install]
WantedBy=sockets.target
```

Enable and start the socket (enabling means it will also start on boot):

```bash
systemctl enable --now gunicorn.socket
```

Inspect the status of gunicorn using

```bash
systemctl status gunicorn.service
```

To test whether gunicorn actually listens on the socket, and whether everything can be reached, use:

```bash
sudo -u www-data curl --unix-socket /run/gunicorn.sock http:/static/js/issue_list.js
```

TODO NO SUCCESS YET! 404

TODO number of workers? as of yet unset?
at least document it

HIER GEBLEVEN:
    let's point a A-record to this server.


## Set up Nginx

Install nginx

```bash
apt install nginx
```

TODO iets met DNS



## Next steps

* Backups
* Upgrades.

