from .models import AcademicYear

def global_academic_year(request):
    # جلب السنة النشطة لتكون متاحة في جميع القوالب (Templates)
    active_year = AcademicYear.objects.filter(is_active=True).first()
    return {
        'active_year': active_year
    }