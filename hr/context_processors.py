# hr/context_processors.py
from .models import LeaveRequest  # تأكد من اسم موديل الإجازات عندك

def hr_notifications(request):
    """
    حساب الإشعارات المعلقة ديناميكياً لتكون متاحة في جميع القوالب (ملف الـ base والملفات الفرعية)
    """
    if request.user.is_authenticated:
        # حساب طلبات الإجازة التي حالتها "قيد الانتظار" أو "Pending"
        pending_leaves_count = LeaveRequest.objects.filter(status='pending').count()
    else:
        pending_leaves_count = 0
        
    return {
        'notification_count': pending_leaves_count
    }