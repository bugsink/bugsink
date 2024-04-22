import logging

logger = logging.getLogger("snappea.foreman")


class Registry:
    def __init__(self):
        self.registry = {}

    def __setitem__(self, key, value):
        self.registry[key] = value

    def __getitem__(self, key):
        if key not in self.registry:
            logger.debug(f"Task '{key}' not found in registry. Trying to import the module.")
            module_name, function = key.rsplit('.', 1)
            try:
                # importing the module will register the task if it has the shared_task decorator
                __import__(module_name, globals(), locals(), [function])
            except ImportError:
                logging.debug(f"Import failed for {module_name}.")

        return self.registry[key]


registry = Registry()
