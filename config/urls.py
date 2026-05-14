from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from finance.views import MyLoginView
from . import views 

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', MyLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('', login_required(views.home), name='home'),
    
    path('students/', include('students.urls')),
    path('finance/', include('finance.urls')),
    path('treasury/', include('treasury.urls')),
    path('hr/', include('hr.urls')),

    path('api/v1/finance/', include('finance.api_urls')), 
    path('api/v1/students/', include('students.api_urls')),
]

# تفعيل الـ Debug Toolbar وملفات الميديا فقط في وضع DEBUG
if settings.DEBUG:
    # إضافة روابط ملفات الميديا
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    
    # إضافة روابط Debug Toolbar بشكل آمن
    try:
        import debug_toolbar
        urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    except ImportError:
        pass