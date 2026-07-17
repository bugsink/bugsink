import ast
import importlib
import sys
from collections import namedtuple
from pathlib import Path
from unittest import TestCase

from django.conf import settings


ROOT = Path(__file__).resolve().parents[1]
GROUPING_MECHANISMS_DIR = ROOT / "issues" / "grouping_mechanisms"
BUILDING_BLOCKS_DIR = GROUPING_MECHANISMS_DIR / "building_blocks"
SENTRY_IMPORT_HASH = "597d25951d00"
VENDORED_SENTRY_DIR = ROOT / "sentry" / f"at_{SENTRY_IMPORT_HASH}"
VENDORED_SENTRY_PACKAGES = (
    "sentry.at_597d25951d00",
    "sentry.at_glitchtip_af9a700a8706",
)
UNPINNED_SENTRY_PACKAGES = ("sentry.assemble", "sentry.minidump")
BUILDING_BLOCKS_PACKAGE = "issues.grouping_mechanisms.building_blocks"
ImportReference = namedtuple("ImportReference", ["module", "level", "display"])


class GroupingMechanismBoundaryTestCase(TestCase):
    def test_python_code_imports_vendored_sentry_through_pinned_root(self):
        def skip_import_boundary_file(path):
            relative_parts = path.relative_to(ROOT).parts
            if relative_parts[0].startswith("."):
                return True

            try:
                path.relative_to(VENDORED_SENTRY_DIR)
                return True
            except ValueError:
                return False

        self.assert_imports_allowed(
            [
                path
                for package_dir in [
                    Path(importlib.import_module(package).__file__).parent
                    for package in settings.BUGSINK_APPS
                ]
                for path in sorted(package_dir.rglob("*.py"))
                if not skip_import_boundary_file(path)
            ],
            self._is_not_unpinned_sentry_import,
        )

    def test_versioned_mechanisms_import_only_versioned_building_blocks_or_vendored_sentry(self):
        self.assert_imports_allowed(
            sorted(GROUPING_MECHANISMS_DIR.glob("v[0-9]*.py")),
            self._is_mechanism_import,
        )

    def test_building_block_imports_are_bounded(self):
        self.assert_imports_allowed(
            sorted(BUILDING_BLOCKS_DIR.glob("v[0-9]*.py")),
            self._is_building_block_import,
        )

    def test_vendored_sentry_package_imports_only_relative_modules_or_generic_python(self):
        self.assert_imports_allowed(
            sorted((VENDORED_SENTRY_DIR / "grouping").rglob("*.py")),
            self._is_relative_or_generic_python_import,
        )

    def test_vendored_sentry_packages_do_not_cross_import(self):
        for path in sorted((ROOT / "sentry").glob("at_*")):
            package = "sentry." + path.name
            self.assert_imports_allowed(
                sorted(path.rglob("*.py")),
                lambda module_path, imported: self._is_same_vendored_package_import(package, imported),
            )

    def _is_mechanism_import(self, path, imported):
        if imported.level == 1:
            return imported.module is not None and imported.module.startswith("building_blocks.v")

        return imported.level == 0 and (
            self._is_pinned_sentry_import(imported.module)
            or self._is_stdlib(imported.module)
            or self._is_django_import(imported.module)
        )

    def _is_building_block_import(self, path, imported):
        def is_lower_building_block_absolute_import(name):
            if name is None:
                return False

            if not name.startswith(BUILDING_BLOCKS_PACKAGE + ".v"):
                return False

            imported_version = self._version_from_module(name.removeprefix(BUILDING_BLOCKS_PACKAGE + "."))
            return imported_version < self._version_from_path(path)

        def is_lower_building_block_relative_import(name):
            if name is None:
                return False

            if not name.split(".", 1)[0].startswith("v"):
                return False

            imported_version = self._version_from_module(name)
            return imported_version < self._version_from_path(path)

        if imported.level == 1:
            return is_lower_building_block_relative_import(imported.module)

        return imported.level == 0 and (
            self._is_pinned_sentry_import(imported.module)
            or is_lower_building_block_absolute_import(imported.module)
            or self._is_django_import(imported.module)
            or self._is_stdlib(imported.module)
        )

    def _is_relative_or_generic_python_import(self, path, imported):
        return imported.level > 0 or self._is_stdlib(imported.module)

    def _is_not_unpinned_sentry_import(self, path, imported):
        if imported.module is None:
            return True

        if imported.module == "sentry" or imported.module.startswith("sentry."):
            return (
                self._is_pinned_sentry_import(imported.module)
                or any(
                    imported.module == package or imported.module.startswith(package + ".")
                    for package in UNPINNED_SENTRY_PACKAGES
                )
            )

        return True

    def _is_same_vendored_package_import(self, package, imported):
        if imported.module is None:
            return True

        if imported.module == "sentry" or imported.module.startswith("sentry."):
            return imported.module == package or imported.module.startswith(package + ".")

        if imported.module == "issues.grouping_mechanisms.building_blocks.v1":
            return True

        if imported.module == "issues" or imported.module.startswith("issues."):
            return False

        return True

    def _is_pinned_sentry_import(self, name):
        if name is None:
            return False

        return any(name == package or name.startswith(package + ".") for package in VENDORED_SENTRY_PACKAGES)

    def _is_stdlib(self, name):
        if name is None:
            return False

        root_name = name.split(".", 1)[0]
        return root_name in sys.stdlib_module_names

    def _is_django_import(self, name):
        # Django's small framework utilities are not part of the grouping mechanism behavior we freeze here.
        return name == "django" or name.startswith("django.")

    def assert_imports_allowed(self, paths, is_allowed):
        for path in paths:
            for imported in self._imports_in(path):
                self.assertTrue(
                    is_allowed(path, imported),
                    f"{path.relative_to(ROOT)} imports {imported.display}",
                )

    def _imports_in(self, path):
        def format_from_import(node):
            dots = "." * node.level
            module = node.module or ""
            names = ", ".join(alias.name for alias in node.names)
            return f"from {dots}{module} import {names}"

        tree = ast.parse(path.read_text(), filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield ImportReference(alias.name, 0, alias.name)

            if isinstance(node, ast.ImportFrom):
                yield ImportReference(node.module, node.level, format_from_import(node))

    def _version_from_path(self, path):
        return int(path.stem.removeprefix("v"))

    def _version_from_module(self, name):
        version = name.split(".", 1)[0]
        if not version.startswith("v"):
            return 0

        return int(version.removeprefix("v"))
