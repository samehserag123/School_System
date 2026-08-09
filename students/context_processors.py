from .models import SystemSettings

from .models import PendingAdmissionNotification


def admission_status(request):
    settings = SystemSettings.objects.first()
    return {
        'admission_open': settings.is_admission_open if settings else True
    }


def pending_notifications_context(request):
    """إتاحة عداد الإشعارات المعلقة كمتغير عام داخل كل قوالب الـ HTML"""
    if request.user.is_authenticated:
        count = PendingAdmissionNotification.objects.filter(is_processed=False).count()
        return {'pending_notifications_count': count}
    return {'pending_notifications_count': 0}