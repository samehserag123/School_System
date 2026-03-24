from django.contrib import admin
from django.urls import path, include
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # الصفحات الرئيسية
    path('', views.home, name='home'),
    
    # الروابط العادية للمستخدمين (HTML)
    path('students/', include('students.urls')),
    path('finance/', include('finance.urls')),
    path('treasury/', include('treasury.urls')),

    # روابط الـ API (المفصولة الآن في ملفات api_urls)
    path('api/v1/finance/', include('finance.api_urls')), 
    path('api/v1/students/', include('students.api_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)