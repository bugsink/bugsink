from django import forms

from bugsink.api_capabilities import CAPABILITIES, CAPABILITY_FIELD_NAMES
from projects.models import Project, projects_visible_to_user

from .models import AuthToken


class ProjectChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, project):
        if project.team is None:
            return project.name
        return "%s / %s" % (project.team.name, project.name)


class AuthTokenForm(forms.ModelForm):
    project = ProjectChoiceField(queryset=Project.objects.none(), required=False)

    class Meta:
        model = AuthToken
        fields = [
            "description",
            "is_user_bound",
            "project",
            *CAPABILITY_FIELD_NAMES.values(),
        ]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        self.fields["is_user_bound"].label = "Personal token"
        if user.is_superuser:
            self.fields["is_user_bound"].help_text = (
                "Tie this token to your own user account and current permissions."
            )
            projects = Project.objects.filter(is_deleted=False)
            self.fields["project"].empty_label = "All projects"
        else:
            self.fields["is_user_bound"].initial = True
            self.fields["is_user_bound"].disabled = True
            self.fields["is_user_bound"].help_text = "Your tokens are always tied to your user account."
            # Offer the same projects as the project list, so we don't offer a project the user cannot access.
            projects = projects_visible_to_user(Project.objects.all(), user)
            self.fields["project"].empty_label = "All my projects"

        self.fields["project"].queryset = projects.select_related("team").order_by("name")
        self.fields["project"].help_text = "Limit this token to one project, or leave it on the first option."

        for capability, field_name in CAPABILITY_FIELD_NAMES.items():
            self.fields[field_name].label = capability
            self.fields[field_name].help_text = CAPABILITIES[capability]

    @property
    def capability_groups(self):
        groups = {}
        for capability, field_name in CAPABILITY_FIELD_NAMES.items():
            prefix, name = capability.split(":", 1)
            groups.setdefault(prefix, []).append({"name": name, "field": self[field_name]})
        return [{"prefix": prefix, "capabilities": capabilities} for prefix, capabilities in groups.items()]

    def clean(self):
        cleaned_data = super().clean()

        is_user_bound = cleaned_data.get("is_user_bound", False) if self.user.is_superuser else True
        cleaned_data["is_user_bound"] = is_user_bound
        self.instance.is_user_bound = is_user_bound
        self.instance.user = self.user if is_user_bound else None

        project = cleaned_data.get("project")
        is_project_bound = project is not None
        cleaned_data["is_project_bound"] = is_project_bound
        self.instance.is_project_bound = is_project_bound
        self.instance.project = project

        selected_capabilities = {
            capability
            for capability, field_name in CAPABILITY_FIELD_NAMES.items()
            if cleaned_data.get(field_name)
        }
        if not selected_capabilities:
            raise forms.ValidationError("Select at least one capability.")

        return cleaned_data
