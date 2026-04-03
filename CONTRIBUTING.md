# Contributing

There are many ways to help contribute to Bugsink. Here are a few:

* Star the project on [GitHub](https://github.com/bugsink/bugsink)
* Open an [issue](https://www.github.com/bugsink/bugsink/issues)
* Reach out via [email](mailto:info@bugsink.com) or [discord](https://discord.gg/6Af6Yzz77C).
* Spread the word about Bugsink on your own blog, README or website
* Mention the project at local meetups and tell your friends/colleagues

## Code contributions

Code contributions are welcome! We use the GitHub PR process to review and merge code changes.

### Local development setup

#### Prerequisites

* Python 3.10 or higher (3.10, 3.11, 3.12, 3.13, or 3.14)
* Git
* Optional: MySQL or PostgreSQL (SQLite works for local development)

#### Setting up your development environment

1. **Clone the repository**

```bash
git clone https://github.com/bugsink/bugsink.git
```

The full test-suite depends on sample event data, which is not included in the main repository. To get this data, also
clone the `event-samples` repository:

```
# event-samples repository for sample event data
git clone https://github.com/bugsink/event-samples.git
```

If the event-samples live at the same level as the main repository, the test suite will find it automatically. If you
put it somewhere else, set the set the environment variable `SAMPLES_DIR` accordingly.

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

4. **Run database migrations**

```bash
python manage.py migrate
```

5. **Create a superuser**

```bash
python manage.py createsuperuser
```

6. **Run the development server**

```bash
python manage.py runserver
```

Visit [http://localhost:8000](http://localhost:8000) to see your local Bugsink instance.

### Running tests

Bugsink uses Django's built-in test framework. To run the test suite:

```bash
# Run all tests
python manage.py test

# Run tests for specific apps (replace with actual app names)
python manage.py test alerts api events issues

# If you didn't clone the event-samples repository, you can run tests that don't depend on sample data like this:
python manage.py test --exclude-tag=samples
```

### Commit messages

No need for magical phrases in the messages; any tense is fine.
Formatting: Linus-style (short summary, blank line, more detailed description if needed, 72-character line limit).

Details: focus on _why_ things needed to be changed. For bugs this is often a story (in prose, not bullets) of:

1. "problem/symptom"
2. cause
3. design decisions/trade offs
4. the fix.

### Architectural notes

#### Single Writer Database Architecture

Bugsink uses a [Single Writer Database Architecture](https://www.bugsink.com/blog/database-transactions/).
In general this means: keep write transactions as short as possible and wrap them in `immediate_atomic()` (if you don't
know why, read the article). For views, `atomic_for_request_method()` may be used. On the flip side: because of this
simple architecture, there is no need for complex locking/reasoning about transaction isolation/race conditions.

#### Snappea

Use Snappea for follow-up work that is not needed to complete the user-visible request, especially when doing it inline
would keep the write transaction open longer. Define tasks with `@shared_task`, queue them with `.delay(...)`, and if
the task depends on committed DB state use `delay_on_commit(task, ...)` rather than calling `.delay(...)` inside the
transaction.

### Linting and code quality

#### Ruff

* Bugsink uses ruff, with rules/exceptions documented in pyproject.toml

```bash
# Install ruff
pip install ruff

# Run ruff on all Python files
ruff check .
```

### Tailwind

Bugsink uses tailwind for styling, and [django-tailwind](https://github.com/timonweb/django-tailwind/)
to "do tailwind stuff from the Django world".

Make sure npm (20+) is installed, then run the following to install tailwind and its dependencies:

```
python manage.py tailwind install
```

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

## Security

For security-related contributions, please refer to the [Security Policy](/SECURITY.md).

## Legal

* Please confirm that you are the author of the code you are contributing, or that you have the right to contribute it.
* Sign the [Contributor License Agreement](/CLA.md); the "CLA bot" will join the PR to help you with this.
