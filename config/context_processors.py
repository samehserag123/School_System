from finance.models import AcademicYear

def active_academic_year(request): # تأكد أن هذا هو نفس الاسم
    active_year = AcademicYear.objects.filter(is_active=True).first()
    return {'active_year': active_year}