from .models import SystemSettings

def admission_status(request):
    settings = SystemSettings.objects.first()
    return {
        'admission_open': settings.is_admission_open if settings else True
    }