"""
ASGI config for config project.

Routes HTTP to Django and WebSockets to Channels (Parlêtre realtime chat,
M13.5b). See https://channels.readthedocs.io/.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# The HTTP application must be built before importing anything that touches
# models / app registry.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

import notifications.routing  # noqa: E402
import parletre.routing  # noqa: E402

websocket_urlpatterns = (
    parletre.routing.websocket_urlpatterns
    + notifications.routing.websocket_urlpatterns
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
