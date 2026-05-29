"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from accounts import views as _account_views
from content import views as _content_views
from payments import views as _payment_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("about/", _content_views.about, name="about"),
    path("directory/", _account_views.directory, name="directory"),
    path("directory/<slug:slug>/", _account_views.directory_detail, name="directory_detail"),
    path("events/", include("events.urls")),
    path("dues/", _payment_views.dues_pay, name="dues"),
    path("donate/", _payment_views.donate, name="donate"),
    path("treasurer/", _payment_views.treasurer_dashboard, name="treasurer"),
    path("payments/", include("payments.urls")),
    path("", include("registrations.urls")),
    path("", include("core.urls")),
]
