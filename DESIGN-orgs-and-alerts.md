Thoughts about alerts (starting at teams and orgs though)

We don't provide a sentry-like concept of "teams".
You are on a project (as an individual) or not. If you're on the project, you're on that project's team.
I imagine typical levels of membership are read-only, regular (state changes of issues), admin (which can do settings and memberships)

Organizations: I think I'll have them: if you work at big-co, this is where you can set up your "bigger team", a place that may have multiple projects.
Examples: github, gitlab, cloud-foundry.
Also, once I build hosted.bugsink.com this is what I can give permissions to.
This may serve as a place for inherited permissions. And as a grouper for projects. And as a place for inheritable settings.


Now, the alert rules.

Opinionated take (as well as the default setting):

* any state-change for-the-worse, i.e.
    * new
    * regression
    * no-longer-muted (for whatever reason, including 'by volume')
        this is also where 

    "you should care about errors on your project".

also available:

* by volume, over periode, first/any, e.g.:
    "any time more than 5 events per hour happen"
    "first time more than 10 events per day happen"      <= this is basically a way to avoid getting swamped in "bug sewer" scenarios
    "first time the total number of events > 100"

    an alternative take:
        auto-mute such events, based on auto-muting rules.


unmuting-by-volume/period is a thing.
    this is "first time" by definition.

====

what about personal notification settings?
    they exist, generally and
    per-project (follow the default or specific) 
        
    reason (for per-project settings).
        there is such a thing as "involved in the project, but not involved enough to get updates about it). e.g. consulting member or some kind of lead

    but they exist only as a single toggle: yes/no/(default)
        i.e. you can't select specific rules to follow for a project.


on the project is where you configure the alerting rules for the project.
    "for everybody that wants the notifications"

    the reasoning here is: a project has a certain amount of brokenness, and a certain need for correctness (an amount of received love).
        if you're on the project in an active role, you'll subscribe to that.


what about chat-ops?
    0-n configurable on the project level. not related to users.
        probably with a default on the org level.

    same rules as the rest of the alerts.