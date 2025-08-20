import sentry_sdk
from tqdm import tqdm
import logging

dsn = "http://02cd9dfb720c4202a42f5a962eb5b74c@127.0.0.1:9999/1"
sentry_sdk.init(dsn=dsn)


for _ in tqdm(range(100_000)):
    try:
        1 / 0
    except Exception as e:
        logging.exception(e)
