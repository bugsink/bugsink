from dataclasses import dataclass


@dataclass(frozen=True)
class InviteLinkNotice:
    kind: str
    link: str
    email: str


def email_not_sent_invite_link_notice(link, email):
    return InviteLinkNotice("email_not_sent", link, email)


def manual_invite_link_notice(link, email):
    return InviteLinkNotice("manual", link, email)
