from django.shortcuts import render

from .models import Project


def project_list(request):
    project_list = Project.objects.all()
    return render(request, 'projects/project_list.html', {
        'state_filter': 'mine',
        'project_list': project_list,
    })


def project_members(request, project_pk):
    # TODO: check if user is a member of the project and has permission to view this page
    project = Project.objects.get(id=project_pk)
    return render(request, 'projects/project_members.html', {
        'project': project,
        'members': project.projectmembership_set.all().select_related('user'),
    })
