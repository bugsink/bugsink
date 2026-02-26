#!/usr/bin/env python
"""
RAM profiling script for Bugsink.

Measures RSS memory usage at various stages using fresh subprocesses (to avoid
cross-contamination between measurements) and tracemalloc for allocation breakdown.

Sections:
  1. Clean RSS measurements (fresh subprocess per data point)
  2. tracemalloc allocation breakdown during django.setup()
  3. Per-event memory cost during ingest/digest

Usage:
    python tools/profile_ram.py

Requires: psutil
  pip install psutil
"""
import os
import sys
import gc
import datetime
import subprocess
import tracemalloc
from collections import defaultdict

# Make sure we're in the repo root and settings are configured
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bugsink.settings.development")

try:
    import psutil
except ImportError:
    sys.exit("psutil is required. Install with: pip install psutil")


def section(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def fresh_rss(setup_code):
    """Measure RSS in a fresh subprocess after running setup_code."""
    full = (
        "import psutil, gc, os, sys\n"
        "proc = psutil.Process()\n"
        + setup_code
        + "\ngc.collect()\nprint(f'{proc.memory_info().rss/1024/1024:.1f}')\n"
    )
    result = subprocess.run([sys.executable, "-c", full], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return 0.0


_SETUP = (
    'os.environ["DJANGO_SETTINGS_MODULE"] = "bugsink.settings.development"\n'
    "import django; django.setup()\n"
)

# ---------------------------------------------------------------------------
# 1. Clean RSS measurements (subprocess per data point)
# ---------------------------------------------------------------------------
section("1. Clean RSS measurements (fresh subprocess, no tracemalloc overhead)")

rss_bare = fresh_rss("pass")
rss_setup = fresh_rss(_SETUP)
rss_jsonschema = fresh_rss(_SETUP + "import jsonschema\n")
rss_fastjsonschema = fresh_rss(_SETUP + "import jsonschema\nimport fastjsonschema\n")
rss_symbolic = fresh_rss(_SETUP + "import jsonschema\nimport fastjsonschema\nimport symbolic\n")
rss_user_agents = fresh_rss(
    _SETUP + "import jsonschema\nimport fastjsonschema\nimport symbolic\nimport user_agents\n"
)

rows = [
    ("Bare Python",                  rss_bare,         rss_bare - rss_bare),
    ("+ django.setup() (all apps)",  rss_setup,        rss_setup - rss_bare),
    ("  + jsonschema (first ingest)", rss_jsonschema,   rss_jsonschema - rss_setup),
    ("  + fastjsonschema",            rss_fastjsonschema, rss_fastjsonschema - rss_jsonschema),
    ("  + symbolic (first minidump)", rss_symbolic,     rss_symbolic - rss_fastjsonschema),
    ("  + user_agents (first UI req)", rss_user_agents, rss_user_agents - rss_symbolic),
]

fmt = "  {:<38s} {:>7s}   {:>9s}"
print(fmt.format("Stage", "RSS MiB", "Delta MiB"))
print("  " + "-" * 58)
for label, rss, delta in rows:
    delta_str = f"+{delta:.1f}" if delta >= 0 else f"{delta:.1f}"
    print(fmt.format(label, f"{rss:.1f}", delta_str))

print()
print(f"  Fully-warmed process RSS: ~{rss_user_agents:.0f} MiB")
print()
print("  Note: fastjsonschema loads on first ingest request.")
print("  jsonschema loads only on first validation failure (lazy import).")
print("  symbolic and user_agents are already lazy (loaded only when needed).")

# ---------------------------------------------------------------------------
# 2. tracemalloc breakdown during django.setup()
# ---------------------------------------------------------------------------
section("2. tracemalloc allocation breakdown during django.setup()")
print("(Note: tracemalloc itself adds ~25 MiB RSS overhead; use section 1 for")
print(" accurate absolute RSS numbers. tracemalloc is useful for relative")
print(" breakdowns of Python-managed allocations.)")

tracemalloc.start()
snap_before = tracemalloc.take_snapshot()

import django
django.setup()

snap_after = tracemalloc.take_snapshot()

stats = snap_after.compare_to(snap_before, "filename")
pkg_alloc = defaultdict(int)
for stat in stats:
    if stat.size_diff <= 0:
        continue
    fname = stat.traceback[0].filename
    if "site-packages" in fname:
        pkg = fname.split("site-packages/")[-1].split("/")[0]
    elif fname.startswith(BASE_DIR):
        pkg = "bugsink:" + fname[len(BASE_DIR) + 1:].split("/")[0]
    elif fname.startswith("<frozen"):
        pkg = fname
    else:
        pkg = "stdlib"
    pkg_alloc[pkg] += stat.size_diff

total = sum(pkg_alloc.values())
print(f"\nPython-managed allocations during django.setup(): {total/1024/1024:.1f} MiB")
print("(RSS includes additional native code from C extensions — not tracked here)")
print()
fmt2 = "  {:<45s} {:>8s}   {:>6s}"
print(fmt2.format("Package", "MiB", "%"))
print("  " + "-" * 62)
for pkg, size in sorted(pkg_alloc.items(), key=lambda x: -x[1])[:20]:
    pct = 100 * size / total if total else 0
    print(fmt2.format(pkg, f"{size/1024/1024:.2f}", f"{pct:.1f}%"))

# ---------------------------------------------------------------------------
# 3. Per-event cost during ingest/digest
# ---------------------------------------------------------------------------
section("3. Per-event memory cost during ingest/digest (50 events)")

proc = psutil.Process()
gc.collect()

from events.factories import create_event_data
from projects.models import Project
from ingest.views import BaseIngestAPIView
from compat.timestamp import format_timestamp
from django.test.runner import DiscoverRunner
from django.conf import settings

# Use in-memory SQLite to avoid interactive prompts
settings.DATABASES["default"]["TEST"] = {"NAME": ":memory:"}

runner = DiscoverRunner(verbosity=0)
old_config = runner.setup_databases()

project = Project.objects.create(name="profile_test")

gc.collect()
rss_pre = proc.memory_info().rss / 1024 / 1024
snap_pre = tracemalloc.take_snapshot()

for i in range(50):
    event_data = create_event_data(exception_type=f"TestError{i % 10}")
    now = datetime.datetime.now(datetime.timezone.utc)
    event_metadata = {
        "event_id": event_data["event_id"],
        "project_id": project.id,
        "ingested_at": format_timestamp(now),
    }
    BaseIngestAPIView.digest_event(event_metadata, event_data)

gc.collect()
rss_post = proc.memory_info().rss / 1024 / 1024
snap_post = tracemalloc.take_snapshot()

delta_rss = rss_post - rss_pre
print(f"RSS delta for 50 events: +{delta_rss:.1f} MiB (~{delta_rss/50*1024:.0f} KiB/event)")
print()
print("Top tracemalloc allocations during 50 ingest/digest cycles:")
ingest_stats = snap_post.compare_to(snap_pre, "lineno")
for stat in ingest_stats[:10]:
    if stat.size_diff > 0:
        loc = str(stat.traceback[0]).split("site-packages/")[-1]
        print(f"  {loc:70s}: {stat.size_diff/1024:.1f} KiB")

runner.teardown_databases(old_config)

# ---------------------------------------------------------------------------
# 4. Where requests comes from (startup)
# ---------------------------------------------------------------------------
section("4. Module origin: which packages are eagerly loaded at startup?")
print("Packages loaded by django.setup() (grouped, new modules only):")
before_mods = set(sys.modules.keys())
tops = defaultdict(int)
for m in sys.modules:
    tops[m.split(".")[0]] += 1

interesting = {
    "django": "framework (expected)",
    "requests": "HTTP lib — loaded via alerts/service_backends/*.py top-level import",
    "sentry_sdk": "error reporting — loads urllib3/certifi eagerly",
    "urllib3": "HTTP transport — pulled in by sentry_sdk",
    "charset_normalizer": "encoding detection — transitive dep of requests",
    "idna": "internationalized domain names — transitive dep of requests/urllib3",
    "certifi": "CA certificates — transitive dep of sentry_sdk/requests",
    "sqlparse": "SQL formatting — Django debug toolbar / migrations",
    "asyncio": "async event loop — pulled in by Django",
    "jsonschema": "JSON schema validation — loaded on first ingest",
    "fastjsonschema": "fast JSON schema validation — loaded on first ingest",
    "symbolic": "minidump parsing — lazy (only on first minidump)",
    "user_agents": "UA string parsing — lazy (already lazy in ua_stuff.py)",
}
print()
fmt3 = "  {:<22s} {:>3d} mod  {}"
for pkg, note in interesting.items():
    count = tops.get(pkg, 0)
    marker = "  ← already lazy" if "lazy" in note else ""
    print(fmt3.format(pkg, count, note + marker))
