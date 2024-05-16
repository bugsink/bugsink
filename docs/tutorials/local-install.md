# Quick install guide

Before you can use Bugsink, you'll need to install it. We have a [comprehensive
guide](/how-to/install) that covers all the details, but if you just want to get
started quickly on your local development environment, here's a quick guide.

Running locally is a great way to determine if Bugsink is right for you and is
even easier to set up than a production environment. Bugsink's License allows
you to run it for a single user on your local machine for free.

## Install Python

Bugsink is written in Python, so you need to have Python installed on your
system. You can download Python from the [official
website](https://www.python.org/downloads/) or using a package manager like
`apt` or `brew`.

You can verify that Python is installed by running the following command:

```bash
python --version
```

## Set up a working dir

Both the Bugsink code and the data it collects will be stored somewhere.

Create a new directory and navigate to it:

```bash
mkdir bugsink
cd bugsink
```

## Set up a virtual environment and activate it

It's a good practice to use a virtual environment to manage your Python
dependencies. This way, you can avoid conflicts between different projects.

Run the following commands to create a virtual environment and activate it:

```bash
python -m venv .
source bin/activate
```

After running these commands, you should see the name of the virtual environment
in your shell prompt.

## Install Bugsink and its dependencies

You can install Bugsink using `pip`:

```bash
pip install bugsink
```

You should see output indicating that Bugsink and its dependencies are being
installed. After the installation is complete, you can verify that Bugsink is
installed by running:

```bash
bugsink-show-version
```

## Create configuration template

Bugsink relies on a configuration file to determine how it should run.

You can create a configuration file that's suitable for local development by
running:

```bash
bugsink-create-conf --local-development --port=9000
```

This will create a file `bugsink_conf.py` in the current directory. You may
later edit this file to customize the configuration, but for this tutorial, the
default configuration should be sufficient.

## Initialize the database

Bugsink uses a database to store the data it collects.

You can initialize the database by running:

```bash
bugsink-manage migrate
```

This will create a new SQLite database in the current directory and set up the
necessary tables.

## Create a superuser

You can create a superuser account to access the Bugsink admin interface.

Run the following command and follow the prompts:

```bash
bugsink-manage createsuperuser
```

This will create a new user account with administrative privileges.

## Run the Bugsink server

The recommended way to run Bugsink is using Gunicorn, a WSGI server.

You can start the Bugsink server by running:

```bash
PYTHONUNBUFFERED=1 gunicorn --bind="127.0.0.1:9000" --access-logfile - --capture-output --error-logfile - bugsink.wsgi
```

You should see output indicating that the server is running. You can now access Bugsink by visiting
http://localhost:9000/ in your web browser.



## Next steps

You've successfully installed Bugsink on your local machine! You can now start
using it to collect crash reports for your (local) applications.
