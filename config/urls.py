from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),

    # صفحات HTML
    path('students/', include('students.urls')),
    path('finance/', include('finance.urls')),

    # API
    path('api/v1/students/', include('students.api_urls')),
    #path('api/v1/finance/', include('finance.api_urls')),
]
