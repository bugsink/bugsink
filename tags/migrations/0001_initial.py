from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("events", "0019_event_storage_backend"),
        ("issues", "0012_alter_issue_calculated_type_and_more"),
        ("projects", "0011_fill_stored_event_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="TagKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=32)),
                ("mostly_unique", models.BooleanField(default=False)),
                (
                    "project",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "unique_together": {("project", "key")},
            },
        ),
        migrations.CreateModel(
            name="TagValue",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("value", models.CharField(db_index=True, max_length=200)),
                (
                    "key",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="tags.tagkey"
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "unique_together": {("key", "value")},
            },
        ),
        migrations.CreateModel(
            name="IssueTag",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("count", models.PositiveIntegerField(default=0)),
                (
                    "issue",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tags",
                        to="issues.issue",
                    ),
                ),
                (
                    "key",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="tags.tagkey"
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.project",
                    ),
                ),
                (
                    "value",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="tags.tagvalue"
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["issue", "key", "count"],
                        name="tags_issuet_issue_i_91a1dd_idx",
                    )
                ],
                "unique_together": {("value", "issue")},
            },
        ),
        migrations.CreateModel(
            name="EventTag",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("digest_order", models.PositiveIntegerField()),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="tags",
                        to="events.event",
                    ),
                ),
                (
                    "issue",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="event_tags",
                        to="issues.issue",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.project",
                    ),
                ),
                (
                    "value",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="tags.tagvalue"
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["event"], name="tags_eventt_event_i_ac6453_idx"
                    ),
                    models.Index(
                        fields=["value", "issue", "digest_order"],
                        name="tags_eventt_value_i_6f1823_idx",
                    ),
                ],
                "unique_together": {("value", "event")},
            },
        ),
    ]
