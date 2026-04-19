from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required

# استيراد كلاس تسجيل الدخول من تطبيق finance
from finance.views import MyLoginView
from . import views 

urlpatterns = [
    # 1. لوحة تحكم الإدارة (Django Admin)
    path('admin/', admin.site.urls),

    # 2. نظام تسجيل الدخول (Login)
    # ملاحظة: لا نضع login_required هنا للسماح للمستخدم بالوصول لصفحة الدخول
    path('login/', MyLoginView.as_view(), name='login'),

    # 3. نظام تسجيل الخروج (Logout)
    # يوجه المستخدم تلقائياً لصفحة اللوجن بعد الخروج
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # 4. الصفحة الرئيسية (Home)
    # محمية بـ login_required: إذا حاول شخص دخولها بدون لوجن سيتم تحويله لصفحة /login/
    path('', login_required(views.home), name='home'),
    

    # 5. روابط التطبيقات (HTML)
    path('students/', include('students.urls')),
    path('finance/', include('finance.urls')),
    path('treasury/', include('treasury.urls')),
    
    path('hr/', include('hr.urls')),

    # 6. روابط الـ API (REST Framework)
    path('api/v1/finance/', include('finance.api_urls')), 
    path('api/v1/students/', include('students.api_urls')),
]

# دعم ملفات الميديا (الصور والملفات المرفوعة) في وضع التطوير
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)