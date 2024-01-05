# Alert Rules

## Opinionated take

Default setting, may be adapted at organisational level.

You should get alerts for any state change for the worse, such as:

* New issues
* Regressions
* Unmuting (could be due to volume)

The basic belief underlying this is: "you should care about the errors on your project". And therefore, you'll be
alerted when they occur.

### Volume-Based Rules for unmuting

Volume based rules may be configured per-issue for unmuting. e.g.

- First time  more than 5 events per the last 3 hours occur
- First time more than 10 events per day
- First time the total number of events exceeds 100

The idea is: "I know about this issue, I've determined it's not important, and I only want to get notified when it start
occurrung a lot (for some definition of 'a lot')"

The tie-in with alerts is: you can send notification on-unmute. (by the definition of unmuting, the alert
occurs only the _first time_ the condition occurs)

## "Later": auto-mute w/ default unmute rules

At some point we may make it so that you can configure per-project that issues are initially muted (on create) but with
some predefined set of volume-based unmute conditions, which is set on the muted issues on-create.

(This is in place of project-level volume-based alert settings. The main reason for this is that I want to keep a
symmetry/tracability between what's going on in the UI and the alerts that are going out)

## "Later": more than first-time-only

(The below only works if you let go of the idea that auto-mute is the only way you get volume-based alerts).

Rather than just having first-time only rules, you could have alerting rules that are triggered when a condition
persists. e.g.

* Any time more than 5 events occur the past 3 hours (ignoring any events that occured before the last time this was
  triggered). 

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
