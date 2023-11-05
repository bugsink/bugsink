from django.db import models


class Project(models.Model):
    # id is implied which makes it an Integer; we would prefer a uuid but the sentry clients have int baked into the DSN
    # parser (we could also introduce a special field for that purpose but that's ugly too)
    pass
