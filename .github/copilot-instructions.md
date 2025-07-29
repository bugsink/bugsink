Bugsink is a Django-based error tracker. It's maintained by one developer and favors simple, predictable code over
abstract generality. Python 3.12 is the standard environment.

## Coding Guidance

* Keep it clear and simple. When in doubt: shorter.
* Use descriptive names, short functions, minimal boilerplate.
* Error-handling: avoid catching every possible error; in many cases "fail early"
  is in fact the idiom which gives much more clarity, especially in utilities.
* Avoid overly clever or verbose code
* Keep comments absolutely minimal: only comment to explain unusual or complex
  (which there shouldn't be anyway)
* Follow PEP8 and ensure `flake8` passes (CI ignores E741, E731). width: 120 columns.
* Use Django's function-based views

### Tests

Tests should be either of 2 kinds:

1. Tight unit-tests around easy-to-test, small, functions. These should express intent
   clearly and enumerate the relevant cases (and no others) very carefully. The data
   here will be very "synthetic", focussed on expressing intent

2. Broader "integration-like" tests: much more end-to-end, with the goal of covering
   [a] the integration of parts and [b] the happy paths for those. These tests should
   not try to enumerate every single case. They should reflect a more typical flow fitting
   "what would typically happen" (more natural inputs/outputs, no extensive edge-cases)

### Database

Bugsink assumes a single-writer DB model:

* Keep writes as short as possible
* Do not worry about write-concurrency (there is none)
* Use the helpers in `bugsink/transaction.py` helpers like `@durable_atomic`

### Frontend (Tailwind)

* Bugsink does NOT have a "modern" backend/frontend split: "classic django instead"
* Bugsink uses Tailwind via `django-tailwind`

Test the frontend by running the server like so and checking in a browser:

`python manage.py runserver` (uses `bugsink.settings.development`)

(an admin user is available in your environment. login with admin@example.org/admin)

### Before committing

A pre-commit hook is installed in your environment and will block any illegal commit.
Before commiting, _always_ run the following:

```
python manage.py tailwind build
git add theme/static/css/dist/styles.css
tools/strip-trailing-whitespace.sh
```

If you fail to do so the pre-commit hook will trigger, and you will not be able to commit.
