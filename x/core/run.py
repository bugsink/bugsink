import sentry_sdk
from tqdm import tqdm
import logging
from x.config import const

sentry_sdk.init(dsn=const.dsn)
sentry_sdk.set_tag("gitversion", const.gitversion)


def main():
    for _ in tqdm(range(100_000)):
        try:
            1 / 0
        except Exception as e:
            logging.exception(e)
