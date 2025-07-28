Bugsink is a Django-based error tracker. It's maintained by one developer and favors simple, predictable code over
abstract generality. Python 3.12 is the standard environment.

## Coding Guidance

* Keep it clear and simple.
* Avoid overly clever or verbose code — this isn't Java.
* Use Django idioms: models, views, middleware, etc.
* Follow PEP8 and ensure `flake8` passes (CI ignores E127, E741, E501, E731).
* Use descriptive names, short functions, minimal boilerplate.

## Tests

* Prefer a few focused unit tests around testable logic.
* Broader integration tests are fine to exercise key flows.
* It's OK to generate simple coverage-style tests — just mark them with:
  `# LLM-generated test for coverage`

### Further details

##### Database

* Bugsink assumes a single-writer DB model (no write concurrency).
* Keep writes short
* Use `bugsink/transaction.py` helpers like `@durable_atomic` etc.

##### Frontend (Tailwind)

* Bugsink doesn't have a backend/frontend split: "classic django instead"
* Bugsink uses Tailwind via `django-tailwind`
* Before committing, build the CSS and add it:
  `python manage.py tailwind build && git add theme/static/css/dist/styles.css`

##### Other

* Use function-based views by default.
* Use `python manage.py runserver` (uses `bugsink.settings.development`)
* The default SQLite setup should work out of the box.
