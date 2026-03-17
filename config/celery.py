import os
from celery import Celery
from celery.schedules import crontab

# ضبط إعدادات Django الافتراضية لبرنامج celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_system.settings')

app = Celery('school_system')

# استخدام سلسلة نصية هنا يعني أن العامل (worker) لا يضطر لعمل serialize للكود
app.config_from_object('django.conf:settings', namespace='CELERY')

# تحميل المهام من جميع تطبيقات Django المسجلة
app.autodiscover_tasks()

# إعداد الجدول الزمني للمهام (Beat)
app.conf.beat_schedule = {
    'send-late-notifications-every-morning': {
        'task': 'finance.views.notify_admin_of_late_payments',
        'schedule': crontab(hour=8, minute=0), # الساعة 8 صباحاً
    },
}