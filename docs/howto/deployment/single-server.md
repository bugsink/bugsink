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

This guide assumes the following knowledge and starting position:

* you know your way around the command line and have (root) `ssh` access to a fresh system with the single purpose of
  running Bugsink.
* an A-record for your hostname is set up to point to the IP address of your server.

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
python3 -m pip install Bugsink --upgrade
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

Bugsink uses a database to store the data it collects. When set up with Snappea, it also uses a database as a message
queue.

You can initialize both these databases by running:

```bash
bugsink-manage migrate
bugsink-manage migrate snappea --database=snappea
```

This will create 2 new SQLite database in the location specified in the configuration file (by default: `/home/bugsink`)
and set up the necessary tables. You may verify the presence of the database by running:

```bash
ls *.sqlite3
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
ExecStart=/home/bugsink/venv/bin/gunicorn --workers=5 --access-logfile - --capture-output --error-logfile - bugsink.wsgi
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

(In the example above we have set the number of workers to 5; a good starting point for this value in general is the
number of CPU cores on your server * 2 + 1, as per the [Gunicorn
documentation](https://docs.gunicorn.org/en/latest/design.html#how-many-workers))

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
sudo -u www-data curl --unix-socket /run/gunicorn.sock http
```

(if no error is displayed, everything is set up correctly)


## Set up Nginx to run on port 80

We will first set up Nginx to run on port 80; when this is running correctly, we can use certbot to set up SSL
automatically.

Install nginx:

```bash
apt install nginx
```

To verify that nginx is running, and that your DNS record is pointing to your server, you may enter the hostname of your
server in your browser. You should see the default nginx welcome page ("Welcome to nginx!").

Remove the default configuration file:

```bash
rm /etc/nginx/sites-enabled/default
```

Create a configuration file for your site (`/etc/nginx/sites-available/bugsink`) with the following contents:


```
server {
    server_name                 YOURHOST;
    listen                      80;
    location / {
        proxy_pass              http://unix:/run/gunicorn.sock;
        proxy_set_header        Host $host;
    }
}
```

(YOURHOST should be replaced with the hostname of your server).

Create a link from `sites-enabled` to `sites-available`:

```bash
ln -s /etc/nginx/sites-available/bugsink /etc/nginx/sites-enabled
```

Check the configuration file for syntax errors:

```bash
service nginx configtest
```

If there are no errors, restart nginx:

```bash
systemctl restart nginx
```

You should now be able to access Bugsink by going to `http://YOURHOST` in your browser.

Congratulations!

## Setting up SSL

To set up SSL, we will use certbot, a tool that automates the process of obtaining and renewing SSL certificates. Certbot
is available as a snap package.

```bash
snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

Then, run certbot (following the instructions on the prompt).

We will use the `--nginx` plugin to automatically configure Nginx to use the SSL certificate.  `--no-redirect` is used
to avoid redirecting all HTTP traffic to HTTPS; we will set this up manually in the Nginx in the next step.

```bash
certbot --nginx --rsa-key-size 4096 --no-redirect
```

(If you wish, you can take a look at the configuration file in `/etc/nginx/sites-available/bugsink` to see how certbot
has modified it).

After this step you should be able to access Bugsink using HTTPS; open your browser and enter the hostname of your
server, but with `https` instead of `http`. You should see the Bugsink interface, and the browser should indicate that
the connection is secure.

## Final Nginx configuration

To avoid accidentally using the unencrypted version of the site, it's a good idea to

* set up automatic redirects from HTTP
* avoid host spoofing by setting up a catch-all `server_name` directive
* Use HSTS to ensure that browsers only connect to your site over HTTPS

A complete nginx configuration file could look like this:


```
# Disable nginx version number in headers (unnecessary information for potential attackers)
server_tokens                       off;

# Set up logging (site-specific logs are set up in the server block below)
access_log                          /var/log/nginx/bugsink.access.log;
error_log                           /var/log/nginx/bugsink.error.log;

# Catch-all server block to avoid host spoofing, i.e. to ensure that the server only responds to requests for the
# correct hostname
server {
    listen                          80 default_server;
    return                          444;
}

# Redirect HTTP to HTTPS
server {
    server_name                     YOURHOST;
    listen                          80;
    return                          307 https://$host$request_uri;
}

server {
    server_name                     YOURHOST;

    location / {
        # The socket is created by the gunicorn.socket systemd service
        proxy_pass                  http://unix:/run/gunicorn.sock;

        # Set the Host header to the original host.
        proxy_set_header            Host $host;

        # Set the X-Forwarded-Proto header to the original scheme; because Django/Bugsink is behind a proxy, it needs
        # to know the original scheme to know whether the current request is secure or not. This directive corresponds
        # to the setting "SECURE_PROXY_SSL_HEADER" in your bugsink_conf.py file.
        proxy_set_header            X-Forwarded-Proto $scheme;

        # Because the server is behind a proxy, it needs to know the original IP address of the client. This information
        # is passed on in the X-Forwarded-For header, and picked up by Bugsink because of the setting "USE_X_FORWARDED_FOR"
        proxy_set_header            X-Forwarded-For $proxy_add_x_forwarded_for;

        # Set up HSTS with a long max-age (1 year) and the "preload" directive, which tells browsers to include your
        # site in their HSTS preload list. This means that browsers will only connect to your site over HTTPS, even if
        # the user types in the URL without the "https://" prefix.
        add_header                  Strict-Transport-Security "max-age=31536000; preload" always;
    }

    # This whole block is auto-generated by Certbot; Alternatively, use the block below from the previous version of
    # the configuration file, i.e. the version of the file right after you ran certbot:
    listen 443 ssl;  # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/YOURHOST/fullchain.pem;  # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/YOURHOST/privkey.pem;  # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf;  # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;  # managed by Certbot
}
```

Again, replace `YOURHOST` with the hostname of your server. (Note that you cannot skip to this step without first
setting up a port-80 configuration file as described above, because certbot will not be able to verify your domain
otherwise.)

Make sure to check the configuration file for syntax errors, and restart nginx after making changes:

```
service nginx configtest
systemctl restart nginx
```


## Set up Snappea

Snappea is a brokerless service for background tasks.

We will set up Snappea to run as a systemd service.

Add a file `/etc/systemd/system/snappea.service` with the following contents:

```
[Unit]
Description=snappea daemon

[Service]
User=bugsink
Group=bugsink

Environment="PYTHONUNBUFFERED=1"
RuntimeDirectory=gunicorn
WorkingDirectory=/home/bugsink
ExecStart=/home/bugsink/venv/bin/bugsink-manage runsnappea
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service by running:

```bash
systemctl enable --now snappea.service
```

You may check whether this was successful by running:

```bash
systemctl status snappea.service
```

To ensure that Snappea is actually picking up tasks, you may additionally do the following:

```
# log in as bugsink user
su - bugsink

# activate the virtual environment
source venv/bin/activate

# run the following command to add a task to the queue
bugsink-manage checksnappea

# exit back to root
exit
```

The snappea journal should then show that the task was picked up and executed. Check by running:

```bash
journalctl -u snappea.service
```

This should show a log entry indicating that the task was picked up and executed:

```
Starting 000-001 for "snappea.example_tasks.fast_task" with (), {}
Worker done in 0.000s
```
