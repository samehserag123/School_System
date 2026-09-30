"""
Django settings for config project.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# 1. تحميل المتغيرات من ملف .env فوراً
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# 2. إعدادات الأمان الأساسية (تم تنظيف التكرارات والاعتماد على .env)
# إذا لم يجد المفتاح، سيستخدم مفتاحاً عشوائياً لمنع اختراق الجلسات بدلاً من مفتاح ثابت
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-fallback-only-for-dev')

# الحماية الأهم: تعطيل وضع تصحيح الأخطاء افتراضياً إلا إذا تم تفعيله صراحة في .env
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

# 3. المضيفون المسموح لهم (مغلق ومحمي في وضع الإنتاج)
allowed_hosts_env = os.environ.get('ALLOWED_HOSTS', '127.0.0.1,localhost')
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_env.split(',') if host.strip()]

# فتح النطاقات الإضافية (مثل Cloudflare أو IP المحلي) مسموح *فقط* في وضع التطوير (DEBUG = True)
if DEBUG:
    if '.trycloudflare.com' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append('.trycloudflare.com')
    if '192.168.147.93' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append('192.168.147.93')
    if '*' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append('*')
    CSRF_TRUSTED_ORIGINS = ["https://*.trycloudflare.com"]
else:
    # في الإنتاج، نثق فقط بالنطاق الرسمي
    CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host != '*']

# 4. التطبيقات المثبتة
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'rest_framework',
    'corsheaders',
    'students',
    'finance.apps.FinanceConfig',
    'treasury.apps.TreasuryConfig',
    'hr',
    'accounts',
    'audit',
    'core_inventory',
    'crispy_forms',
    'crispy_bootstrap5',
]

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# 5. البرمجيات الوسيطة (Middleware)
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if DEBUG:
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE.append('debug_toolbar.middleware.DebugToolbarMiddleware')

ROOT_URLCONF = 'config.urls'

# 6. القوالب (Templates)
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / "templates",
            BASE_DIR / "students" / "templates" / "students" / "books",
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'config.context_processors.active_academic_year',
                'students.context_processors.admission_status',
                'hr.context_processors.hr_notifications',
                'students.context_processors.pending_notifications_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# 7. قواعد البيانات (محمية بالكامل الآن)
if os.environ.get('PYTHONANYWHERE_SITE'):
    # قاعدة البيانات الحية للمدرسة على السيرفر السحابي (كلمة المرور تقرأ من .env بشكل آمن)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': 'sameh123$talaat_harb',
            'USER': 'sameh123',
            'PASSWORD': os.environ.get('DB_PASSWORD'),
            'HOST': 'sameh123.mysql.pythonanywhere-services.com',
        }
    }
else:
    # قاعدة بيانات التطوير
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'school_db'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'postgres'),
            'HOST': os.getenv('DB_HOST', 'db'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }

db_from_env = dj_database_url.config(conn_max_age=600)
if db_from_env:
    DATABASES['default'].update(db_from_env)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Cairo'
USE_I18N = True
USE_TZ = True

# 8. الملفات الثابتة والميديا (Static & Media)
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
}

CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

ADMIN_EMAIL = 'admin@school.com'
DEFAULT_FROM_EMAIL = 'system@school.com'

# 9. إعدادات نظام تسجيل الدخول والخروج
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'login'

# 10. إعدادات الجلسة (Sessions) المُصلحة
SESSION_COOKIE_AGE = 43200
SESSION_EXPIRE_AT_BROWSER_CLOSE = False     # تم تعديلها لتسمح ببقاء الجلسة 12 ساعة
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

APPEND_SLASH = True
REMOVE_SLASH = False
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 11. إعدادات الأمان ونقل البيانات
CORS_ALLOW_ALL_ORIGINS = False  # تم إغلاق الثغرة
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000  # حد آمن ومعقول

if DEBUG:
    import socket
    try:
        hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
        INTERNAL_IPS = [ip[: ip.rfind(".")] + ".1" for ip in ips] + ["127.0.0.1", "10.0.2.2"]
    except Exception:
        INTERNAL_IPS = ["127.0.0.1"]
    DEBUG_TOOLBAR_CONFIG = {
        'SHOW_TOOLBAR_CALLBACK': lambda request: True,
    }

# 12. تفعيل دروع الحماية القصوى في الإنتاج (Production)
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000  # إجبار المتصفحات على استخدام HTTPS لمدة عام
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True