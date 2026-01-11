## Contributing

There are many ways to help contribute to Bugsink. Here are a few:

* Star the project on [GitHub](https://github.com/bugsink/bugsink)
* Open an [issue](https://www.github.com/bugsink/bugsink/issues)
* Reach out via [email](mailto:info@bugsink.com) or [discord](https://discord.gg/6Af6Yzz77C).
* Spread the word about Bugsink on your own blog, README or website
* Mention the project at local meetups and tell your friends/colleagues

### Code contributions

Code contributions are welcome! We use the GitHub PR process to review and merge code changes.

#### Local development setup

##### Prerequisites

* Python 3.10 or higher (3.10, 3.11, 3.12, 3.13, or 3.14)
* Git
* Optional: MySQL or PostgreSQL (SQLite works for local development)

##### Setting up your development environment

1. **Clone the repository**

```bash
git clone https://github.com/bugsink/bugsink.git

# event-samples repository for sample event data
git clone https://github.com/bugsink/event-samples.git

cd bugsink
```

2. **Create and activate a virtual environment**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**

```bash
# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements.development.txt
```

4. **Set environment variable**

```bash
export DJANGO_SETTINGS_MODULE="bugsink.settings.development"
```

5. **Run database migrations**

```bash
python manage.py migrate
```

6. **Create a superuser**

```bash
python manage.py createsuperuser
```

7. **Run the development server**

```bash
python manage.py runserver  
```

Visit [http://localhost:8000](http://localhost:8000) to see your local Bugsink instance.

#### Running tests

Bugsink uses Django's built-in test framework. To run the test suite:

```bash
# Run all tests
bugsink-manage test

# Run tests with verbose output
bugsink-manage test -v2

# Run tests for specific apps (replace with actual app names)
bugsink-manage test alerts api events issues
```

#### Linting and code quality

##### Flake8

* Bugsink uses flake8, with rules/exceptions documented in tox.ini

```bash
# Install flake8
pip install flake8

# Run flake8 on all Python files
flake8 
```

#### Tailwind

Bugsink uses tailwind for styling, and [django-tailwind](https://github.com/timonweb/django-tailwind/)
to "do tailwind stuff from the Django world".

If you're working on HTML, you should probably develop while running the following somewhere:

```
python manage.py tailwind start
```

The above is the "tailwind development server", a thing that watches your files
for changes and generates the relevant `styles.css` on the fly.

Bugsink "vendors" its generated `styles.css` in source control management (git) from the pragmatic
perspective that this saves "everybody else" from doing the tailwind build.

Before committing, run the following:

```
python manage.py tailwind build
git add theme/static/css/dist/styles.css
```

The pre-commit hook in the project's root does this automatically if needed, copy it to .git/hooks
to auto-run.

### Security

For security-related contributions, please refer to the [Security Policy](/SECURITY.md).

#### Legal

* Please confirm that you are the author of the code you are contributing, or that you have the right to contribute it.
* Sign the [Contributor License Agreement](/CLA.md); the "CLA bot" will join the PR to help you with this.
