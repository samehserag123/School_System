from django.contrib import admin
from .models import InstallmentPlan, StudentInstallment, AcademicYear, MonthlyClosure, Payment, Coupon
#from decimal import Decimal
#from .models import Payment
#from .models import MonthlyClosure

#admin.site.register(MonthlyClosure)
#admin.site.register(AcademicYear)
#admin.site.register(RevenueCategory)


# =========================
# Academic Year
# =========================
@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    list_editable = ['is_active']


# =========================
# Monthly Closure
# =========================
@admin.register(MonthlyClosure)
class MonthlyClosureAdmin(admin.ModelAdmin):
    list_display = ['month', 'total_collected', 'total_remaining']


# =========================
# Installment Plan
# =========================
@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'total_amount', 'number_of_installments']


# =========================
# Student Installments
# =========================
@admin.register(StudentInstallment)
class StudentInstallmentAdmin(admin.ModelAdmin):
    list_display = [
        'student',
        'academic_year',
        'installment_number',
        'amount_due',
        'status',
        'due_date'
    ]

    list_filter = ['academic_year', 'status']
    search_fields = ['student__first_name', 'student__last_name']
    readonly_fields = ['status']


# =========================
# Payments
# =========================
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        'installment',
        'academic_year',
        'amount_paid',
        'payment_date'
    ]

    list_filter = ['academic_year', 'payment_date']
    search_fields = [
        'installment__student__first_name',
        'installment__student__last_name'
    ]


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return request.user.is_superuser

