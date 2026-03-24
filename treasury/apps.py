from django.apps import AppConfig

class TreasuryConfig(AppConfig):  # تأكد من تغيير الاسم هنا لـ TreasuryConfig
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'treasury'  # هذا هو السطر الأهم، يجب أن يكون 'treasury' فقط
    def ready(self):
        import treasury.signals  # هذا السطر هو الذي يفعّل المراقبة التلقائية