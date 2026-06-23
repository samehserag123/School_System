from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Payment, StudentAccount 
from .models import StudentInstallment
from django.db.models import Sum
from decimal import Decimal

import threading
from django.contrib.auth.signals import user_logged_in
from django.core.cache import cache

import datetime

def background_cache_warming():
    """ الدالة الشبحية لتسخين الكاش المالي في الخلفية (النسخة الكاملة الآمنة) """
    from students.models import Student, Grade
    from finance.models import StudentInstallment, Payment, StudentAccount, AcademicYear
    from treasury.models import GeneralLedger

    try:
        current_year = AcademicYear.objects.filter(is_active=True).first()
        if not current_year: return
        today = datetime.date.today()
        
        dash_cache_key = f"finance_dashboard_heavy_stats_year_{current_year.id}_{today.strftime('%Y%m')}"
        
        # تسخين الكاش فقط إذا كان غير موجود
        if not cache.get(dash_cache_key):
            # 1. إيرادات الخزينة
            month_revenue_all = GeneralLedger.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
            year_revenue_all = GeneralLedger.objects.filter(date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0

            # 2. إحصائيات الداشبورد (استعلامات Aggregate سريعة جداً)
            total_paid_students = StudentInstallment.objects.filter(academic_year=current_year).aggregate(total=Sum('paid_amount'))['total'] or 0
            total_fees_req = StudentInstallment.objects.filter(academic_year=current_year).aggregate(total=Sum('amount_due'))['total'] or 0
            total_old_debts = Student.objects.filter(academic_year=current_year).aggregate(total=Sum('previous_debt'))['total'] or 0
            
            total_target_all = total_fees_req + total_old_debts
            total_debt_combined = max(total_target_all - total_paid_students, 0)
            total_percentage = round((total_paid_students / total_target_all * 100), 1) if total_target_all > 0 else 0

            # 3. إحصائيات الفصول
            installments_agg = StudentInstallment.objects.filter(academic_year=current_year).values('student__grade__name').annotate(
                g_target=Sum('amount_due'), g_paid=Sum('paid_amount')
            )
            debt_agg = Student.objects.filter(academic_year=current_year).values('grade__name').annotate(
                g_old_debt=Sum('previous_debt')
            )

            grades_data = {grade.name: {'target': 0, 'paid': 0, 'old_debt': 0} for grade in Grade.objects.all()}

            for item in installments_agg:
                g_name = item['student__grade__name']
                if g_name in grades_data:
                    grades_data[g_name]['target'] = item['g_target'] or 0
                    grades_data[g_name]['paid'] = item['g_paid'] or 0

            for item in debt_agg:
                g_name = item['grade__name']
                if g_name in grades_data:
                    grades_data[g_name]['old_debt'] = item['g_old_debt'] or 0

            grades_efficiency = []
            for g_name, data in grades_data.items():
                g_total_target = data['target'] + data['old_debt']
                g_paid = data['paid']
                grades_efficiency.append({
                    'grade': g_name,
                    'target': float(g_total_target),
                    'paid': float(g_paid),
                    'remaining': float(max(g_total_target - g_paid, 0)),
                    'percentage': round((g_paid / g_total_target * 100), 1) if g_total_target > 0 else 0
                })

            # حفظ القاموس كاملاً في الكاش لتجنب خطأ KeyError
            heavy_stats = {
                "month_revenue_all": float(month_revenue_all),
                "year_revenue_all": float(year_revenue_all),
                "total_debt_combined": float(total_debt_combined),
                "total_percentage": float(total_percentage),
                "grades_efficiency": grades_efficiency,
            }
            cache.set(dash_cache_key, heavy_stats, 1800)
    except Exception as e:
        print(f"Error in cache warming: {e}")

@receiver(user_logged_in)
def trigger_cache_warming_on_login(sender, user, request, **kwargs):
    if user.is_superuser or user.groups.filter(name__in=["Finance_General", "Full_Access_No_Admin"]).exists():
        thread = threading.Thread(target=background_cache_warming)
        thread.daemon = True
        thread.start()
        
        
# def background_cache_warming():
#     """ الدالة الشبحية لتسخين الكاش المالي في الخلفية """
#     from students.models import Student, Grade
#     from finance.models import StudentInstallment, Payment, StudentAccount, AcademicYear
#     from treasury.models import GeneralLedger

#     try:
#         current_year = AcademicYear.objects.filter(is_active=True).first()
#         if not current_year: return
#         today = datetime.date.today()
        
#         dash_cache_key = f"finance_dashboard_heavy_stats_year_{current_year.id}_{today.strftime('%Y%m')}"
#         if not cache.get(dash_cache_key):
#             month_revenue_all = GeneralLedger.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
#             year_revenue_all = GeneralLedger.objects.filter(date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0

#             heavy_stats = {
#                 "month_revenue_all": month_revenue_all,
#                 "year_revenue_all": year_revenue_all,
#             }
#             cache.set(dash_cache_key, heavy_stats, 1800)
#     except Exception as e:
#         print(f"Error in cache warming: {e}")

# @receiver(user_logged_in)
# def trigger_cache_warming_on_login(sender, user, request, **kwargs):
#     if user.is_superuser or user.groups.filter(name__in=["Finance_General", "Full_Access_No_Admin"]).exists():
#         thread = threading.Thread(target=background_cache_warming)
#         thread.daemon = True
#         thread.start()
        
        
# def background_cache_warming():
#     """ الدالة الشبحية لتسخين الكاش المالي في الخلفية """
#     from students.models import Student, Grade
#     from finance.models import StudentInstallment, Payment, StudentAccount, AcademicYear
#     from treasury.models import GeneralLedger

#     try:
#         current_year = AcademicYear.objects.filter(is_active=True).first()
#         if not current_year:
#             return

#         today = datetime.date.today()
        
#         # 1. مفاتيح الكاش
#         student_cache_key = f"student_stats_year_{current_year.id}_grade_None_class_None_search_"
#         dash_cache_key = f"finance_dashboard_heavy_stats_year_{current_year.id}_{today.strftime('%Y%m')}"

#         print("🚀 جاري تسخين كاش الأنظمة المالية في الخلفية...")

#         # ==========================================
#         # 🔥 تسخين الداشبورد المالي الرئيسي
#         # ==========================================
#         if not cache.get(dash_cache_key):
#             month_revenue_all = GeneralLedger.objects.filter(date__month=today.month, date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
#             year_revenue_all = GeneralLedger.objects.filter(date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0

#             total_paid_students = StudentInstallment.objects.filter(academic_year=current_year).aggregate(total=Sum('paid_amount'))['total'] or 0
#             total_fees_req = StudentInstallment.objects.filter(academic_year=current_year).aggregate(total=Sum('amount_due'))['total'] or 0
#             total_old_debts = Student.objects.filter(academic_year=current_year).aggregate(total=Sum('previous_debt'))['total'] or 0
            
#             total_target_all = total_fees_req + total_old_debts
#             total_debt_combined = max(total_target_all - total_paid_students, 0)
#             total_percentage = round((total_paid_students / total_target_all * 100), 1) if total_target_all > 0 else 0

#             installments_agg = StudentInstallment.objects.filter(academic_year=current_year).values('student__grade__name').annotate(
#                 g_target=Sum('amount_due'), g_paid=Sum('paid_amount')
#             )
#             debt_agg = Student.objects.filter(academic_year=current_year).values('grade__name').annotate(
#                 g_old_debt=Sum('previous_debt')
#             )

#             grades_data = {grade.name: {'target': 0, 'paid': 0, 'old_debt': 0} for grade in Grade.objects.all()}

#             for item in installments_agg:
#                 g_name = item['student__grade__name']
#                 if g_name in grades_data:
#                     grades_data[g_name]['target'] = item['g_target'] or 0
#                     grades_data[g_name]['paid'] = item['g_paid'] or 0

#             for item in debt_agg:
#                 g_name = item['grade__name']
#                 if g_name in grades_data:
#                     grades_data[g_name]['old_debt'] = item['g_old_debt'] or 0

#             grades_efficiency = []
#             for g_name, data in grades_data.items():
#                 g_total_target = data['target'] + data['old_debt']
#                 g_paid = data['paid']
#                 grades_efficiency.append({
#                     'grade': g_name,
#                     'target': g_total_target,
#                     'paid': g_paid,
#                     'remaining': max(g_total_target - g_paid, 0),
#                     'percentage': round((g_paid / g_total_target * 100), 1) if g_total_target > 0 else 0
#                 })

#             heavy_stats = {
#                 "month_revenue_all": month_revenue_all,
#                 "year_revenue_all": year_revenue_all,
#                 "total_debt_combined": total_debt_combined,
#                 "total_percentage": total_percentage,
#                 "grades_efficiency": grades_efficiency,
#             }
#             cache.set(dash_cache_key, heavy_stats, 1800)
#             print("✅ اكتمل تسخين الداشبورد المالي.")

#         # ==========================================
#         # 🔥 تسخين سجل الطلاب المالي
#         # ==========================================
#         if not cache.get(student_cache_key):
#             base_query = Student.objects.filter(academic_year=current_year, is_active=True)
#             total_count_val = base_query.count()
#             assigned_count_val = base_query.filter(installments__academic_year=current_year).distinct().count()

#             filtered_student_ids = base_query.values_list('id', flat=True)

#             total_due = StudentInstallment.objects.filter(student__in=filtered_student_ids, academic_year=current_year).aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
#             total_late = StudentInstallment.objects.filter(student__in=filtered_student_ids, academic_year=current_year).aggregate(s=Sum('late_fee'))['s'] or Decimal('0.00')
#             total_paid = Payment.objects.filter(student__in=filtered_student_ids, academic_year=current_year, is_cancelled=False).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')
#             total_discount = StudentAccount.objects.filter(student__in=filtered_student_ids, academic_year=current_year).aggregate(s=Sum('discount'))['s'] or Decimal('0.00')
#             total_prev_debt = base_query.aggregate(s=Sum('previous_debt'))['s'] or Decimal('0.00')

#             remaining_sum_val = (total_prev_debt + total_due + total_late) - (total_paid + total_discount)

#             stats = {
#                 'total': total_count_val,
#                 'assigned': assigned_count_val,
#                 'paid': 0, 
#                 'debt': 0, 
#                 'total_remaining_sum': remaining_sum_val
#             }
#             cache.set(student_cache_key, stats, 1800) 
#             print("✅ اكتمل تسخين السجل المالي.")
            
#     except Exception as e:
#         print(f"حدث خطأ أثناء تسخين الكاش: {e}")


# @receiver(user_logged_in)
# def trigger_cache_warming_on_login(sender, user, request, **kwargs):
#     if user.is_superuser or user.groups.filter(name__in=["Finance_General", "Full_Access_No_Admin"]).exists():
#         thread = threading.Thread(target=background_cache_warming)
#         thread.daemon = True
#         thread.start()



# @receiver([post_save, post_delete], sender=Payment)
# def update_student_account_balance_live(sender, instance, **kwargs):
#     """
#     حارس المديونية الحية: بمجرد إضافة، تعديل، أو حذف أي إيصال (حتى من الأدمن)
#     نقوم بإخطار النظام بإعادة التحديث دون العبث بالـ properties لتجنب الـ No Setter Bug.
#     """
#     student = instance.student
#     year = instance.academic_year
    
#     if not student or not year:
#         return

#     # 1. جلب حساب الطالب المالي لهذه السنة
#     st_account = StudentAccount.objects.filter(student=student, academic_year=year).first()
    
#     # 2. إذا كان الحساب موجوداً، نقوم بعمل حفظ عادي لتحديث السجلات المرتبطة به إن وجدت
#     if st_account:
#         # نقوم بالحفظ بشكل آمن تماماً بدون محاولة الكتابة في الـ properties
#         st_account.save()

#     # 🎯 تم حذف الجزء الخاص بـ student.final_remaining = ... و student.save() تماماً
#     # لأن 'final_remaining' عبارة عن @property في موديل الطالب وتحسب نفسها ذاتياً في القوالب والواجهات.


@receiver(post_delete, sender=Payment)
def update_student_account_on_delete(sender, instance, **kwargs):
    """
    بمجرد حذف إيصال دفع، نقوم بإعادة تحديث كافة الحسابات المادية للطالب
    في جميع السنوات الدراسية بترتيبها الصحيح لضمان ترحيل المبالغ وتحديث العدادات بدقة وسرعة.
    """
    if instance.student:
        try:
            # 1. جلب حسابات الطالب مرتبة من الأقدم للأحدث لضمان صحة ترحيل الديون القديمة
            all_accounts = StudentAccount.objects.filter(
                student=instance.student
            ).order_by('academic_year__start_date')
            
            if all_accounts.exists():
                for st_account in all_accounts:
                    # ⚡ نداء دالة الحسابات الداخلية للموديل برمجياً بدون عمل save() كامل يتعب السيرفر
                    if hasattr(st_account, 'recalculate_balances'):
                        st_account.recalculate_balances() 
                    
                    # ⚡ تحديث قاعدة البيانات بضربة واحدة سريعة ومباشرة تمنع الـ Infinite Loops
                    StudentAccount.objects.filter(id=st_account.id).update(
                        previous_debt=st_account.previous_debt,
                        total_fees=st_account.total_fees,
                        discount=st_account.discount,
                        # ضيف هنا أي حقول مادية تانية بتتغير لما الإيصال بيتحذف
                    )
            
        except Exception as e:
            print(f"Error in post_delete signal: {e}")
            
        
        
