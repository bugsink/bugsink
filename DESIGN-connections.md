Connection closing and subsequent re-opening is not free. I've done some experiments; it looks like the connection
close/open themselves are in the sub-1ms range.

But: when being the first connection to write, there is a c. 13ms penalty. Hypothesis: the opening of the WAL file.

This is the code I played with to establish this.
Note that the result of running the second half (the Django part) without first running the first half are very
different from doing them both at once. Hence "being the first connection", i.e. there's a cross-connection effect.

```
from performance.context_managers import time_it
import sqlite3

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

with time_it() as timings:
  cursor.execute('UPDATE auth_user set username = username')
  conn.commit()

print("fresh conn", timings.took)

with time_it() as timings:
  cursor.execute('UPDATE auth_user set username = username')
  conn.commit()

print("reused conn", timings.took)


from performance.context_managers import time_it
import sqlite3
from django.db import connection
from django.db import models
from users.models import User
from performance.context_managers import time_it
from bugsink.transaction import immediate_atomic

with time_it() as timings:
    with immediate_atomic():
        User.objects.update(username=models.F('username'))

print("django fresh conn", timings.took)

with time_it() as timings:
    with immediate_atomic():
        User.objects.update(username=models.F('username'))

print("django reused conn", timings.took)
```

With just the second half:

```
...     with immediate_atomic():
...         User.objects.update(username=models.F('username'))
... 
CONNECTION created /mnt/datacrypt/dev/bugsink/db.sqlite3 124812146634816 in 0ms MainThread
      1.79ms BEGIN IMMEDIATE, A.K.A. get-write-lock ↴
      0.69ms ABOUT TO END IMMEDIATE transaction' ↴
     10.67ms END IMMEDIATE transaction' ↴
>>> print("django fresh conn", timings.took)

django fresh conn 13.312101364135742

>>> 
>>> with time_it() as timings:
...     with immediate_atomic():
...         User.objects.update(username=models.F('username'))
... 
      0.19ms BEGIN IMMEDIATE, A.K.A. get-write-lock ↴
      0.35ms ABOUT TO END IMMEDIATE transaction' ↴
      0.50ms END IMMEDIATE transaction' ↴
>>> print("django reused conn", timings.took)

django reused conn 0.9033679962158203
```
