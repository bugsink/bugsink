class SeparateSnappeaDBRouter(object):

    def db_for_read(self, model, **hints):
        if model._meta.app_label == "snappea":
            return "snappea"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == "snappea":
            return "snappea"
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == "snappea":
            return app_label == "snappea"

        return app_label != "snappea"
