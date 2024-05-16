## How to Deploy Bugsink for Production

To get Bugsink running, you'll need to host it on your own server. This means there's some setup involved.

But don't stress! We've made deploying Bugsink straightforward. We've minimized complexity to make it as easy as
possible.

The recommended setup is to deploy Bugsink on a single server, or a virtual one if you prefer. Then, you'll use nginx to
manage incoming requests, directing them to a gunicorn webserver.

If you have specific deployment preferences or organizational requirements, Bugsink operates like any other Django
application. You can utilize standard Django deployment methods.
