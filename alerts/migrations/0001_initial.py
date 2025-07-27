from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("projects", "0011_fill_stored_event_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="MessagingServiceConfig",
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
                (
                    "display_name",
                    models.CharField(
                        help_text='For display in the UI, e.g. "#general on company Slack"',
                        max_length=100,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("slack", "Slack (or compatible)")],
                        default="slack",
                        max_length=20,
                    ),
                ),
                ("config", models.TextField()),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="service_configs",
                        to="projects.project",
                    ),
                ),
            ],
        ),
    ]
