# Alert Rules

## Opinionated take

Default setting, may be adapted at organisational level.

You should get alerts for:

* **Any State Change for the Worse:**
    - New issues
    - Regressions
    - Unmuting (could be due to volume)

    The basic belief underlying this is: "you should care about the errors on your project". And therefor, you'll be
    alerted when they occur.

You may configure alerts for:

* **Volume-Based Rules:**
    - _Any time_ more than 5 events per hour occur
    - _First time_ more than 10 events per day
    - _First time_ the total number of events exceeds 100
    
    The idea is: to avoid getting swamped, set thresholds slightly higher then 1 (over some period).

    An alternative approach is to automatically unmute issues based on such rules (and to initially mute them as long as
    they don't match the rules yet); and then send the notification on-unmute. (by the definition of unmuting, the alert
    occurs only the _first time_ the condition occurs)

## Personal Notification Settings

Personal notification settings exist both globally and per project. 

Reasons for per-project settings include scenarios where someone is involved in the project but not to the extent of
needing constant updates (e.g., consulting members or certain leads). 

However, these settings are limited to a single toggle: yes/no/(default). That is, you can't choose specific rules to
follow for a project.

Configuration of alerting rules is project-centered. The idea is that the 2 main variables that control when alerts
should be sent are project-centric (not member-centric), namely:

* how broken the project is (how many errors are generated)
* how important brokenness is

I.e. there is a single (configurable) threshold per project for what constitues "worth alerting about but avoiding
swamping in false positives" which you can then subscribe to or not.

## Chat-Ops

You may configure any number of chat-ops endpoints (mattermost/slack channels). These are not connected to individual
users. There's likely a default setting at the organization level.

The chat-ops channels always receive the per-project configured set of notifications, i.e. the threshold cannot be
changed per chat-op-channel (as with users).
