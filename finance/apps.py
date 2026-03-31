from django.apps import AppConfig

class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance'
    verbose_name = 'إدارة الحسابات والخزينة'

    def ready(self):
        # استيراد السينجلز الخاص بالمالية عند تشغيل المشروع
        import finance.signals