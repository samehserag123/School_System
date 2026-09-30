
import json
import time
import uuid
import re
import traceback
import datetime
import hashlib
from decimal import Decimal
from datetime import date, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponse, Http404
from django.apps import apps
from django.core.cache import cache
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.db.models import (
    CharField, Q, F, Value, Sum, Count, DecimalField, Max,
    ExpressionWrapper, Exists, Subquery, OuterRef, Case, When, IntegerField
)
from django.db.models.functions import Coalesce, Concat
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

# =========================================================
# 🟢 Django REST Framework
# =========================================================
from rest_framework import generics, filters, status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

# =========================================================
# 📦 النماذج والفورمز (Models, Forms & Serializers)
# =========================================================
from hr.models import Employee, Department
from finance.models import StudentAccount, AcademicYear, DeliveryRecord, Payment, StudentInstallment
from finance.utils import get_active_year
from treasury.models import GeneralLedger

from .models import (
    GradeItemPackage, StudentSaleRecord, SaleDeliveryDetail,
    Student, Grade, Classroom, Subject, Uniform, Teacher, SubjectPrice,
    InventoryItem, InventoryRestock, GradePackagePrice, BookSale, CourseGroup,
    CoursePayment, StudentSession, ExternalStudent, AttendanceRecord, ReEnrollmentRecord,
    SubjectConfig, ExamResult, ControlRoomConfig, StudentTermControlNumber,
    BusRoute, BusSubscription, BusPayment, MiscellaneousRevenue, RemedialFeeSetting,
    RemedialProgramRecord, StudentControlSheet, StudentAcademicHistory,
    AcademyDoctor, AcademyCourse, AcademySubject, AcademyTermSubject,
    AcademyEnrollment, AcademyLecture, AcademyAttendance, PendingAdmissionNotification
)

from .forms import (
    StudentForm, CourseGroupForm, RestockForm, BookSaleForm,
    AttendanceFilterForm, ExamResultFilterForm, RemedialProgramForm,
    AcademyEnrollmentForm
)
from .serializers import StudentSerializer, OnlineAdmissionSerializer


def get_search_variants(text):
    """
    توليد جميع احتمالات وتنوعات الحروف المتشابهة
    (الهمزات، التاء المربوطة، الياء/الألف اللينة، والواو المهموزة)
    """
    if not text:
        return []

    # 1. إزالة التشكيل والمسافات الزائدة
    clean = re.sub(r'[\u064B-\u065F\u0670]', '', text).strip()
    variants = {clean}

    # 2. توحيد الألف والهمزات والياء والتاء المربوطة
    soft_norm = re.sub(r'[أإآٱ]', 'ا', clean)
    soft_norm = re.sub(r'ة', 'ه', soft_norm)
    soft_norm = re.sub(r'[ىئ]', 'ي', soft_norm)
    variants.add(soft_norm)

    # 3. توحيد الواو المهموزة والعادية (ؤ <-> و)
    hard_norm = re.sub(r'ؤ', 'و', soft_norm)
    variants.add(hard_norm)
    waw_norm = re.sub(r'و', 'ؤ', soft_norm)
    variants.add(waw_norm)

    # 4. معالجة الأسماء المركبة (مثل: عبدالله <-> عبد الله)
    final_variants = set()
    for v in variants:
        final_variants.add(v)
        if 'عبد ' in v:
            final_variants.add(v.replace('عبد ', 'عبد'))
        if 'عبد' in v and 'عبد ' not in v:
            final_variants.add(v.replace('عبد', 'عبد '))

    return list(final_variants)


def parent_attendance_check(request):
    """
    صفحة استعلام أولياء الأمور المبتكرة والمحمية بالكامل
    آمنة وسريعة بدعم البحث اللحظي والتأمين ضد استخراج البيانات
    """
    raw_query = request.GET.get('q', '')
    clean_query = raw_query.strip()
    student_status_list = []
    today = timezone.now().date()

    # 🔒 شرط أمني وأداء: عدم تشغيل استعلام قاعدة البيانات إلا بعد كتابة حرفين على الأقل
    if len(clean_query) >= 2:
        search_variants = get_search_variants(clean_query)

        # دمج (الاسم الأول + مسافة + اسم العائلة) للاستعلام اللحظي السريع
        students = Student.objects.filter(is_active=True).annotate(
            full_name_concat=Concat('first_name', Value(' '), 'last_name', output_field=CharField())
        )

        # بناء الاستعلام لجميع الاحتمالات المتشابهة
        q_objects = Q()
        for v in search_variants:
            q_objects |= Q(full_name_concat__icontains=v)
            q_objects |= Q(search_name__icontains=v)
            q_objects |= Q(first_name__icontains=v) | Q(last_name__icontains=v)

        matched_students = students.filter(q_objects).distinct()

        # ترتيب النتائج من الأقرب للأبعد (الاسم الذي يبدأ بالبحث أولاً)
        def get_closeness_score(student):
            full_name = student.get_full_name()
            clean_s = re.sub(r'[أإآٱ]', 'ا', full_name).replace(' ', '')
            clean_q = re.sub(r'[أإآٱ]', 'ا', clean_query).replace(' ', '')

            if full_name.startswith(clean_query) or clean_s.startswith(clean_q):
                return 0
            elif clean_query in full_name or clean_q in clean_s:
                return 1
            return 2

        # 🔒 تحديد أقصى عدد للنتائج (10 طلاب كحد أقصى) لحماية البيانات وتسريع الاستجابة
        sorted_students = sorted(matched_students, key=get_closeness_score)[:10]

        # جلب سجلات الحضور والغياب لليوم الحالي دفعة واحدة O(1)
        student_ids = [s.id for s in sorted_students]
        attendances = {
            att.student_id: att
            for att in AttendanceRecord.objects.filter(student_id__in=student_ids, date=today)
        }

        for student in sorted_students:
            record = attendances.get(student.id)
            status = record.status if record else 'unmarked'
            notes = record.notes if record else ''

            student_status_list.append({
                'student': student,
                'status': status,
                'notes': notes,
            })

    response = render(request, 'students/parent_attendance_check.html', {
        'today': today,
        'query': raw_query,
        'results': student_status_list,
    })

    # 🔒 إضافة الهيدرز الأمنية لمنع التضمين والإطارات الخبيثة
    response['X-Frame-Options'] = 'DENY'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    return response


@login_required
@require_POST
def api_save_attendance_robust(request):
    """
    دالة موحدة فائقة السرعة والاعتمادية لرصد الحضور والغياب (فردي أو جماعي).
    """
    try:
        data = json.loads(request.body or '{}')
        items = data.get('items', [])

        # توحيد المعالجة إذا أُرسلت حالة طالب واحد بشكل مباشر
        if not items and 'student_id' in data:
            items = [data]

        if not items:
            return JsonResponse({'success': False, 'error': 'لا توجد بيانات صالحة للإرسال.'}, status=400)

        # 1. جلب كل الطلاب المستهدفين في استعلام واحد فقط بدلاً من التكرار داخل اللوب
        raw_ids = [item.get('student_id') for item in items if item.get('student_id')]
        students_map = {
            s.id: s for s in Student.objects.filter(id__in=raw_ids).select_related('academic_year')
        }

        active_year = get_active_year()
        today_str = str(timezone.localdate())

        saved_records = []
        errors = []

        with transaction.atomic():
            for item in items:
                student_id = item.get('student_id')
                status = item.get('status')
                date_str = item.get('date') or today_str
                term = item.get('term', 'term1')
                notes = item.get('notes', '')

                if not student_id or not status:
                    continue

                # تحويل المعرف لرقم صحيح لمطابقة قاموس البحث
                s_id = int(student_id) if str(student_id).isdigit() else student_id
                student = students_map.get(s_id)

                if not student:
                    errors.append(f'الطالب رقم #{student_id} غير موجود بالنظام.')
                    continue

                academic_year = getattr(student, 'academic_year', None) or active_year

                record, _ = AttendanceRecord.objects.update_or_create(
                    student=student,
                    date=date_str,
                    defaults={
                        'academic_year': academic_year,
                        'status': status,
                        'term': term,
                        'notes': notes
                    }
                )
                saved_records.append({'student_id': student.id, 'status': record.status})

        return JsonResponse({
            'success': True,
            'processed_count': len(saved_records),
            'records': saved_records,
            'errors': errors
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'تنسيق بيانات JSON غير صالح.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'خطأ بالسيرفر: {str(e)}'}, status=500)


# =========================================================
# 🧠 أداة توحيد الحروف العربية المتشابهة للبحث الذكي
# =========================================================
def _normalize_arabic(text):
    """
    يوحّد الحروف المتشابهة شكلاً (أ/إ/آ/ٱ -> ا، ة -> ه، ى/ئ -> ي، ؤ -> و)
    وبيشيل التشكيل، عشان البحث يلاقي الاسم حتى لو مكتوب بطريقة مختلفة شوية.
    """
    if not text:
        return ''
    text = str(text).strip()
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا',
        'ة': 'ه',
        'ى': 'ي', 'ئ': 'ي',
        'ؤ': 'و',
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)  # شيل التشكيل
    return text.lower()


def _full_name(student):
    return f"{getattr(student, 'first_name', '')} {getattr(student, 'last_name', '')}".strip() or str(student)




@login_required
def api_student_delivery_overview(request, student_id):
    """
    عرض حالة تسليم أصناف الطالب مقارنة بين مخزون صفّه الدراسي وحركات الصرف
    الفعلية المسجلة له (StockTransaction) — مصدر حقيقة موثوق 100%.
    """
    from core_inventory.models import ItemMaster, StockBalance, StockTransaction

    try:
        student = get_object_or_404(Student.objects.select_related('grade'), id=student_id)

        # ✅ مصدر الحقيقة: حركات الصرف الفعلية المسجلة لهذا الطالب بالذات
        delivered_item_ids = set(
            StockTransaction.objects.filter(
                student=student, movement_type='OUT_STUDENT'
            ).values_list('item_id', flat=True)
        )

        grade_items = ItemMaster.objects.filter(linked_grade=student.grade).select_related('category')
        if not grade_items.exists():
            grade_items = ItemMaster.objects.all().select_related('category')

        item_ids = list(grade_items.values_list('id', flat=True))

        stock_balances = (
            StockBalance.objects.filter(item_id__in=item_ids)
            .values('item_id')
            .annotate(total_stock=Coalesce(Sum('quantity_on_hand'), Value(Decimal('0.00')), output_field=DecimalField()))
        )
        stock_map = {sb['item_id']: sb['total_stock'] for sb in stock_balances}

        categories_map = {}
        for item in grade_items:
            sb_qty = stock_map.get(item.id, Decimal('0.00'))
            is_delivered = item.id in delivered_item_ids
            cat_name = str(item.category) if getattr(item, 'category', None) else 'أصناف أخرى'

            categories_map.setdefault(cat_name, []).append({
                'id': item.id,
                'name': item.name,
                'stock': float(sb_qty),
                'is_available': (sb_qty > 0) or is_delivered,
                'is_delivered': is_delivered,
            })

        categories = [
            {'category': cat, 'items': sorted(items, key=lambda x: x['name'])}
            for cat, items in sorted(categories_map.items())
        ]

        total_count = len(item_ids)
        delivered_count = len(delivered_item_ids.intersection(set(item_ids)))

        return JsonResponse({
            'success': True,
            'student_name': student.get_full_name() if hasattr(student, 'get_full_name') else str(student),
            'grade_name': student.grade.name if student.grade else '—',
            'total_count': total_count,
            'delivered_count': delivered_count,
            'categories': categories,
        })

    except Exception as e:
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'حدث خطأ في الخادم: {str(e)}'}, status=500)



@login_required
@require_POST
def api_save_student_delivery(request, student_id):
    """
    ✅ تسليم موحّد لكل تصنيفات الطالب دفعة واحدة، مع مزامنة رصيد ذاتية،
    وتحديث حالة is_delivered بالاعتماد على حركات المخزون الفعلية
    (StockTransaction) بدل حقل غير موجود بالموديل، وإرجاع الرصيد
    المتبقي فعلياً لكل صنف بعد الخصم مباشرة.
    """
    from core_inventory.models import ItemMaster, StockBalance, StockTransaction

    try:
        body = json.loads(request.body or '{}')
        selected_item_ids = body.get('selected_items', [])
        if not selected_item_ids:
            return JsonResponse({'success': False, 'error': 'يرجى تحديد صنف واحد على الأقل لتسليمه!'}, status=400)

        student = get_object_or_404(Student, id=student_id)
        eligible_sales = list(BookSale.objects.filter(student=student, status='paid'))
        if not eligible_sales:
            return JsonResponse({'success': False, 'error': 'لا يوجد إذن صرف مسدد بالكامل لهذا الطالب.'}, status=400)

        items_dict = {i.id: i for i in ItemMaster.objects.filter(id__in=selected_item_ids)}

        balances_dict = {
            b.item_id: b
            for b in StockBalance.objects.filter(item_id__in=selected_item_ids).select_related('warehouse')
        }

        # 🩹 مزامنة ذاتية لضمان دقة الرصيد (نفس الحل اللي عملناه قبل كده)
        tx_by_item_warehouse = (
            StockTransaction.objects.filter(item_id__in=selected_item_ids)
            .values('item_id', 'warehouse_id')
            .annotate(total=Coalesce(Sum(
                Case(
                    When(movement_type__in=['IN_OPENING', 'IN_PURCHASE', 'IN_RETURN', 'ADJUST'], then=F('quantity')),
                    When(movement_type__in=['OUT_STUDENT', 'OUT_DEPT', 'OUT_WASTE', 'TRANSFER'], then=-F('quantity')),
                    default=Value(Decimal('0.00')), output_field=DecimalField()
                )
            ), Decimal('0.00')))
        )
        tx_best_map = {}
        for row in tx_by_item_warehouse:
            iid, qty = row['item_id'], row['total'] or Decimal('0.00')
            if iid not in tx_best_map or qty > tx_best_map[iid]['qty']:
                tx_best_map[iid] = {'warehouse_id': row['warehouse_id'], 'qty': qty}

        balances_to_fix = []
        for iid, info in tx_best_map.items():
            if info['qty'] <= 0 or not info['warehouse_id']:
                continue
            existing = balances_dict.get(iid)
            if not existing:
                nb, created = StockBalance.objects.get_or_create(
                    item_id=iid, warehouse_id=info['warehouse_id'],
                    defaults={'quantity_on_hand': info['qty']}
                )
                if not created and nb.quantity_on_hand < info['qty']:
                    nb.quantity_on_hand = info['qty']
                    balances_to_fix.append(nb)
                balances_dict[iid] = nb
            elif existing.quantity_on_hand < info['qty']:
                existing.quantity_on_hand = info['qty']
                balances_to_fix.append(existing)

        if balances_to_fix:
            StockBalance.objects.bulk_update(balances_to_fix, ['quantity_on_hand'])

        valid_items_to_process = []
        out_of_stock = []
        for iid in selected_item_ids:
            item = items_dict.get(iid)
            if not item:
                continue
            balance = balances_dict.get(iid)
            if balance and balance.quantity_on_hand > 0:
                valid_items_to_process.append((item, balance))
            else:
                out_of_stock.append(item.name)

        if out_of_stock:
            return JsonResponse({
                'success': False,
                'error': f'🛑 تعذر التسليم! نفاذ رصيد المخزن للأصناف التالية: ({", ".join(out_of_stock)}).'
            }, status=400)

        student_name = _full_name(student)
        delivered_names = []

        # ⚡ عدد الأصناف المطلوبة لصف الطالب (يُحسب مرة واحدة قبل الحلقة لتسريع الأداء)
        total_required = ItemMaster.objects.filter(linked_grade=student.grade).count() or 1

        try:
            with transaction.atomic():
                for item, balance in valid_items_to_process:
                    # ⚡ الحفظ الطبيعي: بيتحقق من الرصيد ويحدّث StockBalance تلقائياً بنفسه
                    StockTransaction(
                        item=item,
                        warehouse=balance.warehouse,
                        movement_type='OUT_STUDENT',
                        quantity=1,
                        student=student,
                        created_by=request.user,
                        notes=f'تسليم طالب: {student_name} (شاشة موبايل موحّدة)'
                    ).save()
                    delivered_names.append(item.name)

                # ✅ مصدر الحقيقة الموثوق: حركات الصرف الفعلية بدل حقل delivered_items غير الموجود
                delivered_item_ids_for_student = set(
                    StockTransaction.objects.filter(
                        student=student, movement_type='OUT_STUDENT'
                    ).values_list('item_id', flat=True)
                )

                if len(delivered_item_ids_for_student) >= total_required:
                    BookSale.objects.filter(
                        id__in=[s.id for s in eligible_sales]
                    ).update(
                        is_delivered=True,
                        delivered_at=timezone.now(),
                        delivered_by=request.user,
                        status='delivered'
                    )

        except ValidationError as e:
            msg = "، ".join(e.messages) if hasattr(e, 'messages') else str(e)
            return JsonResponse({'success': False, 'error': f'🛑 {msg}'}, status=400)

        # ⚡ الرصيد المتبقي فعلياً بعد الخصم لكل صنف تم تسليمه (لعرضه في شاشة الموبايل)
        delivered_ids = [item.id for item, _ in valid_items_to_process]
        remaining_map = dict(
            StockBalance.objects.filter(item_id__in=delivered_ids)
            .values('item_id')
            .annotate(total=Coalesce(Sum('quantity_on_hand'), Decimal('0.00')))
            .values_list('item_id', 'total')
        )
        delivered_stock = [
            {
                'id': item.id,
                'name': item.name,
                'remaining': float(remaining_map.get(item.id, Decimal('0.00')) or Decimal('0.00')),
            }
            for item, _ in valid_items_to_process
        ]

        return JsonResponse({
            'success': True,
            'message': f'✅ تم تسليم ({len(delivered_names)}) صنف بنجاح للطالب ({student_name}).',
            'delivered_stock': delivered_stock,
        })

    except Exception as e:
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'خطأ تقني: {str(e)}'}, status=400)



# ================================================================
# ⚡ نسخة محسّنة للسرعة: مستحقون للاستلام
# ================================================================


@require_http_methods(["GET"])
def mobile_delivery_students_api(request):
    try:
        q = request.GET.get('q', '').strip()

        # 1) استعلام خفيف ومباشر يجيب معرفات الطلاب المستحقين
        student_ids = list(
            BookSale.objects.filter(status='paid', is_delivered=False)
            .values_list('student_id', flat=True)
            .distinct()
        )

        if not student_ids:
            return JsonResponse({'success': True, 'count': 0, 'students': []})

        students_qs = Student.objects.filter(id__in=student_ids).select_related('grade')

        # 2) البحث المتطور عن طريق تجزئة الكلمات (Word Splitting)
        if q:
            # التأكد من وجود دالة المعالجة بدون إحداث خطأ
            q_norm = _normalize_arabic(q) if '_normalize_arabic' in globals() else q

            # تجزئة نص البحث إلى كلمات (مثل: ["أحمد", "علي"])
            terms = q.split()
            terms_norm = q_norm.split()

            search_query = Q()

            # اشتراط وجود كل كلمة أدخلها المستخدم في أي من حقول الطالب
            for i, term in enumerate(terms):
                term_n = terms_norm[i] if i < len(terms_norm) else term

                # الكلمة الواحدة قد تكون في الاسم الأول، الثاني، الثالث، أو الأخير
                term_condition = (
                    Q(first_name__icontains=term) | Q(first_name__icontains=term_n) |
                    Q(last_name__icontains=term) | Q(last_name__icontains=term_n)
                )

                # دعم الحقول الإضافية تلقائياً إن وجدت بالموديل
                if hasattr(Student, 'second_name'):
                    term_condition |= Q(second_name__icontains=term) | Q(second_name__icontains=term_n)
                if hasattr(Student, 'third_name'):
                    term_condition |= Q(third_name__icontains=term) | Q(third_name__icontains=term_n)
                if hasattr(Student, 'student_code'):
                    term_condition |= Q(student_code__icontains=term)
                if hasattr(Student, 'national_id'):
                    term_condition |= Q(national_id__icontains=term)

                # دمج الشروط بـ AND (يجب أن توجد كل كلمة في أجزاء الاسم)
                search_query &= term_condition

            students_qs = students_qs.filter(search_query)

        # 3) تجميع المبالغ وتاريخ أحدث دفع (Bulk Aggregation)
        totals = (
            BookSale.objects.filter(student_id__in=student_ids, status='paid')
            .values('student_id')
            .annotate(
                total=Sum('total_amount'),
                last_paid_at=Max('sale_date')
            )
        )
        totals_map = {t['student_id']: t for t in totals}

        # 4) الترتيب والتجهيز
        students_list = list(students_qs)
        students_list.sort(
            key=lambda st: totals_map.get(st.id, {}).get('last_paid_at') or st.id,
            reverse=True
        )

        data = [
            {
                'student_id': st.id,
                'name': st.get_full_name() if hasattr(st, 'get_full_name') and callable(st.get_full_name) else str(st),
                'grade': str(st.grade) if getattr(st, 'grade', None) else 'غير محدد',
                'total_amount': float(totals_map.get(st.id, {}).get('total') or 0),
            }
            for st in students_list
        ]

        return JsonResponse({'success': True, 'count': len(data), 'students': data})

    except Exception as e:
        return JsonResponse(
            {'success': False, 'message': 'حدث خطأ أثناء جلب البيانات', 'error': str(e)},
            status=500
        )


# @require_http_methods(["GET"])
# def mobile_delivery_students_api(request):
#     q = request.GET.get('q', '').strip()

#     # 1) استعلام خفيف مباشر يجيب معرفات الطلاب المستحقين فقط
#     student_ids = list(
#         BookSale.objects.filter(status='paid', is_delivered=False)
#         .values_list('student_id', flat=True).distinct()
#     )

#     if not student_ids:
#         return JsonResponse({'success': True, 'count': 0, 'students': []})

#     students_qs = Student.objects.filter(id__in=student_ids).select_related('grade')

#     if q:
#         q_norm = _normalize_arabic(q)
#         students_qs = students_qs.filter(
#             Q(first_name__icontains=q) | Q(last_name__icontains=q) |
#             Q(first_name__icontains=q_norm) | Q(last_name__icontains=q_norm)
#         )

#     # 2) استعلام تجميع واحد للمبالغ وآخر تاريخ دفع لكل الطلاب دفعة واحدة (بدل Subquery لكل صف)
#     totals = (
#         BookSale.objects.filter(student_id__in=student_ids, status='paid')
#         .values('student_id')
#         .annotate(total=Sum('total_amount'), last_paid_at=Max('sale_date'))
#     )
#     totals_map = {t['student_id']: t for t in totals}

#     students_list = list(students_qs)
#     students_list.sort(
#         key=lambda st: totals_map.get(st.id, {}).get('last_paid_at') or st.id,
#         reverse=True
#     )

#     data = [
#         {
#             'student_id': st.id,
#             'name': st.get_full_name() if hasattr(st, 'get_full_name') else str(st),
#             'grade': str(st.grade) if getattr(st, 'grade', None) else 'غير محدد',
#             'total_amount': float(totals_map.get(st.id, {}).get('total') or 0),
#         }
#         for st in students_list
#     ]

#     return JsonResponse({'success': True, 'count': len(data), 'students': data})


# ================================================================
# ⚡ نسخة محسّنة للسرعة: تم التسليم
# ================================================================
@require_http_methods(["GET"])
def mobile_delivered_students_api(request):
    q = request.GET.get('q', '').strip()

    pending_ids = set(BookSale.objects.filter(status='paid', is_delivered=False).values_list('student_id', flat=True))
    delivered_ids = set(BookSale.objects.filter(is_delivered=True).values_list('student_id', flat=True))
    done_ids = list(delivered_ids - pending_ids)

    if not done_ids:
        return JsonResponse({'success': True, 'count': 0, 'students': []})

    students_qs = Student.objects.filter(id__in=done_ids).select_related('grade').order_by('first_name', 'last_name')

    if q:
        q_norm = _normalize_arabic(q)
        students_qs = students_qs.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(first_name__icontains=q_norm) | Q(last_name__icontains=q_norm)
        )

    last_delivered_map = dict(
        BookSale.objects.filter(student_id__in=done_ids, is_delivered=True)
        .values('student_id').annotate(last=Max('delivered_at'))
        .values_list('student_id', 'last')
    )

    data = [
        {
            'student_id': st.id,
            'name': st.get_full_name() if hasattr(st, 'get_full_name') else str(st),
            'grade': str(st.grade) if getattr(st, 'grade', None) else 'غير محدد',
            'delivered_at': last_delivered_map.get(st.id).strftime('%Y-%m-%d %H:%M') if last_delivered_map.get(st.id) else '—',
        }
        for st in students_qs
    ]

    return JsonResponse({'success': True, 'count': len(data), 'students': data})


# ================================================================
# ⚡ نسخة محسّنة للسرعة: المخزون (بدون تجميع كل حركات StockTransaction)
#    الاعتماد فقط على StockBalance المتزامن تلقائياً مع كل عملية حفظ
# ================================================================
@login_required
def mobile_inventory_stock_api(request):
    from core_inventory.models import ItemMaster, StockBalance

    q = request.GET.get('q', '').strip()
    items_qs = ItemMaster.objects.select_related('category').all()

    if q:
        q_norm = _normalize_arabic(q)
        items_qs = items_qs.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) | Q(name__icontains=q_norm)
        )

    item_ids = list(items_qs.values_list('id', flat=True))

    stock_balance_map = dict(
        StockBalance.objects.filter(item_id__in=item_ids)
        .values('item_id').annotate(total=Coalesce(Sum('quantity_on_hand'), Decimal('0.00')))
        .values_list('item_id', 'total')
    ) if item_ids else {}

    LOW_STOCK_THRESHOLD = 10
    categories_map = {}
    available_count = low_count = out_count = 0

    for item in items_qs:
        stock_qty = float(stock_balance_map.get(item.id, Decimal('0.00')) or Decimal('0.00'))
        if stock_qty <= 0:
            status = 'out'; out_count += 1
        elif stock_qty <= LOW_STOCK_THRESHOLD:
            status = 'low'; low_count += 1
        else:
            status = 'ok'; available_count += 1

        cat_name = item.category.name if item.category else 'أصناف أخرى'
        categories_map.setdefault(cat_name, []).append({
            'id': item.id, 'name': item.name, 'sku': item.sku or '',
            'stock': stock_qty, 'status': status,
        })

    categories = [
        {'category': c, 'items': sorted(i, key=lambda x: x['name'])}
        for c, i in sorted(categories_map.items())
    ]

    return JsonResponse({
        'success': True,
        'categories': categories,
        'total_items': len(item_ids),
        'summary': {
            'total': len(item_ids),
            'available': available_count,
            'low': low_count,
            'out': out_count,
        }
    })


@require_http_methods(["GET"])
def student_delivery_overview_api(request, student_id):
    try:
        student = get_object_or_404(Student, id=student_id)
        st_name = student.get_full_name() if hasattr(student, 'get_full_name') else str(student)
        grade_name = str(student.grade) if hasattr(student, 'grade') and student.grade else 'غير محدد'

        # جلب جميع مبيعات الطالب
        sales = BookSale.objects.filter(student=student).select_related('item')

        total_count = sales.count()
        delivered_count = sales.filter(is_delivered=True).count()
        categories_dict = {}

        for sale in sales:
            item_obj = sale.item
            item_name = getattr(item_obj, 'name', str(sale)) if item_obj else f"صنف مبيعات #{sale.id}"

            cat_name = "مستلزمات وأصناف الطالب"
            if item_obj and hasattr(item_obj, 'category') and item_obj.category:
                cat_name = str(item_obj.category)

            if cat_name not in categories_dict:
                categories_dict[cat_name] = []

            stock_qty = getattr(item_obj, 'quantity', getattr(item_obj, 'stock', 0)) if item_obj else 0

            categories_dict[cat_name].append({
                'id': sale.id,
                'name': item_name,
                'stock': stock_qty,
                'is_available': stock_qty >= getattr(sale, 'quantity', 1),
                'is_delivered': sale.is_delivered,
            })

        formatted_categories = [
            {'category': cat_name, 'items': items}
            for cat_name, items in categories_dict.items()
        ]

        return JsonResponse({
            'success': True,
            'student_name': st_name,
            'grade_name': grade_name,
            'total_count': total_count,
            'delivered_count': delivered_count,
            'categories': formatted_categories,
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)




@require_http_methods(["POST"])
def save_student_delivery_api(request, student_id):
    try:
        student = get_object_or_404(Student, id=student_id)
        body = json.loads(request.body)
        selected_ids = body.get('selected_items', [])

        if not selected_ids:
            return JsonResponse({'success': False, 'error': 'لم يتم تحديد أي أصناف.'}, status=400)

        with transaction.atomic():
            sales = BookSale.objects.filter(id__in=selected_ids, student=student)

            if sales.exists():
                for sale in sales:
                    item_obj = sale.item
                    if item_obj:
                        stock_qty = getattr(item_obj, 'quantity', getattr(item_obj, 'stock', 0))
                        if stock_qty < sale.quantity:
                            raise ValueError(f"الرصيد غير كافٍ للصنف {item_obj}.")

                        if hasattr(item_obj, 'quantity'):
                            item_obj.quantity -= sale.quantity
                        elif hasattr(item_obj, 'stock'):
                            item_obj.stock -= sale.quantity
                        item_obj.save()

                    sale.is_delivered = True
                    sale.delivered_at = timezone.now()
                    if request.user.is_authenticated:
                        sale.delivered_by = request.user
                    sale.save()
            else:
                items = InventoryItem.objects.filter(id__in=selected_ids)
                for item_obj in items:
                    stock_qty = getattr(item_obj, 'quantity', getattr(item_obj, 'stock', 0))
                    if stock_qty <= 0:
                        raise ValueError(f"الرصيد غير كافٍ للصنف {item_obj}.")

                    if hasattr(item_obj, 'quantity'):
                        item_obj.quantity -= 1
                    elif hasattr(item_obj, 'stock'):
                        item_obj.stock -= 1
                    item_obj.save()

                    BookSale.objects.create(
                        student=student,
                        item=item_obj,
                        quantity=1,
                        is_delivered=True,
                        delivered_at=timezone.now(),
                        delivered_by=request.user if request.user.is_authenticated else None
                    )

        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)





@login_required
@require_POST
def api_confirm_sale_delivery(request, student_id):
    """
    تأكيد تسليم أصناف ItemMaster المحددة للطالب وخصمها من المخزن مع تحديث حالة إذن البيع.
    """
    import json
    from django.utils import timezone
    from core_inventory.models import ItemMaster, StockBalance, StockTransaction, Warehouse
    from students.models import Student, BookSale

    try:
        data = json.loads(request.body or '{}')
        selected_item_ids = data.get('item_ids', []) or data.get('selected_items', [])

        if not selected_item_ids:
            return JsonResponse({'success': False, 'error': 'لم يتم تحديد أي أصناف للتسليم!'}, status=400)

        student = get_object_or_404(Student, id=student_id)
        items_to_deliver = ItemMaster.objects.filter(id__in=selected_item_ids)

        insufficient_items = []
        item_warehouse_map = {}
        default_warehouse = Warehouse.objects.filter(is_active=True).first()

        # فحص توفر الكميات لكل صنف ItemMaster
        for item in items_to_deliver:
            sb_qty = StockBalance.objects.filter(item=item).aggregate(
                total=Coalesce(Sum('quantity_on_hand'), Decimal('0.00'))
            )['total'] or Decimal('0.00')

            if sb_qty < Decimal('1.00'):
                insufficient_items.append(item.name)
            else:
                balances = StockBalance.objects.filter(item=item, quantity_on_hand__gt=0).order_by('-quantity_on_hand')
                target_wh = balances.first().warehouse if balances.exists() else default_warehouse
                item_warehouse_map[item.id] = target_wh

        if insufficient_items:
            items_str = "، ".join(insufficient_items)
            return JsonResponse({
                'success': False,
                'error': f'تعذر التسليم! نفاذ رصيد المخزن للأصناف التالية: ({items_str}).'
            }, status=400)

        # تنفيذ خصم المخزن وتحديث حالة الإذن
        with transaction.atomic():
            delivered_count = 0
            for item in items_to_deliver:
                target_wh = item_warehouse_map.get(item.id)
                if target_wh:
                    StockTransaction.objects.create(
                        item=item,
                        warehouse=target_wh,
                        movement_type='OUT_STUDENT',
                        quantity=Decimal('1.00'),
                        student=student,
                        created_by=request.user,
                        notes=f"تسليم طالب: {student.get_full_name()}"
                    )
                    delivered_count += 1

            # تحديث حالة إذن البيع الخاص بالطالب
            BookSale.objects.filter(student=student).update(
                is_delivered=True,
                delivered_at=timezone.now(),
                delivered_by=request.user,
                status='delivered'
            )

        return JsonResponse({
            'success': True,
            'message': f'✅ تم تسليم {delivered_count} صنف بنجاح للطالب {student.get_full_name()}.'
        })

    except Exception as e:
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'حدث خطأ في الخادم: {str(e)}'}, status=500)



@login_required
def mobile_delivery_list(request):
    """
    📱 صفحة موبايل لموظف المخزن: تعرض فقط الطلاب المستحقين للاستلام
    (سددوا المبلغ بالكامل status='paid') ولسه ما استلموش (is_delivered=False).
    """
    from django.db.models import Q

    eligible_sales = (
        BookSale.objects
        .filter(status='paid', is_delivered=False)
        .select_related('student', 'student__grade', 'item')
        .order_by('-sale_date')
    )

    q = request.GET.get('q', '').strip()
    if q:
        # 🟡 لو اسم الطالب في موديل Student مخزن بحقل مختلف (مش get_full_name)
        #    قولّي الاسم بالظبط عشان أضيف البحث بيه هنا كمان.
        eligible_sales = eligible_sales.filter(
            Q(student__id__icontains=q) |
            Q(student__grade__name__icontains=q)
        )

    return render(request, 'students/mobile_delivery.html', {
        'eligible_sales': eligible_sales,
        'total_count': eligible_sales.count(),
        'search_q': q,
    })


# 1️⃣ API جلب تفاصيل تسليم الأصناف ورصيد المخزن المتاح
def delivery_details_api(request, sale_id):
    try:
        # جلب إذن تسليم الطالب
        sale_record = get_object_or_404(
            StudentSaleRecord.objects.select_related('student', 'student__grade'),
            pk=sale_id
        )
        student = sale_record.student

        # جلب تفاصيل الأصناف (Checklist) الخاصة بطلب التسليم
        details = sale_record.delivery_details.select_related('item').all()

        items_data = []
        delivered_count = 0

        for detail in details:
            if detail.is_delivered:
                delivered_count += 1

            # إجمالي الرصيد المتاح للصنف عبر كافة المستودعات
            stock_qty = StockBalance.objects.filter(
                item=detail.item
            ).aggregate(total=Sum('quantity_on_hand'))['total'] or 0

            items_data.append({
                'id': detail.id,
                'item_id': detail.item.id,
                'name': detail.item.name,
                'sku': detail.item.sku,
                'is_delivered': detail.is_delivered,
                'stock': float(stock_qty),
                'is_available': stock_qty > 0
            })

        return JsonResponse({
            'success': True,
            'student_name': student.get_full_name(),
            'grade_name': student.grade.name if student.grade else 'غير محدد',
            'specialization': getattr(student, 'specialization', 'عام') or 'عام',
            'item_type_label': sale_record.get_sale_type_display(),
            'delivered_count': delivered_count,
            'total_count': details.count(),
            'items': items_data
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


# 2️⃣ API حفظ عملية التسليم الجزئي/الكلي وإنشاء حركات المخزون
@require_http_methods(["POST"])
def save_delivery_api(request, sale_id):
    try:
        data = json.loads(request.body)
        selected_detail_ids = data.get('selected_items', [])

        if not selected_detail_ids:
            return JsonResponse({'success': False, 'error': 'يرجى تحديد صنف واحد على الأقل للتسليم!'}, status=400)

        sale_record = get_object_or_404(StudentSaleRecord, pk=sale_id)

        with transaction.atomic():
            # جلب العناصر المحددة للتسليم والتي لم تُسلم بعد
            details_to_update = SaleDeliveryDetail.objects.filter(
                sale_record=sale_record,
                id__in=selected_detail_ids,
                is_delivered=False
            ).select_related('item')

            main_warehouse = Warehouse.objects.filter(is_active=True).first()

            for detail in details_to_update:
                # 1. تحديث حالة التسليم للتفصيلة
                detail.is_delivered = True
                detail.delivered_at = timezone.now()
                detail.delivered_by = request.user if request.user.is_authenticated else None
                detail.save()

                # 2. تسجبل حركة خصم مخزني من المستودع المتاح
                if main_warehouse:
                    StockTransaction.objects.create(
                        movement_type='OUT_STUDENT',
                        item=detail.item,
                        warehouse=main_warehouse,
                        quantity=1,
                        student=sale_record.student,
                        created_by=request.user,
                        notes=f"تسليم بموجب إذن صرف رقم #{sale_record.id}"
                    )

            # 3. تحديث حالة الإذن الرئيسي إذا تمت كل التسليمات
            all_delivered = not sale_record.delivery_details.filter(is_delivered=False).exists()
            if all_delivered:
                sale_record.is_fully_delivered = True
                sale_record.save()

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def ajax_collect_reenrollment_fee(request):
    """تحصيل رسوم إدارية/إعادة قيد وإرسال إشعار آلي لشئون الطلاب"""
    try:
        student_id = request.POST.get('student_id')
        amount = Decimal(request.POST.get('amount', '0.00'))
        notes = request.POST.get('notes', '').strip()

        student = get_object_or_404(Student, id=student_id)

        with transaction.atomic():
            # 1. تسجيل الإيراد في الخزينة العامة
            try:
                from treasury.models import GeneralLedger
            except ImportError:
                from finance.models import GeneralLedger

            receipt_code = f"RE-{student.id}-{int(time.time())}"
            GeneralLedger.objects.create(
                student=student,
                amount=amount,
                category='other', # تصنيف: إيرادات أخرى / إدارية
                notes=f"رسوم إدارية/إعادة قيد - {notes}",
                receipt_number=receipt_code,
                date=timezone.now(),  # 🟢 هذا الحقل كان ينقصنا وتسبب في تعطل السيرفر!
                collected_by=request.user
            )

            # 2. السحر هنا 🪄: إرسال الإشعار المالي لشاشة شئون الطلاب أوتوماتيكياً
            current_datetime = timezone.localtime().strftime('%Y-%m-%d %I:%M %p')
            alert_msg = f"🟢 [إشعار سداد من الخزينة - {current_datetime}]: تم تحصيل مبلغ {amount} ج.م (إيصال {receipt_code}). السبب: {notes}."

            # إضافة الإشعار فوق الملاحظات القديمة ليظهر أحدث شيء بالأعلى
            if student.enrollment_notes:
                student.enrollment_notes = alert_msg + "\n---\n" + student.enrollment_notes
            else:
                student.enrollment_notes = alert_msg

            student.save()

        return JsonResponse({'success': True, 'message': 'تم التحصيل وتسجيل الإيراد بالخزينة، وإرسال الإشعار لشئون الطلاب بنجاح.'})
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)})



@login_required
def delete_pending_notification(request, pk):
    """دالة لحذف إشعار تقديم طالب واحد (رفض الطلب)"""
    if not request.user.is_staff:
        messages.error(request, "غير مصرح لك بإجراء هذه العملية.")
        return redirect('talaat_harb_home')

    notification = get_object_or_404(PendingAdmissionNotification, id=pk)
    student_name = notification.full_name_ar
    notification.delete()

    messages.success(request, f"🗑️ تم رفض وحذف إشعار الطالب ({student_name}) بنجاح.")
    return redirect('pending_admissions_list')

@login_required
def delete_all_pending_notifications(request):
    """دالة لحذف جميع الإشعارات المعلقة دفعة واحدة"""
    if not request.user.is_staff:
        messages.error(request, "غير مصرح لك بإجراء هذه العملية.")
        return redirect('talaat_harb_home')

    # نحذف فقط الإشعارات التي لم تتم معالجتها (المعلقة)
    pending_notes = PendingAdmissionNotification.objects.filter(is_processed=False)
    count = pending_notes.count()

    if count > 0:
        pending_notes.delete()
        messages.success(request, f"🗑️ تم رفض وحذف جميع الإشعارات المعلقة ({count} طلب) بنجاح.")
    else:
        messages.info(request, "لا توجد إشعارات معلقة لحذفها.")

    return redirect('pending_admissions_list')


def pending_admissions_list(request):
    """شاشة عرض طلبات الالتحاق المقبولة من البوابة الخارجية والجاهزة للتسجيل"""
    # نجلب الطلبات التي لم يتم تسجيلها بعد
    notifications = PendingAdmissionNotification.objects.filter(is_processed=False).order_by('-received_at')

    context = {
        'notifications': notifications,
        'notifications_count': notifications.count()
    }
    return render(request, 'students/pending_notifications.html', context)


@csrf_exempt
def api_receive_approved_student(request):
    """API لاستقبال الطلاب المقبولين من بوابة التقديم الخارجية (مع دعم استقبال الصور)"""
    if request.method == 'POST':
        # 🛡️ الحماية الصارمة: يجب أن يتطابق التوكن حرفياً مع ما يرسله السيرفر الخارجي
        auth_header = request.headers.get('Authorization')

        # 🟢 التعديل هنا: مطابقة التوكن السري
        if auth_header != "Token TalaatHarb_SecureToken_2026_X9":
            return JsonResponse({'success': False, 'error': 'Unauthorized - Invalid Token'}, status=403)

        try:
            # 🟢 التعديل الجوهري: دعم قراءة البيانات والصور (Form-Data) بدلاً من JSON فقط
            if request.content_type and 'application/json' in request.content_type:
                data = json.loads(request.body)
                files = {}
            else:
                data = request.POST
                files = request.FILES

            # حفظ البيانات كإشعار جديد معلق
            notification, created = PendingAdmissionNotification.objects.update_or_create(
                national_id=data.get('national_id'),
                defaults={
                    'full_name_ar': data.get('full_name_ar') or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
                    'phone': data.get('phone'),
                    'whatsapp_number': data.get('whatsapp_number'),
                    'gender': data.get('gender'),
                    'birth_date': data.get('birth_date') or None,
                    'birth_governorate': data.get('birth_governorate'),
                    'address': data.get('address'),
                    'current_qualification': data.get('current_qualification'),
                    'is_processed': False # إرجاعه كمعلق في حال تم إرساله مجدداً
                }
            )

            # 🟢 استلام وحفظ الصور المرفقة من موقع التقديم الخارجي
            if 'student_photo' in files:
                notification.student_photo = files['student_photo']
            if 'parent_id_photo' in files:
                notification.parent_id_photo = files['parent_id_photo']
            if 'birth_certificate' in files:
                notification.birth_certificate = files['birth_certificate']
            if 'qualification_photo' in files:
                notification.qualification_photo = files['qualification_photo']
            if 'national_id_photo' in files:
                notification.national_id_photo = files['national_id_photo']

            notification.save()

            return JsonResponse({'success': True, 'message': 'Data and images received successfully.'}, status=200)
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)


@login_required
def api_academy_courses_for_term(request):
    """📋 يرجّع الأقسام (الدبلومات) اللي عندها فعلاً مواد مسكّنة في التيرم المحدد بس"""
    term_number = request.GET.get('term_number')
    if not term_number:
        return JsonResponse({'success': False, 'courses': []})

    course_ids = AcademyTermSubject.objects.filter(
        term_number=term_number
    ).values_list('course_id', flat=True).distinct()

    courses = AcademyCourse.objects.filter(id__in=course_ids).order_by('name')
    data = [{'id': c.id, 'name': c.name} for c in courses]
    return JsonResponse({'success': True, 'courses': data})


@login_required
def api_academy_subjects_for_term_course(request):
    """📋 يرجّع المواد والدكاترة الخاصة بالقسم في التيرم المحدد بس"""
    term_number = request.GET.get('term_number')
    course_id = request.GET.get('course_id')
    if not term_number or not course_id:
        return JsonResponse({'success': False, 'subjects': []})

    items = AcademyTermSubject.objects.filter(
        term_number=term_number, course_id=course_id
    ).select_related('subject', 'doctor').order_by('subject__name')

    data = [{
        'id': ts.id,
        'subject_name': ts.subject.name,
        'doctor_name': ts.doctor.name,
    } for ts in items]
    return JsonResponse({'success': True, 'subjects': data})


@login_required
def academy_study_plan_view(request):
    """شاشة الخطة الدراسية وتسكين المواد"""
    course_id = request.GET.get('course_id')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_term_subject':
            c_id = request.POST.get('course')
            term_num = request.POST.get('term_number')
            s_id = request.POST.get('subject')
            d_id = request.POST.get('doctor')

            if c_id and term_num and s_id and d_id:
                AcademyTermSubject.objects.get_or_create(
                    course_id=c_id,
                    term_number=term_num,
                    subject_id=s_id,
                    doctor_id=d_id
                )
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'success'})
                messages.success(request, "✅ تم تسكين المادة والدكتور بالتيرم بنجاح.")
                return redirect(f"{request.path}?course_id={c_id}")

        elif action == 'delete_term_subject':
            ts_id = request.POST.get('ts_id')
            AcademyTermSubject.objects.filter(id=ts_id).delete()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success'})
            messages.success(request, "🗑️ تم حذف تسكين المادة من الخطة الدراسية.")
            return redirect(f"{request.path}?course_id={course_id}" if course_id else request.path)

    courses = AcademyCourse.objects.all()
    selected_course = AcademyCourse.objects.filter(id=course_id).first() if course_id else courses.first()

    term_subjects_qs = AcademyTermSubject.objects.select_related('course', 'subject', 'doctor')
    if selected_course:
        term_subjects_qs = term_subjects_qs.filter(course=selected_course)

    terms_data = []
    for term_num, term_label in AcademyTermSubject.TERM_CHOICES:
        items = term_subjects_qs.filter(term_number=term_num)
        terms_data.append({'num': term_num, 'label': term_label, 'items': items})

    subjects = AcademySubject.objects.all()
    doctors = AcademyDoctor.objects.all()

    context = {
        'courses': courses,
        'selected_course': selected_course,
        'terms_data': terms_data,
        'subjects': subjects,
        'doctors': doctors,
        'term_choices': AcademyTermSubject.TERM_CHOICES,
        'title': 'الخطة الدراسية - تسكين المواد'
    }
    return render(request, 'students/academy_study_plan.html', context)


@login_required
def academy_attendance_sheet_view(request):
    """شاشة رصد غياب وحضور الطلاب"""
    ts_id = request.GET.get('term_subject_id')
    lecture_date_str = request.GET.get('lecture_date') or timezone.now().date().strftime('%Y-%m-%d')

    selected_ts = None
    lecture = None
    students_data = []
    stats = {'total': 0, 'present': 0, 'absent': 0, 'rate': 0}

    if ts_id:
        selected_ts = get_object_or_404(
            AcademyTermSubject.objects.select_related('course', 'subject', 'doctor'),
            id=ts_id
        )

        lecture, _ = AcademyLecture.objects.get_or_create(
            term_subject=selected_ts,
            lecture_date=lecture_date_str,
            defaults={'title': f"محاضرة {selected_ts.subject.name} - {lecture_date_str}"}
        )

        enrollments = AcademyEnrollment.objects.filter(
            course=selected_ts.course,
            is_graduated=False
        ).select_related('student')

        if request.method == 'POST':
            with transaction.atomic():
                for enr in enrollments:
                    st_val = request.POST.get(f'status_{enr.id}', 'present')
                    AcademyAttendance.objects.update_or_create(
                        enrollment=enr,
                        lecture=lecture,
                        defaults={'status': st_val}
                    )
            # إرسال رد صامت (بدون HTML) لكي لا ترمش الصفحة (AJAX)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success'})

            messages.success(request, f"✅ تم حفظ الكشف بنجاح.")
            return redirect(f"{request.path}?term_subject_id={ts_id}&lecture_date={lecture_date_str}")

        attendances = AcademyAttendance.objects.filter(lecture=lecture).values('enrollment_id', 'status')
        att_map = {a['enrollment_id']: a['status'] for a in attendances}

        present_cnt = 0
        absent_cnt = 0

        for enr in enrollments:
            st_status = att_map.get(enr.id, 'present')
            if st_status == 'present':
                present_cnt += 1
            else:
                absent_cnt += 1

            students_data.append({
                'enrollment_id': enr.id,
                'student_name': enr.student.get_full_name(),
                'student_code': getattr(enr.student, 'student_code', '') or getattr(enr.student, 'national_id', '---'),
                'status': st_status
            })

        total_cnt = len(students_data)
        rate = int((present_cnt / total_cnt) * 100) if total_cnt > 0 else 0
        stats = {'total': total_cnt, 'present': present_cnt, 'absent': absent_cnt, 'rate': rate}

    term_subjects = AcademyTermSubject.objects.select_related('course', 'subject', 'doctor').all()

    context = {
        'term_subjects': term_subjects,
        'selected_ts': selected_ts,
        'lecture_date': lecture_date_str,
        'lecture': lecture,
        'students_data': students_data,
        # 'term_choices': AcademyTermSubject.TERM_CHOICES, # قم بتفعيلها إذا كنت تستخدم الفلتر المتدرج
        'stats': stats,
        'title': 'رصد غياب وحضور الطلاب'
    }
    return render(request, 'students/academy_attendance_sheet.html', context)


@login_required
def academy_lectures_list_view(request):
    """
    شاشة رصد الحضور والتسجيل المباشر بالمادة والدكتور والتيرم
    """
    if request.method == 'POST':
        term_subject_id = request.POST.get('term_subject')
        lecture_date = request.POST.get('lecture_date')

        if term_subject_id and lecture_date:
            term_subject = get_object_or_404(AcademyTermSubject, id=term_subject_id)
            auto_title = f"محاضرة {term_subject.subject.name} - {lecture_date}"

            lecture, created = AcademyLecture.objects.get_or_create(
                term_subject=term_subject,
                lecture_date=lecture_date,
                defaults={'title': auto_title}
            )
            messages.success(
                request,
                f"✅ تم فتح كشف حضور مادة ({term_subject.subject.name}) للدكتور ({term_subject.doctor.name}) - تيرم ({term_subject.term_number})."
            )
            return redirect('take_lecture_attendance', lecture_id=lecture.id)
        else:
            messages.error(request, "⚠️ يرجى اختيار المادة والدكتور وتاريخ المحاضرة بشكل صحيح.")

    lectures = AcademyLecture.objects.select_related(
        'term_subject__course', 'term_subject__subject', 'term_subject__doctor'
    ).order_by('-lecture_date', '-id')

    term_subjects = AcademyTermSubject.objects.select_related('course', 'subject', 'doctor').all()

    context = {
        'lectures': lectures,
        'term_subjects': term_subjects,
        'title': 'رصد الحضور والغياب حسب المادة والدكتور والتيرم'
    }
    return render(request, 'students/academy_lectures_list.html', context)


@login_required
def take_lecture_attendance_view(request, lecture_id):
    """
    شاشة رصد حضور وغياب المحاضرة المحددة
    """
    lecture = get_object_or_404(
        AcademyLecture.objects.select_related('term_subject__course', 'term_subject__subject', 'term_subject__doctor'),
        id=lecture_id
    )

    # 1. جلب جميع الطلاب المسجلين بالدبلومة (الذين لم يتخرجوا بعد)
    enrollments = AcademyEnrollment.objects.filter(
        course=lecture.term_subject.course,
        is_graduated=False
    ).select_related('student')

    if request.method == 'POST':
        with transaction.atomic():
            for enr in enrollments:
                status_val = request.POST.get(f'status_{enr.id}', 'present')

                AcademyAttendance.objects.update_or_create(
                    enrollment=enr,
                    lecture=lecture,
                    defaults={'status': status_val}
                )
        messages.success(request, f"✅ تم حفظ كشف حضور محاضرة ({lecture.title}) بنجاح.")
        return redirect('academy_lectures_list')

    existing_attendance = AcademyAttendance.objects.filter(lecture=lecture).values('enrollment_id', 'status')
    attendance_map = {att['enrollment_id']: att['status'] for att in existing_attendance}

    students_list = []
    for enr in enrollments:
        students_list.append({
            'enrollment_id': enr.id,
            'student_name': enr.student.get_full_name(),
            'student_code': enr.student.student_code or '---',
            'status': attendance_map.get(enr.id, 'present')
        })

    context = {
        'lecture': lecture,
        'students_list': students_list,
        'title': f"رصد حضور: {lecture.title}"
    }
    return render(request, 'students/take_lecture_attendance.html', context)


@login_required
def academy_dashboard_view(request):
    """الشاشة الرئيسية لإدارة الأكاديميات متوافقة مع هيكل التيرمات والمواد والدكاترة"""

    if request.GET.get('ajax') == '1':
        qs = AcademyEnrollment.objects.select_related(
            'student', 'course'
        ).prefetch_related('course__term_subjects__doctor').order_by('-enrollment_date')

        q = request.GET.get('q', '').strip()
        time_filter = request.GET.get('time_filter', 'all')
        course_id = request.GET.get('course_id')
        doctor_id = request.GET.get('doctor_id')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        page_number = request.GET.get('page', 1)
        now = timezone.now()

        if q:
            qs = qs.annotate(
                full_name_db=Concat('student__first_name', Value(' '), 'student__last_name', output_field=CharField())
            ).filter(
                Q(student__first_name__icontains=q) |
                Q(student__last_name__icontains=q) |
                Q(full_name_db__icontains=q) |
                Q(student__student_code__icontains=q) |
                Q(student__national_id__icontains=q)
            )

        if date_from and date_to:
            qs = qs.filter(enrollment_date__range=[date_from, date_to])
        elif time_filter == 'today':
            qs = qs.filter(enrollment_date=now.date())
        elif time_filter == 'week':
            qs = qs.filter(enrollment_date__gte=now.date() - timedelta(days=7))
        elif time_filter == 'month':
            qs = qs.filter(enrollment_date__gte=now.date() - timedelta(days=30))

        if course_id:
            qs = qs.filter(course_id=course_id)
        if doctor_id:
            qs = qs.filter(course__term_subjects__doctor_id=doctor_id).distinct()

        paginator = Paginator(qs, 20)
        page_obj = paginator.get_page(page_number)

        enrollments_data = []
        for e in page_obj.object_list:
            doctors_list = list(e.course.term_subjects.values_list('doctor__name', flat=True).distinct())
            doctors_str = ", ".join(doctors_list) if doctors_list else "نخبة المحاضرين"

            enrollments_data.append({
                'id': e.id,
                'student_name': e.student.get_full_name(),
                'student_first_letter': e.student.get_full_name()[:1] if e.student.get_full_name() else 'ط',
                'student_code': e.student.student_code or '---',
                'national_id': e.student.national_id or '---',
                'course_name': e.course.name,
                'doctor_name': doctors_str,
                'enrollment_date': e.enrollment_date.strftime('%Y-%m-%d'),
                'is_graduated': e.is_graduated,
            })

        page_range = list(paginator.get_elided_page_range(number=page_obj.number, on_each_side=1, on_ends=1))

        return JsonResponse({
            'total_students': qs.values('student').distinct().count(),
            'total_graduates': qs.filter(is_graduated=True).count(),
            'active_courses': AcademyCourse.objects.count(),
            'enrollments': enrollments_data,
            'pagination': {
                'current_page': page_obj.number,
                'num_pages': paginator.num_pages,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'previous_page_number': page_obj.previous_page_number() if page_obj.has_previous() else None,
                'next_page_number': page_obj.next_page_number() if page_obj.has_next() else None,
                'page_range': [str(p) for p in page_range],
            }
        })

    if request.method == 'POST':
        form = AcademyEnrollmentForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                enrollment = form.save()
                pay_now = form.cleaned_data.get('pay_now') or Decimal('0.00')
                receipt_number = form.cleaned_data.get('receipt_number') or ''
                notes = form.cleaned_data.get('notes') or ''

                if pay_now > Decimal('0.00'):
                    from treasury.models import GeneralLedger
                    receipt_code = receipt_number.strip() if receipt_number.strip() else f"ACAD-{enrollment.id}-{int(time.time())}"

                    GeneralLedger.objects.create(
                        student=enrollment.student,
                        amount=pay_now,
                        category='كورس',
                        notes=f"تحصيل رسوم دبلومة أكاديمية: {enrollment.course.name} - {notes}",
                        receipt_number=receipt_code,
                        collected_by=request.user
                    )

            messages.success(request, f"✅ تم تسجيل المتدرب ({enrollment.student.get_full_name()}) وحفظ مبلغ ({pay_now} ج.م) بالخزينة بنجاح.")
            return redirect('academy_dashboard')
        else:
            messages.error(request, "⚠️ يرجى التأكد من اختيار الطالب والدبلومة بشكل صحيح.")
    else:
        form = AcademyEnrollmentForm()

    qs_all = AcademyEnrollment.objects.select_related(
        'student', 'course'
    ).prefetch_related('course__term_subjects__doctor').order_by('-enrollment_date')

    paginator = Paginator(qs_all, 20)
    page_obj = paginator.get_page(1)

    courses_qs = AcademyCourse.objects.all()
    course_prices_dict = {c.id: float(c.base_price) for c in courses_qs}

    context = {
        'form': form,
        'enrollments': page_obj,
        'total_students': qs_all.values('student').distinct().count(),
        'total_graduates': qs_all.filter(is_graduated=True).count(),
        'active_courses': courses_qs.count(),
        'all_courses': courses_qs,
        'all_doctors': AcademyDoctor.objects.all(),
        'course_prices_json': json.dumps(course_prices_dict),
        'title': 'أكاديمية التدريب المهني (برنامج 14 شهر)'
    }
    return render(request, 'students/academy_dashboard.html', context)


@login_required
def api_academy_student_details(request, enrollment_id):
    """API جلب التفاصيل الشاملة مع قائمة الدكاترة والمواد بالتيرمات المحدثة"""
    enrollment = get_object_or_404(
        AcademyEnrollment.objects.select_related('student', 'course'),
        id=enrollment_id
    )

    today = timezone.now().date()
    days_passed = (today - enrollment.enrollment_date).days
    total_course_days = enrollment.course.duration_months * 30
    progress_percentage = min(int((days_passed / total_course_days) * 100), 100) if total_course_days > 0 else 0

    attendances = enrollment.attendances.select_related('lecture__term_subject__subject', 'lecture__term_subject__doctor').order_by('-lecture__lecture_date')
    attended_count = attendances.filter(status='present').count()
    absent_count = attendances.filter(status='absent').count()

    attendance_history = [
        {
            "lecture_title": f"{att.lecture.title} ({att.lecture.term_subject.subject.name})",
            "date": att.lecture.lecture_date.strftime('%Y-%m-%d'),
            "status": "حاضر" if att.status == 'present' else "غائب",
            "is_present": att.status == 'present'
        }
        for att in attendances
    ]

    doctors_list = list(enrollment.course.term_subjects.values_list('doctor__name', flat=True).distinct())
    doctors_str = ", ".join(doctors_list) if doctors_list else "نخبة المحاضرين"

    price = enrollment.final_price
    paid_qs = GeneralLedger.objects.filter(
        student=enrollment.student,
        category='كورس'
    ).filter(
        Q(notes__icontains=enrollment.course.name) | Q(notes__icontains="أكاديمية") | Q(notes__icontains="دبلومة")
    )
    total_paid = paid_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    if total_paid == Decimal('0.00'):
        total_paid = GeneralLedger.objects.filter(
            student=enrollment.student, category='كورس'
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    remaining = max(Decimal('0.00'), price - total_paid)

    if remaining <= Decimal('0.00') and price > Decimal('0.00'):
        fin_status = "خالص ومسدد بالكامل ✅"
        fin_badge = "success"
    elif total_paid > Decimal('0.00'):
        fin_status = f"سداد جزئي (متبقي {remaining} ج.م) ⚠️"
        fin_badge = "warning"
    else:
        fin_status = "لم يتم السداد ❌"
        fin_badge = "danger"

    return JsonResponse({
        'success': True,
        'student': {
            'name': enrollment.student.get_full_name(),
            'code': enrollment.student.student_code,
            'enrollment_date': enrollment.enrollment_date.strftime('%Y-%m-%d'),
            'expected_graduation': enrollment.expected_graduation_date.strftime('%Y-%m-%d'),
            'is_graduated': enrollment.is_graduated,
        },
        'course': {
            'name': enrollment.course.name,
            'doctor': doctors_str,
            'progress_pct': progress_percentage,
        },
        'financials': {
            'price': float(price),
            'total_paid': float(total_paid),
            'remaining': float(remaining),
            'status_label': fin_status,
            'status_badge': fin_badge
        },
        'attendance': {
            'total_attended': attended_count,
            'total_absent': absent_count,
            'history': attendance_history
        }
    })


@login_required
def api_check_academy_enrollment(request):
    """API فحص وجود اشتراك سابق للطالب لمنع الدبلجة وقفل الحفظ"""
    student_id = request.GET.get('student_id')
    course_id = request.GET.get('course_id')

    if student_id and course_id:
        enrollment = AcademyEnrollment.objects.filter(
            student_id=student_id, course_id=course_id
        ).select_related('student', 'course').first()

        if enrollment:
            return JsonResponse({
                'exists': True,
                'message': f'⚠️ هذا الطالب ({enrollment.student.get_full_name()}) مشترك بالفعل في دبلومة ({enrollment.course.name})! بياناته مثبتة ولا يمكن التعديل إلا من خلال لوحة التحكم (Admin).'
            })

    return JsonResponse({'exists': False})


@login_required
def api_search_students_for_courses(request):
    """API بحث صاروخي وخفيف لاستهلاك صفر من الذاكرة عند فتح الصفحة"""
    q = request.GET.get('q', '').strip()
    return JsonResponse({'students': perform_student_search(q)})


@login_required
def get_teacher_courses_api(request, teacher_id):
    """API سريع لتصفية المواد والباقات الخاصة بالمدرس المحدد فقط"""
    courses = SubjectPrice.objects.filter(teacher_id=teacher_id).select_related('subject', 'teacher')
    data = []
    for c in courses:
        data.append({
            'id': c.id,
            'name': f"{c.subject.name} - {c.teacher.name} ({c.get_session_type_display()}) - {c.price} ج.م",
            'teacher_id': c.teacher_id
        })
    return JsonResponse({'success': True, 'courses': data})


def _get_or_create_inventory_master(inv_item, student):
    """
    🌉 جسر تلقائي بين مخزون شاشة الطلاب (students.InventoryItem) ومخزون الماليات
    (finance.InventoryMaster / ItemDefinition) اللي موديل DeliveryRecord مبني عليه فعلياً.
    """
    from finance.models import ItemDefinition, InventoryMaster

    academic_year = getattr(student, 'academic_year', None)
    if academic_year is None:
        academic_year = get_active_year()

    # ⚡ دعم الحالتين (display_name أو name) بدل الاعتماد على اسم واحد بس
    item_name = getattr(inv_item, 'display_name', None) or getattr(inv_item, 'name', None) or str(inv_item)

    item_def, _ = ItemDefinition.objects.get_or_create(name=item_name)

    master, _ = InventoryMaster.objects.get_or_create(
        item=item_def,
        grade=student.grade,
        academic_year=academic_year,
        defaults={'total_quantity': getattr(inv_item, 'stock_quantity', None) or 9999}
    )
    return master


@login_required
def book_sales_list(request):
    """
    لوحة تحكم وتتبع صرف الكتب والزي المدرسي مع مطابقة سليمة لحقول DeliveryRecord
    """
    # 🩺 [تشخيص مؤقت للأداء] - نقيس هنا عدد الاستعلامات ووقتها الحقيقي بدقة
    # بغض النظر عن قيمة DEBUG. احذف الكتلة دي بعد ما نوصل للسبب.
    import time as _time
    from django.test.utils import CaptureQueriesContext
    from django.db import connection as _connection
    _t0 = _time.perf_counter()
    _qctx = CaptureQueriesContext(_connection)
    _qctx.__enter__()

    active_year = get_active_year()

    q = request.GET.get('q', '').strip()
    item_type = request.GET.get('item_type', '')
    grade_id = request.GET.get('grade_id', '')
    status_filter = request.GET.get('status', '')

    sales_qs = BookSale.objects.select_related(
        'student', 'student__grade', 'student__classroom',
        'item__subject', 'item__uniform', 'item__grade',
        'delivered_by'
    ).order_by('-sale_date')

    # استبعاد أذونات البنود الفرعية الصفرية المكررة لمنع ازدواجية السطور بالجدول
    sales_qs = sales_qs.exclude(
        Q(total_amount=0) & Q(pay_now=0) & (Q(item__subject__isnull=False) | Q(item__uniform__isnull=False))
    )

    if q:
        sales_qs = sales_qs.annotate(
            student_full_name=Concat(
                Coalesce('student__first_name', Value('')),
                Value(' '),
                Coalesce('student__last_name', Value('')),
                output_field=CharField()
            )
        )
        for word in q.split():
            w_plain = word.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
            w_hamza = word.replace('ا', 'أ')

            sales_qs = sales_qs.filter(
                Q(student_full_name__icontains=word) | Q(student_full_name__icontains=w_plain) | Q(student_full_name__icontains=w_hamza) |
                Q(student__first_name__icontains=word) | Q(student__first_name__icontains=w_plain) | Q(student__first_name__icontains=w_hamza) |
                Q(student__last_name__icontains=word) | Q(student__last_name__icontains=w_plain) | Q(student__last_name__icontains=w_hamza) |
                Q(student__student_code__icontains=word) |
                Q(student__national_id__icontains=word)
            )

    if item_type:
        sales_qs = sales_qs.filter(item__item_type=item_type)
    if grade_id:
        sales_qs = sales_qs.filter(student__grade_id=grade_id)
    if status_filter == 'delivered':
        sales_qs = sales_qs.filter(is_delivered=True)
    elif status_filter == 'pending_delivery':
        sales_qs = sales_qs.filter(is_delivered=False)

    paginator = Paginator(sales_qs, 20)
    page_number = request.GET.get('page', 1)
    sales_page = paginator.get_page(page_number)

    from django.apps import apps
    from .models import InventoryItem, SubjectConfig, Uniform

    DeliveryRecord = None
    for app_label in ['students', 'finance', 'inventory']:
        try:
            DeliveryRecord = apps.get_model(app_label, 'DeliveryRecord')
            if DeliveryRecord:
                break
        except Exception:
            pass

    sales_list_objs = list(sales_page.object_list)

    # 🚀 [تحسين الأداء] بدل ما نعمل 4-5 استعلامات قاعدة بيانات لكل صف بالجدول (N+1)،
    # بنجمع كل البيانات المطلوبة لكل الصفحة دفعة واحدة بعدد ثابت من الاستعلامات.

    # 1) تجهيز/تخزين مؤقت لبيانات (إجمالي الأصناف + أسماء أصناف النوع) لكل توليفة صف دراسي+سنة+نوع
    grade_itype_cache = {}

    def get_grade_itype_info(grade, academic_year, itype):
        cache_key = (getattr(grade, 'id', None), getattr(academic_year, 'id', None), itype)
        if cache_key in grade_itype_cache:
            return grade_itype_cache[cache_key]

        if itype == 'book':
            total_items_count = SubjectConfig.objects.filter(grade=grade, academic_year=academic_year).count()
            type_items_qs = InventoryItem.objects.filter(grade=grade, item_type='book', subject__isnull=False)
            if total_items_count == 0:
                total_items_count = type_items_qs.count() or 1
        else:
            type_items_qs = InventoryItem.objects.filter(grade=grade, item_type='uniform', uniform__isnull=False)
            total_items_count = type_items_qs.count() or Uniform.objects.count() or 1

        type_item_names = set(i.display_name for i in type_items_qs)
        grade_itype_cache[cache_key] = (total_items_count, type_item_names)
        return grade_itype_cache[cache_key]

    # 2) جلب كل سجلات DeliveryRecord لكل طلاب الصفحة الحالية دفعة واحدة (استعلام واحد بدل 20)
    student_ids = list({sale.student_id for sale in sales_list_objs if sale.student_id})
    delivery_by_student = {}
    if DeliveryRecord and student_ids:
        try:
            del_records = DeliveryRecord.objects.filter(student_id__in=student_ids).select_related('inventory_item__item')
            for r in del_records:
                delivery_by_student.setdefault(r.student_id, []).append(r)
        except Exception:
            pass

    # 3) جلب كل سجلات BookSale المُسلَّمة (نوع فردي) لكل طلاب الصفحة الحالية دفعة واحدة
    bs_delivered_by_student = {}
    if student_ids:
        bs_delivered_qs = BookSale.objects.filter(
            student_id__in=student_ids, is_delivered=True
        ).select_related('item')
        for bs in bs_delivered_qs:
            if bs.item:
                bs_delivered_by_student.setdefault((bs.student_id, bs.item.item_type), []).append(bs)

    for sale in sales_list_objs:
        st = sale.student
        if not st or not sale.item:
            continue

        itype = sale.item.item_type

        # 1. إجمالي الأصناف + أسماء أصناف النوع (من الكاش، بدون أي استعلام إضافي)
        total_items_count, type_item_names = get_grade_itype_info(st.grade, st.academic_year, itype)

        # 2. أسماء الأصناف المسلمة فعلياً للطالب (من البيانات المجلوبة مسبقاً، بدون أي استعلام إضافي)
        delivered_names = []
        for r in delivery_by_student.get(st.id, []):
            if r.inventory_item and r.inventory_item.item and r.inventory_item.item.name in type_item_names:
                delivered_names.append(r.inventory_item.item.name)

        for bs in bs_delivered_by_student.get((st.id, itype), []):
            if bs.item and (bs.item.subject_id or bs.item.uniform_id):
                delivered_names.append(bs.item.display_name)

        delivered_names = list(set(delivered_names))
        delivered_cnt = len(delivered_names)

        # 3. تحديد حالة التسليم بدقة مطلقة
        is_individual_item = bool(sale.item.subject_id or sale.item.uniform_id)
        # 🛡️ عملية الصرف دي "باقة" (مفيش تفصيل حقيقي لمواد متعددة) طالما مفيش أكتر من صنف واحد مسجل فعلياً للصف ده
        is_package_level = total_items_count <= 1 and not type_item_names

        if is_individual_item and sale.is_delivered:
            sale.delivery_state = 'full'
            sale.delivered_count_display = "تم تسليم الصنف"
        elif is_package_level:
            # 🛡️ الاعتماد المباشر على حالة الصرف نفسها بدل أي مقارنة عددية قد تتطابق صدفة
            if sale.is_delivered:
                sale.delivery_state = 'full'
                sale.delivered_count_display = "تم التسليم بالكامل"
            else:
                sale.delivery_state = 'pending'
                sale.delivered_count_display = "لم يتم التسليم بعد"
        elif delivered_cnt >= total_items_count and total_items_count > 0:
            sale.delivery_state = 'full'
            sale.delivered_count_display = f"{total_items_count}/{total_items_count}"
        elif delivered_cnt > 0:
            sale.delivery_state = 'partial'
            sale.delivered_count_display = f"{delivered_cnt}/{total_items_count}"
            sale.delivered_items_list = "، ".join(delivered_names)
            # 🟡 الأصناف المتبقية (اللي لسه محتاجة تتسلّم) - أقصر وأفيد للموظف من عرض المُسلَّم فعلاً
            remaining_names = sorted(type_item_names - set(delivered_names))
            sale.remaining_items_list = "، ".join(remaining_names) if remaining_names else "—"
        else:
            sale.delivery_state = 'pending'
            sale.delivered_count_display = f"0/{total_items_count}"

    total_sales_count = paginator.count  # 🚀 استخدام العدّاد المحسوب بالفعل داخل الـ Paginator بدل تكرار استعلام count() مرة تانية
    from django.core.cache import cache

    # 🚀 [تحسين إضافي] الإحصائيات دي بتتغير ببطء نسبياً، فتخزينها في الكاش لمدة قصيرة
    # بيمنع تنفيذ Aggregate على جدول BookSale بالكامل في كل تحميل صفحة (أثقل استعلام في الشاشة)
    stats_agg = cache.get('book_sales_stats_agg')
    if stats_agg is None:
        stats_agg = BookSale.objects.aggregate(
            books_delivered=Count('id', filter=Q(item__item_type='book', is_delivered=True)),
            uniforms_delivered=Count('id', filter=Q(item__item_type='uniform', is_delivered=True)),
            pending_delivery=Count('id', filter=Q(is_delivered=False)),
        )
        cache.set('book_sales_stats_agg', stats_agg, 60)  # يتجدد تلقائياً كل 60 ثانية
    books_delivered_count = stats_agg['books_delivered']
    uniforms_delivered_count = stats_agg['uniforms_delivered']
    pending_delivery_count = stats_agg['pending_delivery']

    context = {
        'sales': sales_page,
        'all_grades': Grade.objects.all(),
        'total_sales_count': total_sales_count,
        'books_delivered_count': books_delivered_count,
        'uniforms_delivered_count': uniforms_delivered_count,
        'pending_delivery_count': pending_delivery_count,
        'search_query': q,
        'selected_item_type': item_type,
        'selected_grade': grade_id,
        'selected_status': status_filter,
        'active_year': active_year,
        'title': 'سجل حركة صرف الكتب والزي المدرسي'
    }

    _qctx.__exit__(None, None, None)
    _db_time = sum(float(q.get('time', 0)) for q in _qctx.captured_queries)
    _t_before_render = _time.perf_counter()

    response = render(request, 'books/sales_list.html', context)

    _t_after_render = _time.perf_counter()
    print(
        f"\n🩺 [DIAG] book_sales_list => "
        f"عدد الاستعلامات: {len(_qctx.captured_queries)} | "
        f"وقت الاستعلامات مجتمعة: {_db_time:.3f}s | "
        f"وقت المعالجة (بايثون) قبل الـ render: {(_t_before_render - _t0):.3f}s | "
        f"وقت الـ render نفسه: {(_t_after_render - _t_before_render):.3f}s | "
        f"الإجمالي الكلي للفانكشن: {(_t_after_render - _t0):.3f}s\n"
    )
    return response




from .models import BookSale

# -------------------------------------------------------------------
# دالة مساعدة لتحديد موديل DeliveryRecord مرة واحدة ديناميكياً
# -------------------------------------------------------------------
def _get_delivery_record_model():
    for app_label in ['students', 'finance', 'core_inventory', 'inventory']:
        try:
            model = apps.get_model(app_label, 'DeliveryRecord')
            if model:
                return model
        except Exception:
            pass
    return None



@login_required
def api_get_sale_delivery_details(request, sale_id):
    """
    جلب أصناف الباقة ورصيدها المتاح وموقف التسليم بأقصى سرعة ودقة.
    """
    import traceback
    from decimal import Decimal
    from django.shortcuts import get_object_or_404
    from django.http import JsonResponse
    from django.db.models import Sum, Case, When, F, Value, DecimalField
    from django.db.models.functions import Coalesce

    # 🟢 استيراد الموديلات من التطبيقات الصحيحة
    from core_inventory.models import ItemMaster, StockBalance, StockTransaction
    from students.models import BookSale

    try:
        # 1. جلب إذن الصرف والطالب بأقل عدد استعلامات
        sale = get_object_or_404(
            BookSale.objects.select_related('student__grade', 'student__academic_year', 'item'),
            id=sale_id
        )
        student = sale.student
        item_type = getattr(sale.item, 'item_type', 'saleable') if sale.item else 'saleable'
        student_grade = student.grade if student else None

        if not student_grade:
            return JsonResponse({
                'success': False,
                'error': 'الطالب غير مربوط بصف دراسي محدد!'
            }, status=400)

        # 2. فلترة الأصناف المربوطة بالصف الدراسي
        items_qs = ItemMaster.objects.filter(linked_grade=student_grade)

        if item_type in ['saleable', 'consumable', 'asset']:
            items_qs = items_qs.filter(item_type=item_type)

        items_list = list(items_qs)
        item_ids = [item.id for item in items_list]

        if not item_ids:
            return JsonResponse({
                'success': True,
                'sale_id': sale.id,
                'student_name': student.get_full_name() if hasattr(student, 'get_full_name') else str(student),
                'grade_name': student_grade.name if student_grade else '---',
                'specialization': student.get_specialization_display() if hasattr(student, 'get_specialization_display') and getattr(student, 'specialization', None) else 'شعبة عامة',
                'item_type_label': "مخزون للبيع (كتب/زي)" if item_type == 'saleable' else "أصناف أخرى",
                'is_fully_delivered': False,
                'delivered_count': 0,
                'total_count': 0,
                'items': []
            })

        # 3. ⚡ جلب الرصيد المتاح من StockBalance
        stock_balance_map = dict(
            StockBalance.objects.filter(item_id__in=item_ids)
            .values('item_id')
            .annotate(total=Coalesce(Sum('quantity_on_hand'), Decimal('0.00')))
            .values_list('item_id', 'total')
        )

        # 4. ⚡ حساب مباشر من StockTransaction لضمان دقة الرصيد إذا لم يتحدث StockBalance
        tx_stock_map = dict(
            StockTransaction.objects.filter(item_id__in=item_ids)
            .values('item_id')
            .annotate(
                total=Coalesce(
                    Sum(
                        Case(
                            When(movement_type__in=['IN_OPENING', 'IN_PURCHASE', 'IN_RETURN', 'ADJUST'], then=F('quantity')),
                            When(movement_type__in=['OUT_STUDENT', 'OUT_DEPT', 'OUT_WASTE', 'TRANSFER'], then=-F('quantity')),
                            default=Value(Decimal('0.00')),
                            output_field=DecimalField()
                        )
                    ),
                    Decimal('0.00')
                )
            )
            .values_list('item_id', 'total')
        )

        # 5. جلب سجلات التسليم المسبقة للطالب
        delivered_item_ids = set()

        try:
            if hasattr(sale, 'delivered_items'):
                delivered_item_ids.update(
                    sale.delivered_items.values_list('id', flat=True)
                )
        except Exception:
            pass

        sale_is_delivered_fallback = getattr(sale, 'is_delivered', False)

        # 6. معالجة البيانات وتحديد المتاح الحقيقي
        items_data = []
        for item in items_list:
            sb_qty = stock_balance_map.get(item.id, Decimal('0.00')) or Decimal('0.00')
            tx_qty = tx_stock_map.get(item.id, Decimal('0.00')) or Decimal('0.00')

            stock_qty = max(sb_qty, tx_qty)
            already_delivered = (item.id in delivered_item_ids) or sale_is_delivered_fallback

            items_data.append({
                'id': item.id,
                'sku': item.sku or '',
                'name': item.name,
                'stock': float(stock_qty),
                'is_delivered': already_delivered,
                'is_available': (stock_qty > 0) or already_delivered
            })

        delivered_count = sum(1 for i in items_data if i['is_delivered'])
        total_count = len(items_data)

        type_label = "مخزون للبيع (كتب/زي)" if item_type == 'saleable' else "أصناف أخرى"

        return JsonResponse({
            'success': True,
            'sale_id': sale.id,
            'student_name': student.get_full_name() if hasattr(student, 'get_full_name') else str(student),
            'grade_name': student_grade.name if student_grade else '---',
            'specialization': student.get_specialization_display() if hasattr(student, 'get_specialization_display') and getattr(student, 'specialization', None) else 'شعبة عامة',
            'item_type_label': type_label,
            'is_fully_delivered': delivered_count >= total_count and total_count > 0,
            'delivered_count': delivered_count,
            'total_count': total_count,
            'items': items_data
        })

    except Exception as e:
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'حدث خطأ في الخادم: {str(e)}'}, status=500)


@login_required
@require_POST
def api_confirm_sale_delivery(request, student_id):
    """
    تأكيد تسليم الأصناف المحددة للطالب، تحديث سجلات BookSale الخاصة بها،
    وخصمها من المخزن بإنشاء حركات StockTransaction آمنة.
    """
    import json
    from django.utils import timezone
    from core_inventory.models import ItemMaster, StockBalance, StockTransaction, Warehouse
    from students.models import Student, BookSale

    try:
        data = json.loads(request.body or '{}')
        selected_item_ids = data.get('item_ids', []) or data.get('selected_items', [])

        if not selected_item_ids:
            return JsonResponse({'success': False, 'error': 'لم يتم تحديد أي أصناف للتسليم!'}, status=400)

        student = get_object_or_404(Student, id=student_id)

        # جلب سجلات البيع غير المسلمة للأصناف المحددة
        sales_to_deliver = BookSale.objects.filter(
            student=student,
            item_id__in=selected_item_ids,
            is_delivered=False
        ).select_related('item')

        if not sales_to_deliver.exists():
            return JsonResponse({'success': False, 'error': 'جميع الأصناف المحددة تم تسليمها مسبقاً أو غير موجودة!'}, status=400)

        insufficient_items = []
        item_warehouse_map = {}
        default_warehouse = Warehouse.objects.filter(is_active=True).first()

        # 1. مرحلة التحقق من توفر الرصيد لكافة الأصناف أولاً
        for sale in sales_to_deliver:
            item = sale.item
            sb_qty = StockBalance.objects.filter(item=item).aggregate(
                total=Coalesce(Sum('quantity_on_hand'), Decimal('0.00'))
            )['total'] or Decimal('0.00')

            if sb_qty < Decimal('1.00'):
                insufficient_items.append(item.name)
            else:
                balances = StockBalance.objects.filter(item=item, quantity_on_hand__gt=0).order_by('-quantity_on_hand')
                target_wh = balances.first().warehouse if balances.exists() else default_warehouse
                item_warehouse_map[item.id] = target_wh

        if insufficient_items:
            items_str = "، ".join(insufficient_items)
            return JsonResponse({
                'success': False,
                'error': f'تعذر التسليم! نفاذ رصيد المخزن للأصناف التالية: ({items_str}).'
            }, status=400)

        # 2. مرحلة التنفيذ والحفظ داخل Transaction آمنة
        with transaction.atomic():
            delivered_count = 0
            for sale in sales_to_deliver:
                item = sale.item
                target_wh = item_warehouse_map.get(item.id)

                if target_wh:
                    # تسجيل حركة الخروج من المخزن
                    StockTransaction.objects.create(
                        item=item,
                        warehouse=target_wh,
                        movement_type='OUT_STUDENT',
                        quantity=Decimal('1.00'),
                        student=student,
                        created_by=request.user,
                        notes=f"تسليم للطالب {student.get_full_name()} (إذن صرف #{sale.id})"
                    )

                    # تحديث حالة السنف في جدول BookSale مباشرة
                    sale.is_delivered = True
                    sale.delivered_at = timezone.now()
                    sale.delivered_by = request.user
                    sale.status = 'delivered'
                    sale.save(update_fields=['is_delivered', 'delivered_at', 'delivered_by', 'status'])
                    delivered_count += 1

        return JsonResponse({
            'success': True,
            'message': f'✅ تم تسليم {delivered_count} صنف وخصمها من المخزن بنجاح!'
        })

    except Exception as e:
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'حدث خطأ في الخادم: {str(e)}'}, status=500)

@login_required
@require_POST
def api_save_partial_delivery(request, sale_id):
    """
    تأكيد وحفظ التسليم والخصم الجماعي بأقصى سرعة باستعلامات دُفَعية (Bulk Processing).
    """
    try:
        sale = get_object_or_404(
            BookSale.objects.select_related('student__grade', 'student__academic_year', 'item'),
            id=sale_id
        )
        student = sale.student

        data = json.loads(request.body)
        selected_item_ids = data.get('selected_items', [])

        if not selected_item_ids:
            return JsonResponse({'success': False, 'error': 'يرجى تحديد كتاب/صنف واحد على الأقل لتسليمه الآن!'}, status=400)

        from decimal import Decimal
        from django.db.models import Sum, Case, When, F, Value, DecimalField
        from django.db.models.functions import Coalesce
        from core_inventory.models import ItemMaster, StockBalance, StockTransaction

        # ⚡ 1. جلب جميع الأصناف المحددة دفعة واحدة (Bulk Fetch)
        items_qs = ItemMaster.objects.filter(id__in=selected_item_ids)
        items_dict = {item.id: item for item in items_qs}

        # ⚡ 2. جلب جميع الأرصدة والمخازن دفعة واحدة
        balances_dict = {
            b.item_id: b
            for b in StockBalance.objects.filter(item_id__in=selected_item_ids).select_related('warehouse')
        }

        # ⚡ 2.1 🩹 مزامنة ذاتية: احسب الرصيد الحقيقي من الحركات (StockTransaction)
        #     ده نفس منطق الفحص المستخدم في شاشة عرض الأصناف (api_get_sale_delivery_details)
        #     عشان نضمن إن الشاشتين دايماً متوافقتين ومفيش صنف يظهر "متاح" في العرض
        #     وبعدين يترفض وقت التسليم الفعلي.
        tx_by_item_warehouse = (
            StockTransaction.objects.filter(item_id__in=selected_item_ids)
            .values('item_id', 'warehouse_id')
            .annotate(
                total=Coalesce(
                    Sum(
                        Case(
                            When(movement_type__in=['IN_OPENING', 'IN_PURCHASE', 'IN_RETURN', 'ADJUST'], then=F('quantity')),
                            When(movement_type__in=['OUT_STUDENT', 'OUT_DEPT', 'OUT_WASTE', 'TRANSFER'], then=-F('quantity')),
                            default=Value(Decimal('0.00')),
                            output_field=DecimalField()
                        )
                    ),
                    Decimal('0.00')
                )
            )
        )

        # لكل صنف، هات المخزن اللي رصيده الفعلي (من الحركات) هو الأعلى
        tx_best_map = {}
        for row in tx_by_item_warehouse:
            item_id = row['item_id']
            qty = row['total'] or Decimal('0.00')
            if item_id not in tx_best_map or qty > tx_best_map[item_id]['qty']:
                tx_best_map[item_id] = {'warehouse_id': row['warehouse_id'], 'qty': qty}

        # صحّح أو أنشئ سجلات StockBalance الناقصة/القديمة قبل أي فحص للتوفر
        balances_to_fix = []
        for item_id, tx_info in tx_best_map.items():
            tx_qty = tx_info['qty']
            if tx_qty <= 0 or not tx_info['warehouse_id']:
                continue

            existing = balances_dict.get(item_id)

            if not existing:
                # مفيش سجل StockBalance خالص لهذا الصنف -> ننشئه من واقع الحركات الفعلي
                new_balance, created = StockBalance.objects.get_or_create(
                    item_id=item_id,
                    warehouse_id=tx_info['warehouse_id'],
                    defaults={'quantity_on_hand': tx_qty}
                )
                if not created and new_balance.quantity_on_hand < tx_qty:
                    new_balance.quantity_on_hand = tx_qty
                    balances_to_fix.append(new_balance)
                balances_dict[item_id] = new_balance
            elif existing.quantity_on_hand < tx_qty:
                # الرصيد المسجل أقل من واقع الحركات (زي حالتنا الحالية) -> صححه
                existing.quantity_on_hand = tx_qty
                balances_to_fix.append(existing)

        if balances_to_fix:
            StockBalance.objects.bulk_update(balances_to_fix, ['quantity_on_hand'])

        # ⚡ 3. جلب السجلات المسلمة سابقاً في استعلام واحد
        delivered_item_ids = set()
        DeliveryRecord = _get_delivery_record_model()

        if DeliveryRecord:
            delivered_item_ids.update(
                DeliveryRecord.objects.filter(student=student)
                .values_list('inventory_item_id', flat=True)
            )

        if hasattr(sale, 'delivered_items'):
            delivered_item_ids.update(
                sale.delivered_items.values_list('id', flat=True)
            )

        out_of_stock = []
        already_delivered_now = []
        valid_items_to_process = []

        # 4. التصفية والفحص السريع في الذاكرة
        for item_id in selected_item_ids:
            item = items_dict.get(item_id)
            if not item:
                continue

            display_name = getattr(item, 'name', str(item))

            if item.id in delivered_item_ids:
                already_delivered_now.append(display_name)
                continue

            balance = balances_dict.get(item.id)
            stock_qty = balance.quantity_on_hand if balance else 0

            if stock_qty <= 0:
                out_of_stock.append(display_name)
            else:
                valid_items_to_process.append((item, balance))

        if out_of_stock:
            return JsonResponse({
                'success': False,
                'error': f'🛑 تعذر التسليم! نفاذ رصيد المخزن للأصناف التالية: ({", ".join(out_of_stock)}).'
            }, status=400)

        if already_delivered_now and not valid_items_to_process:
            return JsonResponse({
                'success': False,
                'error': f'⚠️ الصنف/الأصناف التالية تم تسليمها من قبل: ({", ".join(already_delivered_now)}).'
            }, status=400)

        # ⚡ 5. الحفظ الفعلي للحركات (كل حركة عن طريق .save() الطبيعية وليس bulk_create)
        #     السبب: موديل StockTransaction فيه save() مخصص بيعمل تلقائياً:
        #       - توليد رقم الحركة (transaction_code)
        #       - التحقق من كفاية الرصيد قبل الخصم (ValidationError لو الرصيد غير كافٍ)
        #       - تحديث StockBalance.quantity_on_hand أوتوماتيك (StockBalance.update_balance)
        #     bulk_create() كان بيتخطى الثلاث خطوات دي بالكامل، وده سبب أساسي
        #     في عدم تطابق الأرصدة. استخدام .save() هنا يضمن إن الرصيد يفضل مضبوط
        #     تلقائياً من نفسه في كل عملية تسليم، من غير أي تدخل يدوي.
        from django.core.exceptions import ValidationError

        delivered_names = []
        records_to_create = []
        items_to_add_to_sale = []

        student_name = student.get_full_name() if hasattr(student, 'get_full_name') else str(student)

        try:
            with transaction.atomic():
                for item, balance in valid_items_to_process:
                    display_name = getattr(item, 'name', str(item))
                    warehouse = balance.warehouse if balance else None

                    if not warehouse:
                        continue

                    # ⚡ الحفظ الطبيعي: بيتحقق من الرصيد ويحدّث StockBalance تلقائياً بنفسه
                    StockTransaction(
                        item=item,
                        warehouse=warehouse,
                        movement_type='OUT_STUDENT',
                        quantity=1,
                        student=student,
                        created_by=request.user,
                        notes=f'تسليم طالب: {student_name} - إذن #{sale.id}'
                    ).save()

                    if DeliveryRecord:
                        master = _get_or_create_inventory_master(item, student) if '_get_or_create_inventory_master' in globals() else item
                        records_to_create.append(
                            DeliveryRecord(
                                student=student,
                                inventory_item=master,
                                delivered_by=request.user,
                                is_received=True
                            )
                        )

                    items_to_add_to_sale.append(item)
                    delivered_names.append(display_name)

                if DeliveryRecord and records_to_create:
                    DeliveryRecord.objects.bulk_create(records_to_create, ignore_conflicts=True)

                if hasattr(sale, 'delivered_items') and items_to_add_to_sale:
                    sale.delivered_items.add(*items_to_add_to_sale)

                # 6. تحديث حالة إذن الصرف
                total_required = ItemMaster.objects.filter(linked_grade=student.grade).count() or 1
                total_delivered = len(delivered_item_ids) + len(items_to_add_to_sale)

                if total_delivered >= total_required:
                    sale.is_delivered = True
                    sale.delivered_at = timezone.now()
                    sale.delivered_by = request.user
                    sale.status = 'delivered'
                    sale.delivery_state = 'full'
                else:
                    sale.status = 'partial'
                    sale.delivery_state = 'partial'

                sale.save()
        except ValidationError as e:
            error_msg = "، ".join(e.messages) if hasattr(e, 'messages') else str(e)
            return JsonResponse({'success': False, 'error': f'🛑 {error_msg}'}, status=400)

        user_display = request.user.get_full_name() or request.user.username
        success_message = f'✅ تم حفظ وتسليم ({len(delivered_names)}) صنف بنجاح للطالب ({student_name}) وخصمها من المخزن.'
        if already_delivered_now:
            success_message += f' ⚠️ ملاحظة: تم تجاهل الأصناف المسلمة سابقاً: {", ".join(already_delivered_now)}.'

        return JsonResponse({
            'success': True,
            'message': success_message,
            'is_fully_delivered': sale.is_delivered,
            'delivered_by': user_display
        })

    except Exception as e:
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'خطأ تقني: {str(e)}'}, status=400)


def perform_student_search(q):
    """خوارزمية تفكيك النص والبحث السريع والمفهرس مع تقديم النتائج التي تبدأ بالنص المكتوب"""
    q = q.strip() if q else ''
    if not q or len(q) < 2:
        return []

    words = q.split()
    qs = Student.objects.filter(is_active=True)

    for word in words:
        # 🟢 توحيد كلمة البحث لمعالجة (أ/إ/ا، ة/ه، ي/ى)
        norm_word = word.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')

        # 🟢 استخدام الحقل المفهرس للبحث
        qs = qs.filter(
            Q(search_name__icontains=norm_word) |
            Q(student_code__icontains=word) |
            Q(national_id__icontains=word)
        )

    # 🟢 توحيد النص الكامل للبحث لمنح الأولوية للأسماء التي تبدأ به
    norm_q = q.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')

    # 🎯 استخدام Case / When لإعطاء أولوية (0) للأسماء وأركان البحث التي تبدأ بالنص المدخل
    qs = qs.annotate(
        is_prefix_match=Case(
            When(
                Q(search_name__istartswith=norm_q) |
                Q(first_name__istartswith=q) |
                Q(student_code__istartswith=q),
                then=Value(0)
            ),
            default=Value(1),
            output_field=IntegerField()
        )
    ).order_by('is_prefix_match', 'first_name', 'last_name')

    students = qs.select_related('grade')[:15]

    results = []
    for st in students:
        results.append({
            'id': st.id,
            'name': st.get_full_name(),
            'code': st.student_code or '---',
            'national_id': st.national_id or '---',
            'grade': st.grade.name if st.grade else 'غير محدد',
        })
    return results


# def perform_student_search(q):
#     """خوارزمية تفكيك النص والبحث السريع والمفهرس (تدعم معالجة الحروف العربية)"""
#     q = q.strip() if q else ''
#     if not q or len(q) < 2:
#         return []

#     words = q.split()
#     qs = Student.objects.filter(is_active=True)

#     for word in words:
#         # 🟢 توحيد كلمة البحث لمعالجة (أ/إ/ا، ة/ه، ي/ى)
#         norm_word = word.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')

#         # 🟢 استخدام الحقل المفهرس الجديد للبحث فائق السرعة
#         qs = qs.filter(
#             Q(search_name__icontains=norm_word) |
#             Q(student_code__icontains=word) |
#             Q(national_id__icontains=word)
#         )

#     students = qs.select_related('grade')[:15]

#     results = []
#     for st in students:
#         results.append({
#             'id': st.id,
#             'name': st.get_full_name(),
#             'code': st.student_code or '---',
#             'national_id': st.national_id or '---',
#             'grade': st.grade.name if st.grade else 'غير محدد',
#         })
#     return results


@login_required
def search_students_sale(request):
    """دالة البحث الذكي للواجهة الرئيسية"""
    q = request.GET.get('q', '').strip()
    return JsonResponse({'students': perform_student_search(q)})


@login_required
def api_search_students_for_sale(request):
    """API بحث صاروخي للطلاب في شاشة الكاونتر/الصرف"""
    q = request.GET.get('q', '').strip()
    return JsonResponse({'students': perform_student_search(q)})


def get_financial_info_data(student_id):
    """
    جلب الموقف المالي الدقيق بدون أي تضاعف أو تدبيل للمديونية المقررة
    """
    student = get_object_or_404(Student.objects.select_related('grade', 'academic_year'), id=student_id)
    active_year = get_active_year()

    # 1. جلب سعر الباقة المحدد رسمياً للصف بجدول GradePackagePrice (مصدر الحقيقة الثابت)
    package = (
        GradePackagePrice.objects.filter(grade=student.grade, academic_year=student.academic_year).first()
        or GradePackagePrice.objects.filter(grade=student.grade, academic_year=active_year).first()
        or GradePackagePrice.objects.filter(grade=student.grade).first()
    )

    pkg_books_price = Decimal(str(package.books_price if package else '0.00'))
    pkg_uniform_price = Decimal(str(package.uniform_price if package else '0.00'))

    # 2. جلب مبيعات وأذونات الطالب
    sales = list(BookSale.objects.filter(student=student).select_related('item'))

    # 3. حساب المسدد فعلياً بجدول الخزينة العامة
    sale_receipts = [f"BS-{s.id}" for s in sales if s.id]

    from treasury.models import GeneralLedger
    ledger_totals = {}
    if sale_receipts:
        ledger_qs = GeneralLedger.objects.filter(receipt_number__in=sale_receipts).values('receipt_number').annotate(total=Sum('amount'))
        for entry in ledger_qs:
            ledger_totals[entry['receipt_number']] = Decimal(str(entry['total'] or 0))

    books_paid = Decimal('0.00')
    uniform_paid = Decimal('0.00')

    for s in sales:
        paid_val = ledger_totals.get(f"BS-{s.id}", Decimal('0.00'))
        if paid_val == Decimal('0.00') and s.pay_now:
            paid_val = Decimal(str(s.pay_now))

        if s.item:
            if s.item.item_type == 'book':
                books_paid += paid_val
            elif s.item.item_type == 'uniform':
                uniform_paid += paid_val

    # 🛑 القفل المحاسبي: تثبيت المبالغ المطلوبة على سعر الباقة الرسمي للصف دون تكرار أو تدبيل
    books_total = pkg_books_price if pkg_books_price > Decimal('0.00') else books_paid
    uniform_total = pkg_uniform_price if pkg_uniform_price > Decimal('0.00') else uniform_paid

    received_items = [s.item.display_name for s in sales if s.item]

    return {
        'books_total': float(books_total),
        'books_paid': float(books_paid),
        'uniform_total': float(uniform_total),
        'uniform_paid': float(uniform_paid),
        'received_items': received_items,
    }



@login_required
def get_student_financial_info(request, student_id):
    """الدالة الموحدة لإرجاع الموقف المالي وسعر الباقة المقرر والمدفوعات الفعلية للطالب"""
    data = get_financial_info_data(student_id)
    return JsonResponse(data)


@login_required
def student_financial_api(request, student_id):
    """API موحد لجلب الموقف المالي وسعر الباقات للكتب والزي المدرسي"""
    data = get_financial_info_data(student_id)
    return JsonResponse(data)

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def bulk_update_specialization(request):
    """دالة لتحديث تخصص مجموعة طلاب بالترم الثاني دون ترحيل"""
    if request.method == 'POST':
        raw_ids = request.POST.get('selected_ids', '')
        student_ids = [sid.strip() for sid in raw_ids.split(',') if sid.strip()]
        new_specialization = request.POST.get('new_specialization')

        if student_ids and new_specialization:
            updated_count = Student.objects.filter(
                id__in=student_ids,
                is_active=True
            ).update(specialization=new_specialization)

            messages.success(request, f"✅ تم تحديث تخصص {updated_count} طالب بنجاح.")
        else:
            messages.error(request, "⚠️ يرجى تحديد الطلاب والتخصص الجديد.")

    return redirect(request.META.get('HTTP_REFERER', 'student_registry'))


@login_required
def manage_student_subjects_view(request):
    """شاشة إدارة وتسكين المواد الدراسية التي سيمتحن فيها الطلاب"""
    active_year = get_active_year()
    grade_id = request.GET.get('grade_id')

    from .models import SubjectConfig, Subject

    if request.method == 'POST':
        selected_subjects = request.POST.getlist('subjects')
        grade_target = request.POST.get('target_grade_id')

        if grade_target:
            SubjectConfig.objects.filter(academic_year=active_year, grade_id=grade_target).delete()
            for sub_id in selected_subjects:
                SubjectConfig.objects.create(
                    academic_year=active_year,
                    grade_id=grade_target,
                    subject_id=sub_id
                )
            messages.success(request, "تم تحديث وتسكين مواد الامتحانات لهذا الصف الدراسي بنجاح وجاهزة للرصد.")
            return redirect(f"{request.path}?grade_id={grade_target}")

    all_subjects = Subject.objects.all() if apps.is_installed('students') else []
    assigned_subject_ids = []
    if grade_id:
        assigned_subject_ids = SubjectConfig.objects.filter(
            academic_year=active_year,
            grade_id=grade_id
        ).values_list('subject_id', flat=True)

    context = {
        'all_grades': Grade.objects.all(),
        'all_subjects': all_subjects,
        'assigned_subject_ids': list(assigned_subject_ids),
        'selected_grade': grade_id,
        'active_year': active_year,
        'title': 'تسكين مواد امتحانات الطلاب'
    }
    return render(request, 'students/control/manage_student_subjects.html', context)


@login_required
def control_numbers_dashboard_view(request):
    """شاشة إدارة وتوليد أرقام الجلوس والسرية وتوزيع اللجان"""
    active_year = get_active_year()

    if request.method == 'POST':
        capacity = int(request.POST.get('students_per_committee', 20))
        config, created = ControlRoomConfig.objects.update_or_create(
            academic_year=active_year,
            defaults={'students_per_committee': capacity}
        )
        term = request.POST.get('term', 'term1')
        StudentTermControlNumber.generate_numbers_for_term(active_year, term)
        messages.success(request, f"تم بنجاح إعادة توليد أرقام الجلوس وتحديث سعة اللجان إلى ({capacity}) طلاب بالفصل.")
        return redirect('control_numbers_dashboard')

    config = ControlRoomConfig.objects.filter(academic_year=active_year).first()

    numbers_queryset = StudentTermControlNumber.objects.filter(
        academic_year=active_year
    ).select_related('student__grade', 'student__classroom').order_by('seating_number')

    page = request.GET.get('page', 1)
    paginator = Paginator(numbers_queryset, 100)
    try:
        generated_numbers = paginator.page(page)
    except PageNotAnInteger:
        generated_numbers = paginator.page(1)
    except EmptyPage:
        generated_numbers = paginator.page(paginator.num_pages)

    context = {
        'config': config,
        'generated_numbers': generated_numbers,
        'active_year': active_year,
        'title': 'منظومة توليد أرقام الجلوس واللجان السري'
    }
    return render(request, 'students/control/control_numbers_dashboard.html', context)


@login_required
def print_committees_roster_view(request):
    """كشوف المناداة وبطاقات اللجان الجاهزة للطباعة الورقية"""
    active_year = get_active_year()
    term = request.GET.get('term', 'term1')
    committee_id = request.GET.get('committee_number')
    grade_id = request.GET.get('grade_id')

    records = StudentTermControlNumber.objects.filter(
        academic_year=active_year,
        term=term
    ).select_related('student__grade', 'student__classroom')

    if committee_id:
        records = records.filter(committee_number=committee_id)
    if grade_id:
        records = records.filter(student__grade_id=grade_id)

    committees_map = {}
    for r in records.order_by('seating_number').iterator():
        if r.committee_number not in committees_map:
            committees_map[r.committee_number] = []
        committees_map[r.committee_number].append(r)

    context = {
        'all_grades': Grade.objects.all(),
        'committees_map': committees_map,
        'selected_term': term,
        'selected_grade': grade_id,
        'title': 'كشوف مناداة اللجان الرسمية'
    }
    return render(request, 'students/control/print_committees_roster.html', context)


@login_required
@require_POST
def ajax_update_status(request):
    """تحديث حالة نتيجة الطالب الفردية وتثبيتها في شيت الكنترول مع مزامنة الأرشيف"""
    try:
        data = json.loads(request.body)
        student_id = data.get('student_id')
        new_status = data.get('status')

        student = get_object_or_404(Student, id=student_id)
        student.enrollment_status = new_status
        student.save()

        active_year = get_active_year()

        # 🟢 المزامنة التلقائية مع جدول أرشيف الفصل وإعادة القيد (ReEnrollmentRecord)
        from students.models import ReEnrollmentRecord
        if new_status == 'Dismissed':
            ReEnrollmentRecord.objects.get_or_create(
                student=student,
                academic_year=active_year,
                defaults={'status': 'dismissed'}
            )
        elif new_status in ['Re_enrolled', 'New', 'Promoted']:
            # تحويل حالة الفصل إلى "معاد قيده" إذا تم تغيير حالته للنجاح أو إعادة القيد
            ReEnrollmentRecord.objects.filter(
                student=student,
                academic_year=active_year,
                status='dismissed'
            ).update(status='re_enrolled', reenrollment_date=timezone.now().date())

        # 🟢 تحديث شيت الكنترول للناجح والراسب
        if new_status in ['Promoted', 'Failed']:
            subjects = Subject.objects.all()
            for subject in subjects:
                sheet_record, created = StudentControlSheet.objects.get_or_create(
                    student=student,
                    subject=subject,
                    academic_year=active_year
                )
                if new_status == 'Promoted':
                    sheet_record.status = 'passed'
                sheet_record.save()

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def ajax_bulk_status(request):
    """دالة الترحيل الذكي: ترحيل شامل لجميع صفوف المدرسة دفعة واحدة بضغطة زر"""
    try:
        data = json.loads(request.body)
        action = data.get('action')
        active_year = get_active_year()

        if action == 'execute_school_wide_promotion':
            with transaction.atomic():
                active_students = Student.objects.filter(academic_year=active_year, is_active=True)

                # 🛑 صمام أمان: التحقق من وجود طلاب ناجحين مؤهلين للترحيل
                if not active_students.filter(enrollment_status='Promoted').exists():
                    return JsonResponse({
                        'success': False,
                        'error': '🛑 لا يوجد أي طالب بحالة "منقول" في المدرسة! تأكد من اعتماد نتائج الطلاب أولاً.'
                    })

                # 🟢 تقسيم صفوف المدرسة إلى 3 مستويات للمعالجة (بترتيب عكسي إجباري 3 -> 2 -> 1)
                all_grades = Grade.objects.all()
                grades_lvl3 = [g for g in all_grades if "الثالث" in g.name]
                grades_lvl2 = [g for g in all_grades if "الثاني" in g.name or "الثانى" in g.name]
                grades_lvl1 = [g for g in all_grades if "الأول" in g.name or "الاول" in g.name]

                # دالة مساعدة لتحديد الصف التالي بدقة (تطابق الشعبة: منتظم/عمال)
                def find_next_grade(current_g):
                    c_name = current_g.name
                    if "الأول" in c_name or "الاول" in c_name:
                        target_name = c_name.replace("الأول", "الثاني").replace("الاول", "الثاني")
                        return Grade.objects.filter(name=target_name).first() or Grade.objects.filter(name__icontains="الثاني").first()
                    elif "الثاني" in c_name or "الثانى" in c_name:
                        target_name = c_name.replace("الثاني", "الثالث").replace("الثانى", "الثالث")
                        return Grade.objects.filter(name=target_name).first() or Grade.objects.filter(name__icontains="الثالث").first()
                    return None

                graduated_cnt = 0
                promoted_to_3_cnt = 0
                promoted_to_2_cnt = 0
                retained_cnt = 0
                students_to_update = []

                # 🚀 المرحلة 1: معالجة الصف الثالث (تخريج الناجحين)
                for g in grades_lvl3:
                    for student in active_students.filter(grade=g):
                        if student.enrollment_status == 'Promoted':
                            student.enrollment_status = 'Graduated'
                            graduated_cnt += 1
                        elif student.enrollment_status not in ['Dismissed', 'Graduated']:
                            student.enrollment_status = 'Retained'
                            retained_cnt += 1
                        students_to_update.append(student)

                # 🚀 المرحلة 2: معالجة الصف الثاني (ترقية للصف الثالث بحالة مستجد)
                for g in grades_lvl2:
                    next_g = find_next_grade(g)
                    for student in active_students.filter(grade=g):
                        if student.enrollment_status == 'Promoted':
                            if next_g:
                                student.grade = next_g
                            student.enrollment_status = 'New'  # 🔒 القفل: تغيير الحالة لمستجد يمنع القفز
                            promoted_to_3_cnt += 1
                        elif student.enrollment_status not in ['Dismissed', 'Graduated']:
                            student.enrollment_status = 'Retained'
                            retained_cnt += 1
                        students_to_update.append(student)

                # 🚀 المرحلة 3: معالجة الصف الأول (ترقية للصف الثاني بحالة مستجد)
                for g in grades_lvl1:
                    next_g = find_next_grade(g)
                    for student in active_students.filter(grade=g):
                        if student.enrollment_status == 'Promoted':
                            if next_g:
                                student.grade = next_g
                            student.enrollment_status = 'New'  # 🔒 القفل: تغيير الحالة لمستجد يمنع القفز
                            promoted_to_2_cnt += 1
                        elif student.enrollment_status not in ['Dismissed', 'Graduated']:
                            student.enrollment_status = 'Retained'
                            retained_cnt += 1
                        students_to_update.append(student)

                # 💾 حفظ جميع التعديلات في قاعدة البيانات دفعة واحدة بسرعة فائقة
                if students_to_update:
                    Student.objects.bulk_update(students_to_update, ['grade', 'enrollment_status'])

                msg = (
                    f"🎉 تم ترحيل المدرسة بالكامل بنجاح!\n\n"
                    f"🎓 إتمام مرحلة (خريجين): {graduated_cnt} طالب\n"
                    f"🚀 ارتقوا للصف الثالث: {promoted_to_3_cnt} طالب\n"
                    f"🚀 ارتقوا للصف الثاني: {promoted_to_2_cnt} طالب\n"
                    f"⚠️ باق للإعادة (راسب): {retained_cnt} طالب"
                )
                return JsonResponse({'success': True, 'message': msg})

        return JsonResponse({'success': False, 'error': 'الإجراء المطلوب غير معرّف.'})
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def add_remedial_program(request):
    """تسجيل البرنامج العلاجي"""
    active_year = get_active_year()
    students = Student.objects.filter(is_active=True).only('id', 'first_name', 'last_name', 'student_code')

    fee_setting = RemedialFeeSetting.objects.filter(academic_year=active_year).first()
    fee_per_subject = fee_setting.fee_per_subject if fee_setting else 150.00

    if request.method == 'POST':
        form = RemedialProgramForm(request.POST)
        if form.is_valid():
            remedial_record = form.save(commit=False)
            remedial_record.academic_year = active_year
            remedial_record.total_amount = remedial_record.subjects_count * Decimal(str(fee_per_subject))
            remedial_record.created_by = request.user
            remedial_record.save()
            messages.success(request, f"تم تسجيل الطالب {remedial_record.student.get_full_name()} في الكورس العلاجي بنجاح.")

            return redirect(f"{request.path}?{request.META.get('QUERY_STRING', '')}")
    else:
        form = RemedialProgramForm()

    remedial_records = RemedialProgramRecord.objects.filter(
        academic_year=active_year
    ).select_related('student').order_by('-created_at')[:50]

    context = {
        'form': form,
        'students': students,
        'fee_per_subject': float(fee_per_subject),
        'active_year': active_year,
        'remedial_records': remedial_records,
        'title': 'تسجيل البرنامج العلاجي'
    }
    return render(request, 'students/add_remedial.html', context)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])  # 🟢 السماح بالربط بين السيرفرات دون حظر 403 Forbidden
@parser_classes([MultiPartParser, FormParser, JSONParser])  # 🟢 تفعيل قراءة واستقبال صور الطالب والمستندات
def receive_online_admission(request):
    """استقبال طلبات الحجز القادمة من المنظومة الخارجية وتوثيق الصور والمستندات"""
    serializer = OnlineAdmissionSerializer(data=request.data)

    if serializer.is_valid():
        try:
            active_year = get_active_year()
            student = serializer.save(
                academic_year=active_year,
                enrollment_status='New',
                is_active=True
            )

            return Response({
                'success': True,
                'message': f'تم استقبال حجز الطالب {student.get_full_name()} بنجاح.',
                'student_code': student.student_code
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                'success': False,
                'error': f'حدث خطأ أثناء الحفظ الداخلي: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'success': False,
        'errors': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


@login_required
@require_POST
def update_single_status_ajax(request):
    try:
        data = json.loads(request.body)
        student_id = data.get('student_id')
        new_status = data.get('status')

        student = Student.objects.get(id=student_id)
        student.enrollment_status = new_status
        student.save()

        return JsonResponse({'success': True, 'message': 'تم التحديث بنجاح'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def bulk_update_academic_status_ajax(request):
    try:
        data = json.loads(request.body)
        action = data.get('action')
        active_year = get_active_year()

        # ========================================================
        # 1. الترحيل الشامل لجميع صفوف المدرسة دفعة واحدة
        # ========================================================
        if action == 'execute_school_wide_promotion':
            with transaction.atomic():
                active_students = Student.objects.filter(academic_year=active_year, is_active=True)

                # صمام أمان: التحقق من وجود طلاب ناجحين مؤهلين للترحيل
                if not active_students.filter(enrollment_status='Promoted').exists():
                    return JsonResponse({
                        'success': False,
                        'error': '🛑 لا يوجد أي طالب بحالة "منقول" في المدرسة! تأكد من رصد درجات واعتماد نتائج الطلاب أولاً.'
                    })

                all_grades = Grade.objects.all()
                grades_lvl3 = [g for g in all_grades if "الثالث" in g.name]
                grades_lvl2 = [g for g in all_grades if "الثاني" in g.name or "الثانى" in g.name]
                grades_lvl1 = [g for g in all_grades if "الأول" in g.name or "الاول" in g.name]

                # دالة مطابقة الصف التالي للحفاظ على نوع الدراسة والشعبة (منتظم / عمال)
                def find_next_grade(current_g):
                    c_name = current_g.name
                    if "الأول" in c_name or "الاول" in c_name:
                        target_name = c_name.replace("الأول", "الثاني").replace("الاول", "الثاني")
                        return Grade.objects.filter(name=target_name).first() or Grade.objects.filter(name__icontains="الثاني").first()
                    elif "الثاني" in c_name or "الثانى" in c_name:
                        target_name = c_name.replace("الثاني", "الثالث").replace("الثانى", "الثالث")
                        return Grade.objects.filter(name=target_name).first() or Grade.objects.filter(name__icontains="الثالث").first()
                    return None

                graduated_cnt = 0
                promoted_to_3_cnt = 0
                promoted_to_2_cnt = 0
                retained_cnt = 0
                students_to_update = []

                # المرحلة 1: معالجة الصف الثالث (الناجح خريج، والباقي راسب)
                for g in grades_lvl3:
                    for student in active_students.filter(grade=g):
                        if student.enrollment_status == 'Promoted':
                            student.enrollment_status = 'Graduated'
                            graduated_cnt += 1
                        elif student.enrollment_status not in ['Dismissed', 'Graduated']:
                            student.enrollment_status = 'Retained'
                            retained_cnt += 1
                        students_to_update.append(student)

                # المرحلة 2: معالجة الصف الثاني (ترقية للصف الثالث بحالة مستجد لمنع القفز)
                for g in grades_lvl2:
                    next_g = find_next_grade(g)
                    for student in active_students.filter(grade=g):
                        if student.enrollment_status == 'Promoted':
                            if next_g:
                                student.grade = next_g
                            student.enrollment_status = 'New'  # 🔒 تحويله لمستجد يحميه من أي ترحيل تالٍ
                            promoted_to_3_cnt += 1
                        elif student.enrollment_status not in ['Dismissed', 'Graduated']:
                            student.enrollment_status = 'Retained'
                            retained_cnt += 1
                        students_to_update.append(student)

                # المرحلة 3: معالجة الصف الأول (ترقية للصف الثاني بحالة مستجد لمنع القفز)
                for g in grades_lvl1:
                    next_g = find_next_grade(g)
                    for student in active_students.filter(grade=g):
                        if student.enrollment_status == 'Promoted':
                            if next_g:
                                student.grade = next_g
                            student.enrollment_status = 'New'  # 🔒 تحويله لمستجد يحميه من أي ترحيل تالٍ
                            promoted_to_2_cnt += 1
                        elif student.enrollment_status not in ['Dismissed', 'Graduated']:
                            student.enrollment_status = 'Retained'
                            retained_cnt += 1
                        students_to_update.append(student)

                # حفظ التعديلات لجميع الطلاب دفعة واحدة
                if students_to_update:
                    Student.objects.bulk_update(students_to_update, ['grade', 'enrollment_status'], batch_size=500)

                msg = (
                    f"🎉 تم ترحيل المدرسة بالكامل بنجاح!\n\n"
                    f"🎓 إتمام مرحلة (الصف الثالث): {graduated_cnt} طالب\n"
                    f"🚀 ترقية إلى الصف الثالث: {promoted_to_3_cnt} طالب\n"
                    f"🚀 ترقية إلى الصف الثاني: {promoted_to_2_cnt} طالب\n"
                    f"⚠️ باق للإعادة (راسب): {retained_cnt} طالب"
                )
                return JsonResponse({'success': True, 'message': msg})

        # ========================================================
        # 2. ترحيل صف دراسي واحد محدد
        # ========================================================
        elif action == 'execute_promotion':
            grade_id = data.get('grade_id')
            if not grade_id:
                return JsonResponse({'success': False, 'error': 'لم يتم تحديد الصف الدراسي المستهدف.'})

            try:
                with transaction.atomic():
                    current_grade = Grade.objects.get(id=grade_id)
                    students_to_process = Student.objects.filter(
                        academic_year=active_year,
                        grade_id=grade_id,
                        is_active=True
                    )

                    has_promoted = students_to_process.filter(enrollment_status='Promoted').exists()
                    if not has_promoted:
                        return JsonResponse({
                            'success': False,
                            'error': '🛑 لا يوجد أي طالب بحالة "منقول" في هذا الصف! يرجى اعتماد الناجحين أولاً.'
                        })

                    next_grade = None
                    current_name = current_grade.name

                    if "الاول" in current_name or "الأول" in current_name:
                        target_name = current_name.replace("الأول", "الثاني").replace("الاول", "الثاني")
                        next_grade = Grade.objects.filter(name=target_name).first() or Grade.objects.filter(name__icontains="الثاني").first()
                    elif "الثاني" in current_name or "الثانى" in current_name:
                        target_name = current_name.replace("الثاني", "الثالث").replace("الثانى", "الثالث")
                        next_grade = Grade.objects.filter(name=target_name).first() or Grade.objects.filter(name__icontains="الثالث").first()

                    updated_count = 0
                    students_to_update = []

                    for student in students_to_process:
                        if student.enrollment_status == 'Promoted':
                            if next_grade:
                                student.grade = next_grade
                                student.enrollment_status = 'New'  # 🟢 تحويله لمستجد لمنع الترحيل المتكرر
                            else:
                                student.enrollment_status = 'Graduated'
                        elif student.enrollment_status not in ['Dismissed', 'Graduated']:
                            student.enrollment_status = 'Retained'

                        students_to_update.append(student)
                        updated_count += 1

                    if students_to_update:
                        Student.objects.bulk_update(students_to_update, ['grade', 'enrollment_status'], batch_size=500)

                    return JsonResponse({
                        'success': True,
                        'message': f'تم ترحيل وتقييم حالة ({updated_count}) طالب بنجاح.'
                    })

            except Grade.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'الصف الدراسي المحدد غير موجود بقاعدة البيانات.'})

        # ========================================================
        # 3. تسجيل رسوب المحدد فقط
        # ========================================================
        elif action == 'mark_failed':
            student_ids = data.get('student_ids', [])
            if not student_ids:
                return JsonResponse({'success': False, 'error': 'لم يتم تحديد أي طلاب!'})

            updated = Student.objects.filter(id__in=student_ids).update(enrollment_status='Retained')
            return JsonResponse({'success': True, 'message': f'تم تسجيل {updated} طالب كراسبين بنجاح.'})

        # ========================================================
        # 4. نقل باقي طلاب الصف
        # ========================================================
        elif action == 'promote_rest':
            grade_id = data.get('grade_id')
            if not grade_id:
                return JsonResponse({'success': False, 'error': 'يجب تحديد الصف الدراسي من الفلتر أولاً!'})

            updated_count = Student.objects.filter(
                grade_id=grade_id,
                is_active=True
            ).exclude(enrollment_status='Retained').update(enrollment_status='Promoted')

            return JsonResponse({'success': True, 'message': f'تم اعتماد نجاح {updated_count} طالب بنجاح!'})

        return JsonResponse({'success': False, 'error': 'الإجراء المطلوب غير معرّف أو غير مدعوم.'})

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def save_student_gate_block(request):
    """دالة استقبال بيانات مودال الحظر وحفظها"""
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        action_type = request.POST.get('action_type')
        student = get_object_or_404(Student, id=student_id)

        if action_type == 'unblock':
            student.is_blocked_at_gate = False
            student.gate_block_reason = ""
            student.gate_blocked_from = None
            student.gate_blocked_to = None
            student.save()
            messages.success(request, f"تم رفع حظر بوابة الأمن عن الطالب {student.get_full_name()} بنجاح.")
        else:
            student.is_blocked_at_gate = True
            student.gate_block_reason = request.POST.get('gate_block_reason')
            student.gate_blocked_from = request.POST.get('gate_blocked_from') if request.POST.get('gate_blocked_from') else None
            student.gate_blocked_to = request.POST.get('gate_blocked_to') if request.POST.get('gate_blocked_to') else None
            student.save()
            messages.success(request, f"تم تطبيق حظر بوابة الأمن على الطالب {student.get_full_name()} بنجاح.")

        return redirect('student_registry')


@login_required
def student_id_card_view(request, student_code):
    student = get_object_or_404(Student, student_code=student_code)
    return render(request, 'students/student_id_card.html', {'student': student})


@login_required
def security_scanner_view(request):
    return render(request, 'students/security_scanner.html')


@csrf_exempt
@login_required
def api_record_qr_attendance(request):
    if not request.user.is_staff:
        return JsonResponse({
            'status': 'error',
            'message': 'غير مصرح لك بتسجيل حضور الطلاب.'
        }, status=403)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            scanned_code = data.get('student_code')
            action = data.get('action', 'save')

            if not scanned_code:
                return JsonResponse({'status': 'error', 'message': 'لم يتم التعرف على الكود.'}, status=400)

            student = Student.objects.filter(student_code=scanned_code).first()
            if not student:
                return JsonResponse({'status': 'error', 'message': 'هذا الكود غير مسجل في السيستم نهائياً!'})

            active_year = get_active_year()
            today = timezone.now().date()

            is_dismissed = ReEnrollmentRecord.objects.filter(
                student=student,
                academic_year=active_year,
                status='dismissed'
            ).exists()

            is_gate_blocked = False
            if student.is_blocked_at_gate:
                if student.gate_blocked_from and student.gate_blocked_to:
                    if student.gate_blocked_from <= today <= student.gate_blocked_to:
                        is_gate_blocked = True
                else:
                    is_gate_blocked = True

            allowed_entry = True
            block_reason = ""

            if not student.is_active:
                allowed_entry = False
                block_reason = "الطالب غير نشط بالسيستم"
            elif is_gate_blocked:
                allowed_entry = False
                reason_text = student.gate_block_reason or "محظور إدارياً بقرار من المدرسة"
                if student.gate_blocked_from and student.gate_blocked_to:
                    block_reason = f"{reason_text} (فترة الحظر: من {student.gate_blocked_from} إلى {student.gate_blocked_to})"
                else:
                    block_reason = reason_text
            elif is_dismissed:
                allowed_entry = False
                block_reason = "الطالب مفصول لتخطي نسبة الغياب المسموحة"

            if action == 'check':
                return JsonResponse({
                    'status': 'success',
                    'allowed': allowed_entry,
                    'block_reason': block_reason,
                    'student_name': student.get_full_name(),
                    'grade': student.grade.name if student.grade else 'غير محدد',
                    'specialization': student.get_specialization_display() if student.specialization else 'شعبة عامة'
                })

            if action == 'save':
                if not allowed_entry:
                    return JsonResponse({'status': 'error', 'message': f'عذراً، هذا الطالب ممنوع من الدخول بسبب: {block_reason}'})

                security_agent = request.user.get_full_name() or request.user.username

                record, created = AttendanceRecord.objects.get_or_create(
                    student=student,
                    date=today,
                    academic_year=active_year,
                    defaults={
                        'status': 'present',
                        'notes': f'بوابة (QR) - بواسطة الموظف: {security_agent}'
                    }
                )

                if not created:
                    if record.status == 'present':
                        return JsonResponse({
                            'status': 'info',
                            'message': f'الطالب ({student.first_name}) مسجل حضوره بالفعل مسبقاً اليوم!'
                        })
                    else:
                        record.status = 'present'
                        record.notes = f'تم التعديل لحاضر عبر البوابة بواسطة: {security_agent}'
                        record.save()

                return JsonResponse({
                    'status': 'success',
                    'message': f'تم تسجيل حضور الطالب ({student.first_name}) بنجاح في المنظومة.'
                })

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'خطأ بالنظام: {str(e)}'})

    return JsonResponse({'status': 'error', 'message': 'طلب غير صالح.'}, status=400)


@login_required
def report_class_roster_view(request):
    active_year = get_active_year()
    grade_id = request.GET.get('grade')
    classroom_id = request.GET.get('classroom')

    students = []
    selected_grade = None
    selected_classroom = None

    if grade_id:
        selected_grade = get_object_or_404(Grade, id=grade_id)
        query = Student.objects.filter(academic_year=active_year, grade=selected_grade, is_active=True).order_by('first_name')
        if classroom_id:
            selected_classroom = get_object_or_404(Classroom, id=classroom_id)
            query = query.filter(classroom=selected_classroom)
        students = query.only('student_code', 'first_name', 'last_name', 'religion', 'gender')

    context = {
        'students': students,
        'all_grades': Grade.objects.all(),
        'all_classrooms': Classroom.objects.all(),
        'selected_grade': selected_grade,
        'selected_classroom': selected_classroom,
        'active_year': active_year,
        'title': 'كشف فصل دراسي'
    }
    return render(request, 'students/reports/class_roster.html', context)


@login_required
def report_student_registry_view(request):
    active_year = get_active_year()

    grade_id = request.GET.get('grade_id')
    classroom_id = request.GET.get('classroom_id')

    students = Student.objects.filter(
        academic_year=active_year, is_active=True
    ).select_related('grade', 'classroom')

    filter_title = "الشامل للطلاب النشطين (الكل)"

    if grade_id:
        students = students.filter(grade_id=grade_id)
        selected_grade = Grade.objects.filter(id=grade_id).first()
        if selected_grade:
            filter_title = f"الصف: {selected_grade.name}"

    if classroom_id:
        students = students.filter(classroom_id=classroom_id)

    students = students.order_by('grade', 'classroom', 'first_name')

    context = {
        'students': students,
        'total_count': students.count(),
        'active_year': active_year,
        'all_grades': Grade.objects.all(),
        'filter_title': filter_title,
        'title': 'السجل المدني للطلاب'
    }
    return render(request, 'students/reports/student_registry.html', context)


@login_required
def report_dismissed_students_view(request):
    active_year = get_active_year()

    dismissed_records = ReEnrollmentRecord.objects.filter(
        academic_year=active_year, status='dismissed'
    ).select_related('student__grade', 'student__classroom').order_by('-dismissal_date')

    context = {
        'records': dismissed_records,
        'total_count': dismissed_records.count(),
        'active_year': active_year,
        'title': 'سجل الطلاب المفصولين أكاديمياً'
    }
    return render(request, 'students/reports/dismissed_students.html', context)


@login_required
def attendance_report_view(request):
    active_year = get_active_year()

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if not date_from:
        date_from = timezone.now().date().strftime('%Y-%m-%d')
    if not date_to:
        date_to = timezone.now().date().strftime('%Y-%m-%d')

    grade_id = request.GET.get('grade')
    status_filter = request.GET.get('status')

    records = AttendanceRecord.objects.filter(
        academic_year=active_year,
        date__range=[date_from, date_to]
    ).select_related('student', 'student__grade', 'student__classroom')

    if grade_id:
        records = records.filter(student__grade_id=grade_id)
    if status_filter:
        records = records.filter(status=status_filter)

    counts = records.aggregate(
        total=Count('id'),
        present=Count('id', filter=Q(status='present')),
        absent=Count('id', filter=Q(status='absent')),
        excused=Count('id', filter=Q(status='excused'))
    )

    total_records = counts['total'] or 0
    present_count = counts['present'] or 0
    absent_count = counts['absent'] or 0
    excused_count = counts['excused'] or 0

    context = {
        'records': records.order_by('-date', 'student__first_name'),
        'total_records': total_records,
        'present_count': present_count,
        'absent_count': absent_count,
        'excused_count': excused_count,
        'all_grades': Grade.objects.all(),
        'title': 'التقرير الشامل للغياب والحضور',
    }
    return render(request, 'students/attendance_report.html', context)


@login_required
def take_daily_attendance_view(request):
    active_year = get_active_year()
    students_data = []
    initial_date = timezone.now().date()

    if request.method == 'POST' and request.POST.get('save_attendance'):
        posted_date = request.POST.get('attendance_date')
        posted_term = request.POST.get('attendance_term')
        posted_grade = request.POST.get('grade', '')
        posted_classroom = request.POST.get('classroom', '')
        student_ids = request.POST.getlist('student_ids')

        with transaction.atomic():
            existing_records = AttendanceRecord.objects.filter(
                date=posted_date,
                student_id__in=student_ids
            )
            existing_map = {str(rec.student_id): rec for rec in existing_records}

            records_to_create = []
            records_to_update = []

            for s_id in student_ids:
                status = request.POST.get(f'status_{s_id}', 'present')
                notes = request.POST.get(f'notes_{s_id}', '')

                if s_id in existing_map:
                    record = existing_map[s_id]
                    record.academic_year = active_year
                    record.term = posted_term
                    record.status = status
                    record.notes = notes
                    records_to_update.append(record)
                else:
                    records_to_create.append(
                        AttendanceRecord(
                            student_id=s_id,
                            date=posted_date,
                            academic_year=active_year,
                            term=posted_term,
                            status=status,
                            notes=notes
                        )
                    )

            if records_to_create:
                AttendanceRecord.objects.bulk_create(records_to_create)

            if records_to_update:
                AttendanceRecord.objects.bulk_update(
                    records_to_update,
                    fields=['academic_year', 'term', 'status', 'notes']
                )

        messages.success(request, "تم حفظ كشف الحضور والغياب بنجاح.")
        redirect_url = reverse('take_attendance') + f"?date={posted_date}&grade={posted_grade}&classroom={posted_classroom}&term={posted_term}"
        return redirect(redirect_url)

    form = AttendanceFilterForm(request.GET or None, initial={'date': initial_date})

    if form.is_valid():
        filter_date = form.cleaned_data['date']
        grade_id = form.cleaned_data['grade']
        classroom_id = form.cleaned_data['classroom']

        students_query = Student.objects.filter(academic_year=active_year, grade=grade_id, is_active=True)
        if classroom_id:
            students_query = students_query.filter(classroom=classroom_id)

        students_list = students_query.only('id', 'first_name', 'last_name', 'student_code').order_by('first_name')

        existing_records = AttendanceRecord.objects.filter(
            academic_year=active_year, date=filter_date, student__in=students_list
        ).values('student_id', 'status', 'notes')

        records_map = {rec['student_id']: rec for rec in existing_records}

        for student in students_list:
            rec = records_map.get(student.id, {'status': 'present', 'notes': ''})
            students_data.append({
                'student': student,
                'status': rec['status'],
                'notes': rec['notes']
            })

    context = {
        'form': form,
        'students_data': students_data,
        'active_year': active_year,
        'title': 'تسجيل الحضور والغياب اليومي'
    }
    # إذا كنت تريد واجهة الموبايل السريعة:
    return render(request, 'students/take_attendance.html', context)



@login_required
def take_daily_attendance_mobile_view(request):
    """
    نسخة الموبايل من شاشة تحضير الحضور والغياب.
    نفس منطق جلب البيانات بالظبط، لكنها لا تحتوي على نموذج الحفظ الجماعي (POST)
    لأن شاشة الموبايل بترصد وتحفظ كل طالب لحظيًا عن طريق api_save_attendance_robust.
    """
    active_year = get_active_year()
    students_data = []
    initial_date = timezone.now().date()

    form = AttendanceFilterForm(request.GET or None, initial={'date': initial_date})

    if form.is_valid():
        filter_date = form.cleaned_data['date']
        grade_id = form.cleaned_data['grade']
        classroom_id = form.cleaned_data['classroom']

        students_query = Student.objects.filter(academic_year=active_year, grade=grade_id, is_active=True)
        if classroom_id:
            students_query = students_query.filter(classroom=classroom_id)

        students_list = students_query.only('id', 'first_name', 'last_name', 'student_code', 'whatsapp_number').order_by('first_name')

        existing_records = AttendanceRecord.objects.filter(
            academic_year=active_year, date=filter_date, student__in=students_list
        ).values('student_id', 'status', 'notes')

        records_map = {rec['student_id']: rec for rec in existing_records}

        for student in students_list:
            rec = records_map.get(student.id, {'status': 'present', 'notes': ''})
            students_data.append({
                'student': student,
                'status': rec['status'],
                'notes': rec['notes']
            })

    context = {
        'form': form,
        'students_data': students_data,
        'active_year': active_year,
        'title': 'تحضير الغياب - الموبايل'
    }
    # return render(request, 'attendance/attendance_mobile.html', context)
    return render(request, 'students/attendance_mobile.html', context)


@login_required
def academic_final_report_view(request):
    active_year = get_active_year()
    grade_id = request.GET.get('grade_id')

    results_summary = []

    if grade_id:
        configs = SubjectConfig.objects.filter(grade_id=grade_id, academic_year=active_year)
        configs_map = {c.subject_id: c for c in configs}

        students = Student.objects.filter(
            academic_year=active_year, grade_id=grade_id, is_active=True
        ).select_related('grade', 'classroom').order_by('first_name')

        all_results = ExamResult.objects.filter(
            academic_year=active_year, exam_type='term', student__grade_id=grade_id
        )

        student_marks_matrix = {}
        for res in all_results:
            if res.student_id not in student_marks_matrix:
                student_marks_matrix[res.student_id] = {}
            if res.subject_id not in student_marks_matrix[res.student_id]:
                student_marks_matrix[res.student_id][res.subject_id] = 0

            student_marks_matrix[res.student_id][res.subject_id] += res.total_score

        for student in students:
            failed_subjects = []
            passed_count = 0
            student_profile = student_marks_matrix.get(student.id, {})

            for sub_id, config in configs_map.items():
                total_student_score = student_profile.get(sub_id, 0)

                if total_student_score < config.passing_score:
                    failed_subjects.append({
                        'subject_name': config.subject.name,
                        'score': total_student_score,
                        'passing_limit': config.passing_score
                    })
                else:
                    passed_count += 1

            if len(failed_subjects) == 0:
                final_status = 'passed'
                status_label = "ناجح ومنقول للدور الأول"
            elif 1 <= len(failed_subjects) <= 2:
                final_status = 'second_session'
                status_label = f"له دور ثانٍ في ({len(failed_subjects)}) مواد"
            else:
                final_status = 'failed'
                status_label = "راسب وباقٍ للإعادة"

            results_summary.append({
                'student': student,
                'failed_subjects': failed_subjects,
                'failed_count': len(failed_subjects),
                'status': final_status,
                'status_label': status_label
            })

    context = {
        'all_grades': Grade.objects.all(),
        'selected_grade': grade_id,
        'results_summary': results_summary,
        'active_year': active_year,
        'title': 'التقرير الأكاديمي النهائي للكنترول'
    }
    return render(request, 'students/academic_final_report.html', context)


@login_required
def manage_reenrollments_view(request):
    active_year = get_active_year()

    if request.method == 'POST' and request.POST.get('action') == 'process_re_enroll':
        record_id = request.POST.get('record_id')

        try:
            with transaction.atomic():
                record = ReEnrollmentRecord.objects.get(id=record_id, academic_year=active_year)
                student = record.student

                record.status = 're_enrolled'
                record.reenrollment_date = timezone.now().date()
                record.save()

                student.enrollment_status = 'New'
                student.is_active = True
                student.save()

            messages.success(request, f"تم إعادة قيد الطالب {student.get_full_name()} بنجاح، ويمكنه الآن الحضور ورصد درجاته.")
        except Exception as e:
            messages.error(request, f"فشل تنفيذ العملية! السبب: {str(e)}")
        return redirect('manage_reenrollments')

    pending_records = ReEnrollmentRecord.objects.filter(
        academic_year=active_year, status='dismissed'
    ).select_related('student__grade', 'student__classroom')

    context = {
        'pending_records': pending_records,
        'title': 'إعادة قيد الطلاب المفصولين'
    }
    return render(request, 'students/manage_reenrollments.html', context)


@login_required
def record_exam_marks_view(request):
    active_year = get_active_year()
    students_data = []
    subject_config = None

    form = ExamResultFilterForm(request.GET or None)

    if form.is_valid():
        exam_type = form.cleaned_data['exam_type']
        term = form.cleaned_data['term']
        month = form.cleaned_data['month']
        grade_id = form.cleaned_data['grade']
        classroom_id = form.cleaned_data['classroom']
        subject_id = form.cleaned_data['subject']

        subject_config = SubjectConfig.objects.filter(
            subject_id=subject_id, grade_id=grade_id, academic_year=active_year
        ).first()

        students_query = Student.objects.filter(
            academic_year=active_year, grade=grade_id, is_active=True
        )
        if classroom_id:
            students_query = students_query.filter(classroom=classroom_id)

        students = students_query.only('id', 'first_name', 'last_name', 'student_code').order_by('first_name')

        existing_results = ExamResult.objects.filter(
            academic_year=active_year, exam_type=exam_type, term=term, month=month, subject_id=subject_id
        ).values('student_id', 'cultural_score', 'practical_score', 'is_absent')

        results_map = {r['student_id']: r for r in existing_results}

        for student in students:
            res = results_map.get(student.id, {'cultural_score': 0, 'practical_score': 0, 'is_absent': False})
            students_data.append({
                'student': student,
                'cultural_score': res['cultural_score'],
                'practical_score': res['practical_score'],
                'is_absent': res['is_absent']
            })

    if request.method == 'POST' and 'save_marks' in request.POST:
        posted_form = ExamResultFilterForm(request.POST)
        if posted_form.is_valid():
            p_exam_type = posted_form.cleaned_data['exam_type']
            p_term = posted_form.cleaned_data['term']
            p_month = posted_form.cleaned_data['month']
            p_subject_id = posted_form.cleaned_data['subject']

            student_ids = request.POST.getlist('post_student_ids')

            with transaction.atomic():
                for s_id in student_ids:
                    c_score = request.POST.get(f'cultural_{s_id}', 0)
                    p_score = request.POST.get(f'practical_{s_id}', 0)
                    absent = request.POST.get(f'absent_{s_id}') == 'true'

                    ExamResult.objects.update_or_create(
                        student_id=s_id,
                        subject=p_subject_id,
                        academic_year=active_year,
                        exam_type=p_exam_type,
                        term=p_term,
                        month=p_month,
                        defaults={
                            'cultural_score': Decimal(c_score) if not absent else 0,
                            'practical_score': Decimal(p_score) if not absent else 0,
                            'is_absent': absent
                        }
                    )
            messages.success(request, "تم حفظ ورصد درجات الطلاب بنجاح.")
            sub_id_val = p_subject_id.id if hasattr(p_subject_id, 'id') else p_subject_id
            return redirect(reverse('record_marks') + f'?exam_type={p_exam_type}&term={p_term}&month={p_month or ""}&grade={request.POST.get("grade")}&classroom={request.POST.get("classroom") or ""}&subject={sub_id_val}')

    context = {
        'form': form,
        'students_data': students_data,
        'subject_config': subject_config,
        'title': 'كنترول رصد الدرجات التفصيلي'
    }
    return render(request, 'students/record_marks.html', context)


def save_remedial_from_registry(request):
    if request.method == 'POST':
        student_id = request.POST.get('student')
        subjects_count = int(request.POST.get('subjects_count', 1))
        notes = request.POST.get('notes', '')

        try:
            student = Student.objects.get(id=student_id)
            active_year = get_active_year()
            fee_per_subject = 150.00
            total_amount = subjects_count * fee_per_subject

            RemedialProgramRecord.objects.create(
                student=student,
                academic_year=active_year,
                subjects_count=subjects_count,
                total_amount=total_amount,
                notes=notes,
                is_paid=False
            )
            return JsonResponse({'success': True, 'message': f'تم تأكيد البرنامج للطالب {student.first_name} بنجاح.'})

        except Student.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'خطأ: لم يتم العثور على الطالب.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'طلب غير صالح.'})


@login_required
def manage_remedial_dashboard(request):
    active_year = get_active_year()

    unpaid_count = RemedialProgramRecord.objects.filter(academic_year=active_year, is_paid=False).count()
    paid_count = RemedialProgramRecord.objects.filter(academic_year=active_year, is_paid=True).count()

    unpaid_records = RemedialProgramRecord.objects.filter(
        academic_year=active_year,
        is_paid=False
    ).select_related('student').defer(
        'student__image', 'student__address', 'student__birth_place', 'student__father_job', 'student__mother_name'
    ).order_by('-created_at')[:50]

    paid_records = RemedialProgramRecord.objects.filter(
        academic_year=active_year,
        is_paid=True
    ).select_related('student').defer(
        'student__image', 'student__address', 'student__birth_place', 'student__father_job', 'student__mother_name'
    ).order_by('-created_at')[:50]

    context = {
        'unpaid_count': unpaid_count,
        'paid_count': paid_count,
        'unpaid_records': unpaid_records,
        'paid_records': paid_records,
        'active_year': active_year,
    }
    return render(request, 'students/remedial_dashboard.html', context)


@login_required
def pay_remedial_record(request, record_id):
    """
    دالة تحصيل البرنامج العلاجي:
    - تُحول حالة البرنامج إلى (خالص)
    - تُسمع فوراً في الخزينة العامة (GeneralLedger)
    """
    if request.method == 'POST':
        try:
            # 🟢 استخدام transaction.atomic لضمان عدم حدوث خطأ نصفي
            with transaction.atomic():
                record = RemedialProgramRecord.objects.get(id=record_id)

                if not record.is_paid:
                    # 1. تحديث حالة الكورس إلى (مسدد)
                    record.is_paid = True
                    record.save()

                    # 2. 🟢 التسميع المباشر في الخزينة العامة
                    receipt_code = f"REM-{record.id}-{int(time.time())}"

                    GeneralLedger.objects.create(
                        student=record.student,
                        amount=record.total_amount,
                        category='other',  # تصنيف كإيرادات أخرى أو كما تفضل
                        notes=f"رسوم برنامج علاجي - لعدد ({record.subjects_count}) مادة",
                        receipt_number=receipt_code,
                        date=timezone.now(),  # حفظ التاريخ والوقت بدقة
                        collected_by=request.user
                    )

                    return JsonResponse({'success': True, 'message': 'تم تسجيل السداد بنجاح وتسميع المبلغ في الخزينة العامة.'})
                else:
                    return JsonResponse({'success': False, 'error': 'هذه المديونية مسددة بالفعل.'})

        except RemedialProgramRecord.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'السجل غير موجود.'})
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return JsonResponse({'success': False, 'error': f'حدث خطأ في النظام: {str(e)}'})

    return JsonResponse({'success': False, 'error': 'طلب غير صالح.'})



@login_required
def misc_revenue_view(request):
    """
    شاشة وإدارة الإيرادات المتنوعة:
    - إمكانية جعل البيان (title) اختياريًا واستخدام التصنيف كبديل تلقائي.
    - التحقق الدقيق من صحة إدخال المبالغ المالية.
    - التعامل الفائق بالسرعة مع تواريخ DateTimeField.
    - التسميع الآلي والآمن في الخزينة العامة داخل معاملة ذرية (transaction.atomic).
    """
    if request.method == 'POST':
        try:
            revenue_type = request.POST.get('revenue_type', 'other').strip()
            raw_title = request.POST.get('title', '').strip()
            raw_amount = request.POST.get('amount', '0').strip()
            notes = request.POST.get('notes', '').strip()

            # 1. التحقق الفائق من صحة المبلغ المالي
            try:
                amount = Decimal(raw_amount)
                if amount <= Decimal('0.00'):
                    messages.error(request, "🛑 خطأ: يجب أن يكون المبلغ المورد أكبر من صفر.")
                    return redirect('misc_revenue')
            except (InvalidOperation, ValueError):
                messages.error(request, "🛑 خطأ: يرجى إدخال مبلغ مالي صحيح.")
                return redirect('misc_revenue')

            # 2. معالجة البيان (العنوان) - إذا تُرك فارغاً يتم استخدام اسم التصنيف تلقائياً
            if not raw_title:
                revenue_type_dict = dict(MiscellaneousRevenue.REVENUE_TYPES)
                title = revenue_type_dict.get(revenue_type, "إيراد متنوع")
            else:
                title = raw_title

            # 3. الحفظ المزدوج والتسميع بالخزينة داخل Atomic Transaction
            with transaction.atomic():
                misc_rev = MiscellaneousRevenue.objects.create(
                    title=title,
                    revenue_type=revenue_type,
                    amount=amount,
                    notes=notes,
                    collected_by=request.user
                )

                # استيراد موديل الخزينة العامة المرن
                try:
                    from treasury.models import GeneralLedger
                except ImportError:
                    from finance.models import GeneralLedger

                unique_receipt = f"MISC-{misc_rev.id}-{int(time.time())}"

                GeneralLedger.objects.create(
                    student=None,
                    amount=amount,
                    category='other',
                    notes=f"إيراد متنوع: {title} ({misc_rev.get_revenue_type_display()})",
                    receipt_number=unique_receipt,
                    date=timezone.now(),
                    collected_by=request.user
                )

            messages.success(request, f"✅ تم تسجيل الإيراد ({title}) بقيمة {amount} ج.م بنجاح وتوريده للخزينة.")

        except Exception as e:
            print(traceback.format_exc())
            messages.error(request, f"❌ فشل تسجيل الإيراد! السبب: {str(e)}")

        return redirect('misc_revenue')

    # =========================================================
    # ⚡ استعلامات العرض (GET) بأقصى سرعة وأداء
    # =========================================================
    today = timezone.localtime().date()

    # حساب الإيراد الكلي أوتوماتيكياً بدقة حتى في حالة عدم وجود سجلات
    total_revenue = MiscellaneousRevenue.objects.aggregate(
        total=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField())
    )['total']

    # حساب إيرادات اليوم باستخدام date__date المتوافق مع DateTimeField
    today_revenue = MiscellaneousRevenue.objects.filter(
        date__date=today
    ).aggregate(
        total=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField())
    )['total']

    # جلب أحدث 50 حركة مع تقليل استعلامات قاعدة البيانات
    revenues = MiscellaneousRevenue.objects.select_related(
        'collected_by'
    ).all().order_by('-date')[:50]

    context = {
        'revenues': revenues,
        'total_revenue': total_revenue,
        'today_revenue': today_revenue,
        'title': 'إدارة الإيرادات المتنوعة'
    }
    return render(request, 'finance/misc_revenue.html', context)



# @login_required
# def misc_revenue_view(request):
#     if request.method == 'POST':
#         try:
#             with transaction.atomic():
#                 title = request.POST.get('title')
#                 revenue_type = request.POST.get('revenue_type')
#                 amount = Decimal(request.POST.get('amount', 0))
#                 notes = request.POST.get('notes', '')

#                 misc_rev = MiscellaneousRevenue.objects.create(
#                     title=title,
#                     revenue_type=revenue_type,
#                     amount=amount,
#                     notes=notes,
#                     collected_by=request.user
#                 )

#                 try:
#                     from treasury.models import GeneralLedger
#                 except ImportError:
#                     from finance.models import GeneralLedger

#                 unique_receipt = f"MISC-{misc_rev.id}-{int(time.time())}"

#                 GeneralLedger.objects.create(
#                     student=None,
#                     amount=amount,
#                     category='other',
#                     notes=f"إيراد متنوع: {title} ({misc_rev.get_revenue_type_display()})",
#                     receipt_number=unique_receipt,
#                     collected_by=request.user
#                 )

#             messages.success(request, f"تم تسجيل الإيراد ({title}) بقيمة {amount} ج.م بنجاح وتوريده للخزينة.")

#         except Exception as e:
#             print(traceback.format_exc())
#             messages.error(request, f"فشل تسجيل الإيراد! السبب: {str(e)}")

#         return redirect('misc_revenue')

#     today = timezone.now().date()

#     total_revenue = MiscellaneousRevenue.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

#     today_revenue = MiscellaneousRevenue.objects.filter(date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
#     revenues = MiscellaneousRevenue.objects.select_related('collected_by').all().order_by('-date')[:50]

#     context = {
#         'revenues': revenues,
#         'total_revenue': total_revenue,
#         'today_revenue': today_revenue,
#     }
#     return render(request, 'finance/misc_revenue.html', context)


@login_required
def bus_dashboard_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_route':
            try:
                BusRoute.objects.create(
                    name=request.POST.get('name'),
                    driver_name=request.POST.get('driver_name'),
                    driver_phone=request.POST.get('driver_phone'),
                    bus_number=request.POST.get('bus_number'),
                    capacity=request.POST.get('capacity', 20),
                    monthly_price=request.POST.get('monthly_price', 0),
                    term_price=request.POST.get('term_price', 0),
                    yearly_price=request.POST.get('yearly_price', 0),
                )
            except Exception as e:
                messages.error(request, f'خطأ أثناء إضافة الخط: {e}')
            return redirect('bus_dashboard')

        elif action == 'add_subscription':
            try:
                student_id = request.POST.get('student_id')
                route_id = request.POST.get('route_id')

                student = get_object_or_404(Student, id=student_id)
                route = get_object_or_404(BusRoute, id=route_id)

                BusSubscription.objects.create(
                    student=student,
                    route=route,
                    sub_type=request.POST.get('sub_type'),
                    start_date=request.POST.get('start_date'),
                    end_date=request.POST.get('end_date'),
                    required_amount=request.POST.get('required_amount', 0),
                    notes=request.POST.get('notes', '')
                )
            except Exception as e:
                messages.error(request, f'خطأ أثناء إضافة الاشتراك: {e}')
            return redirect('bus_dashboard')

        elif action == 'add_payment':
            sub_id = request.POST.get('subscription_id')
            amount = request.POST.get('amount_paid')

            try:
                with transaction.atomic():
                    subscription = get_object_or_404(BusSubscription, id=sub_id)

                    payment = BusPayment.objects.create(
                        subscription=subscription,
                        amount_paid=Decimal(amount),
                        collected_by=request.user,
                    )

                    try:
                        from treasury.models import GeneralLedger
                    except ImportError:
                        from finance.models import GeneralLedger

                    unique_receipt = f"BUS-{payment.id}-{int(time.time())}"

                    GeneralLedger.objects.create(
                        student=subscription.student,
                        amount=Decimal(amount),
                        category='bus',
                        notes=f"تحصيل اشتراك باص - خط: {subscription.route.name}",
                        receipt_number=unique_receipt,
                        collected_by=request.user
                    )

            except Exception as e:
                print(traceback.format_exc())
                messages.error(request, f"فشل التحصيل والتسميع! السبب: {str(e)}")

            return redirect('bus_dashboard')

    routes = BusRoute.objects.all()
    subscriptions = BusSubscription.objects.select_related('student', 'route').all()

    students = Student.objects.filter(is_active=True).values('id', 'first_name', 'last_name', 'student_code')

    total_bus_students = subscriptions.filter(is_active=True).count()
    total_revenue = sum(sub.total_paid for sub in subscriptions)
    total_debt = sum(sub.remaining_amount for sub in subscriptions if sub.remaining_amount > 0)

    context = {
        'routes': routes,
        'subscriptions': subscriptions,
        'students': students,
        'total_bus_students': total_bus_students,
        'total_revenue': total_revenue,
        'total_debt': total_debt,
        'today': timezone.now().date(),
    }
    return render(request, 'students/bus_dashboard.html', context)






@login_required
def api_student_quick_analytics(request, student_id):
    """
    API جلب البيانات التحليلية الشاملة للطالب بداخل النافذة المنبثقة
    """
    student = get_object_or_404(Student.objects.select_related('grade', 'academic_year'), id=student_id)

    enrollments = CourseGroup.objects.filter(student=student).select_related(
        'course_info__subject', 'course_info__teacher'
    ).annotate(
        attended_cnt=Count('sessions', filter=Q(sessions__attendance_status='attended'), distinct=True),
        total_paid_val=Coalesce(Sum('payments__amount_paid'), Value(Decimal('0.00')), output_field=DecimalField())
    )

    courses_data = []
    total_required_sum = Decimal('0.00')
    total_paid_sum = Decimal('0.00')
    total_sessions_sum = 0
    total_attended_sum = 0

    for e in enrollments:
        req = Decimal(str(e.required_amount or 0))
        paid = Decimal(str(e.total_paid_val or 0))
        rem_debt = max(Decimal('0.00'), req - paid)

        att = e.attended_cnt or 0
        rem_sess = max(0, e.total_sessions - att)

        total_required_sum += req
        total_paid_sum += paid
        total_sessions_sum += e.total_sessions
        total_attended_sum += att

        recent_sessions = list(e.sessions.filter(attendance_status='attended').order_by('-session_date').values_list('session_date', flat=True)[:5])
        recent_dates = [s.strftime('%Y-%m-%d') for s in recent_sessions if s]

        subject_name = e.course_info.subject.name if (e.course_info and e.course_info.subject) else '---'
        teacher_name = e.course_info.teacher.name if (e.course_info and e.course_info.teacher) else '---'

        courses_data.append({
            'id': e.id,
            'subject': subject_name,
            'teacher': teacher_name,
            'reg_date': e.registration_date.strftime('%Y-%m-%d') if e.registration_date else '---',
            'required_amount': float(req),
            'total_paid': float(paid),
            'remaining_debt': float(rem_debt),
            'total_sessions': e.total_sessions,
            'attended_sessions': att,
            'remaining_sessions': rem_sess,
            'progress_pct': int((att / e.total_sessions) * 100) if e.total_sessions > 0 else 0,
            'recent_dates': recent_dates
        })

    total_debt_sum = max(Decimal('0.00'), total_required_sum - total_paid_sum)

    return JsonResponse({
        'success': True,
        'student': {
            'id': student.id,
            'name': student.get_full_name(),
            'code': student.student_code or '---',
            'national_id': student.national_id or '---',
            'grade': student.grade.name if student.grade else 'عام',
            'year': student.academic_year.name if student.academic_year else '---'
        },
        'summary': {
            'total_courses': len(courses_data),
            'total_required': float(total_required_sum),
            'total_paid': float(total_paid_sum),
            'total_debt': float(total_debt_sum),
            'total_sessions': total_sessions_sum,
            'total_attended': total_attended_sum,
            'total_remaining_sessions': max(0, total_sessions_sum - total_attended_sum)
        },
        'courses': courses_data
    })


@login_required
def students_analytics_view(request):
    """
    شاشة التحليل الإحصائي العام والاشتراكات والمدرسين
    """
    active_year = get_active_year()

    time_filter = request.GET.get('time_filter', 'all')
    grade_id = request.GET.get('grade_id')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    now = timezone.now()

    base_students_qs = Student.objects.filter(is_active=True)
    if grade_id:
        base_students_qs = base_students_qs.filter(grade_id=grade_id)

    total_students = base_students_qs.count()

    enrollments_qs = CourseGroup.objects.select_related(
        'student', 'student__grade', 'course_info__subject', 'course_info__teacher'
    )

    if date_from and date_to:
        enrollments_qs = enrollments_qs.filter(registration_date__range=[date_from, date_to])
        time_filter = 'custom'
    elif time_filter == 'today':
        enrollments_qs = enrollments_qs.filter(registration_date=now.date())
    elif time_filter == 'week':
        enrollments_qs = enrollments_qs.filter(registration_date__gte=now.date() - timedelta(days=7))
    elif time_filter == 'month':
        enrollments_qs = enrollments_qs.filter(registration_date__gte=now.date() - timedelta(days=30))
    elif time_filter == 'year':
        enrollments_qs = enrollments_qs.filter(registration_date__gte=now.date() - timedelta(days=365))

    if grade_id:
        enrollments_qs = enrollments_qs.filter(student__grade_id=grade_id)

    enrolled_student_ids = set(enrollments_qs.values_list('student_id', flat=True).distinct())

    enrolled_count = len(enrolled_student_ids - {None})
    non_enrolled_count = max(0, total_students - enrolled_count)

    enrolled_students_qs = base_students_qs.filter(id__in=enrolled_student_ids).select_related(
        'grade', 'academic_year'
    ).order_by('first_name')

    non_enrolled_students_qs = base_students_qs.exclude(id__in=enrolled_student_ids).select_related(
        'grade', 'academic_year'
    ).order_by('first_name')

    # 🟢 1. تحليل كثافة المواد
    subject_analysis_qs = list(enrollments_qs.values(
        subject_name=F('course_info__subject__name')
    ).annotate(
        total=Count('id')
    ).order_by('-total'))

    # 🟢 2. تحليل انتشار المدرسين
    raw_teacher_stats = list(enrollments_qs.values(
        teacher_name=F('course_info__teacher__name')
    ).annotate(
        total_students=Count('id'),
        total_required=Coalesce(Sum('required_amount'), Value(Decimal('0.00')), output_field=DecimalField())
    ))

    payments_filtered = CoursePayment.objects.filter(course_enrollment__in=enrollments_qs)
    collected_map = {
        item['teacher_name']: item['total']
        for item in payments_filtered.values(
            teacher_name=F('course_enrollment__course_info__teacher__name')
        ).annotate(total=Sum('amount_paid'))
    }

    teacher_analysis = []
    for t in raw_teacher_stats:
        t_name = t['teacher_name']
        if not t_name:
            continue
        teacher_analysis.append({
            'teacher_name': t_name,
            'total_students': t['total_students'],
            'total_required': t['total_required'],
            'total_collected': collected_map.get(t_name, Decimal('0.00'))
        })

    teacher_analysis.sort(key=lambda x: x['total_students'], reverse=True)

    paginator_enrolled = Paginator(enrolled_students_qs, 10)
    page_enrolled = request.GET.get('page_e', 1)
    enrolled_page = paginator_enrolled.get_page(page_enrolled)

    paginator_non_enrolled = Paginator(non_enrolled_students_qs, 10)
    page_non_enrolled = request.GET.get('page_ne', 1)
    non_enrolled_page = paginator_non_enrolled.get_page(page_non_enrolled)

    context = {
        'total_students': total_students,
        'enrolled_count': enrolled_count,
        'non_enrolled_count': non_enrolled_count,
        'enrolled_students': enrolled_page,
        'non_enrolled_students': non_enrolled_page,
        'subject_analysis': subject_analysis_qs,
        'teacher_analysis': teacher_analysis,
        'all_grades': Grade.objects.all(),
        'selected_grade': grade_id,
        'current_filter': time_filter,
        'date_from': date_from,
        'date_to': date_to,
        'title': 'التحليل الإحصائي العام والمالي للاشتراكات'
    }

    return render(request, 'students/analytics_dashboard.html', context)





@login_required
def student_detail_analytics(request, student_id):
    student = get_object_or_404(Student, id=student_id)

    enrollments = CourseGroup.objects.filter(student=student).select_related(
        'course_info__subject',
        'course_info__teacher'
    )

    subscribed_subjects = enrollments.values_list('course_info__subject_id', flat=True)
    from .models import Subject
    other_subjects = Subject.objects.exclude(id__in=subscribed_subjects)

    context = {
        'student': student,
        'enrollments': enrollments,
        'other_subjects': other_subjects,
        'title': f'تحليل ملف: {student.get_full_name()}'
    }
    return render(request, 'students/student_detail.html', context)



@login_required
def course_prices_view(request):
    """
    لوحة تحكم المجموعات والاشتراكات المحسنة:
    - فلترة زمنية سريعة.
    - حساب أوتوماتيكي لثمن الكورس.
    - معالجة الحضور والمدفوعات على مستوى الصفحة الحالية فقط لضمان أداء فائق.
    """
    if request.method == 'POST':
        form = CourseGroupForm(request.POST)
        form.fields['student'].queryset = Student.objects.filter(is_active=True).only('id')

        if form.is_valid():
            is_external = form.cleaned_data.get('is_external')
            sessions = form.cleaned_data.get('total_sessions') or 4
            course_info = form.cleaned_data.get('course_info')

            # ربط ثمن الكورس تلقائياً بسعر المادة والمدرس
            if course_info and course_info.price:
                price_per_session = Decimal(str(course_info.price)) / Decimal('4')
                calculated_amount = price_per_session * Decimal(str(sessions))
            else:
                calculated_amount = Decimal('0.00')

            instance = form.save(commit=False)
            instance.required_amount = calculated_amount

            if is_external:
                ext_student = ExternalStudent.objects.create(
                    full_name=form.cleaned_data.get('ext_name'),
                    phone_number=form.cleaned_data.get('ext_phone')
                )
                instance.external_student = ext_student
                instance.student = None

            instance.save()
            return redirect('course_prices')
    else:
        form = CourseGroupForm(initial={'total_sessions': 4})
        form.fields['student'].queryset = Student.objects.none()

    # 🟢 1. بناء الاستعلام الأساسي مع العلاقات
    courses_query = CourseGroup.objects.select_related(
        'student', 'student__grade', 'external_student',
        'course_info__subject', 'course_info__teacher'
    ).prefetch_related(
        'sessions', 'payments'
    ).order_by('-id')

    # 🟢 2. معالجة الفلاتر الزمنية بأداء محسّن
    time_filter = request.GET.get('time_filter', 'all')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    today_date = timezone.now().date()

    if date_from and date_to:
        courses_query = courses_query.filter(registration_date__range=[date_from, date_to])
        time_filter = 'custom'
    elif time_filter == 'today':
        courses_query = courses_query.filter(registration_date__date=today_date)
    elif time_filter == 'week':
        courses_query = courses_query.filter(registration_date__gte=today_date - timedelta(days=7))
    elif time_filter == 'month':
        courses_query = courses_query.filter(registration_date__gte=today_date - timedelta(days=30))
    elif time_filter == 'year':
        courses_query = courses_query.filter(registration_date__gte=today_date - timedelta(days=365))

    # 🟢 3. حساب الإجماليات عبر استعلامات خفيفة محددة (values)
    total_revenue = courses_query.aggregate(total=Sum('required_amount'))['total'] or Decimal('0.00')

    # تحسين استعلام التحصيل ليعمل على المعرفات فقط بدلاً من Subquery كامل
    filtered_course_ids = courses_query.values_list('id', flat=True)
    total_collected = CoursePayment.objects.filter(
        course_enrollment_id__in=filtered_course_ids
    ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    # 🟢 4. تقسيم الصفحات (15 اشتراكاً لكل صفحة)
    paginator = Paginator(courses_query, 15)
    page_number = request.GET.get('page')
    courses_page = paginator.get_page(page_number)

    # 🟢 5. معالجة الحسابات في الذاكرة لـ 15 عنصر فقط (سريعة جداً)
    for c in courses_page.object_list:
        if c.course_info and getattr(c.course_info, 'teacher', None):
            c.teacher_name_display = getattr(c.course_info.teacher, 'name', str(c.course_info.teacher))
        else:
            c.teacher_name_display = "غير محدد"

        ann_attended_count = sum(1 for s in c.sessions.all() if getattr(s, 'attendance_status', '') == 'attended')
        ann_total_paid = sum((p.amount_paid for p in c.payments.all() if p.amount_paid), Decimal('0.00'))

        c.attended_count_display = ann_attended_count
        c.remaining_sessions_display = max(0, c.total_sessions - ann_attended_count)
        c.remaining_amount_display = max(Decimal('0.00'), Decimal(str(c.required_amount or 0)) - Decimal(str(ann_total_paid)))

    # 🟢 6. جلب بيانات الأقسام والموظفين المطلوبة للشاشة
    departments = Department.objects.all()
    # جلب الموظفين التابعين لقسم "مدرس" فقط
    employees = Employee.objects.filter(
        is_active=True,
        department__name__icontains='مدرس'
    )
    existing_external_names = ExternalStudent.objects.values_list('full_name', flat=True).distinct()

    context = {
        'courses': courses_page,
        'form': form,
        'total_revenue': total_revenue,
        'departments': departments,
        'employees': employees,
        'total_collected': total_collected,
        'total_remaining': Decimal(str(total_revenue)) - Decimal(str(total_collected)),
        'current_filter': time_filter,
        'date_from': date_from,
        'date_to': date_to,
        'existing_external_names': existing_external_names,
        'title': 'سجل المجموعات والإيرادات'
    }

    return render(request, 'students/course_prices.html', context)



@login_required
def mark_session_attendance(request, enrollment_id):
    """
    دالة التحضير الفوري الفائقة السرعة:
    - مسجلة بتمكين استيراد StudentSession لمنع أي خطأ نطاق (NameError).
    - تمنع التكرار وتحدث الواجهة دون إعادة تحميل الصفحة.
    """
    if request.method == 'POST':
        enrollment = get_object_or_404(CourseGroup, id=enrollment_id)
        today = timezone.now().date()

        # 1. منع التكرار والتحضير المزدوج لنفس اليوم
        if StudentSession.objects.filter(course_enrollment=enrollment, session_date=today).exists():
            return JsonResponse({
                'status': 'warning',
                'message': '⚠️ الطالب مسجل حضوره اليوم بالفعل مسبقاً!'
            })

        # 2. التحقق من وجود رصيد حصص كافٍ
        if enrollment.remaining_sessions <= 0:
            return JsonResponse({
                'status': 'error',
                'message': '🛑 نفد رصيد الحصص الخاص بهذا الاشتراك! يرجى التجديد أولاً.'
            }, status=400)

        # 3. توثيق الحضور
        StudentSession.objects.create(
            course_enrollment=enrollment,
            session_date=today,
            attendance_status='attended'
        )

        # 4. حساب القيم المحدثة لإرسالها للواجهة فورياً
        attended_cnt = enrollment.attended_sessions_count
        total_sessions = enrollment.total_sessions
        rem_sessions = enrollment.remaining_sessions
        progress_pct = int((attended_cnt / total_sessions) * 100) if total_sessions > 0 else 0

        return JsonResponse({
            'status': 'success',
            'message': '✅ تم تسجيل حضور الحصة بنجاح.',
            'attended_count': attended_cnt,
            'total_sessions': total_sessions,
            'remaining_sessions': rem_sessions,
            'progress_pct': progress_pct
        })

    return JsonResponse({'status': 'error', 'message': 'طلب غير مصرح به.'}, status=400)




@login_required
def session_history_api(request, enrollment_id):
    from .models import CourseGroup
    enrollment = get_object_or_404(CourseGroup, id=enrollment_id)
    sessions = enrollment.sessions.all().order_by('-session_date')

    data = [
        {'date': s.session_date.strftime('%Y-%m-%d')}
        for s in sessions
    ]
    return JsonResponse({'sessions': data})


@login_required
def collect_fee_view(request, enrollment_id):
    from .models import CourseGroup
    enrollment = get_object_or_404(CourseGroup, id=enrollment_id)

    if request.method == 'POST':
        try:
            amount_paid = Decimal(request.POST.get('amount_paid', '0'))
        except (ValueError, TypeError):
            amount_paid = Decimal('0')

        notes = request.POST.get('notes', '')

        if amount_paid > 0:
            from .models import CoursePayment
            course_pay = CoursePayment.objects.create(
                course_enrollment=enrollment,
                amount_paid=amount_paid,
                payment_date=timezone.now(),
                collected_by=request.user,
                notes=notes
            )

            from treasury.models import GeneralLedger

            GeneralLedger.objects.create(
                student=enrollment.student,
                amount=amount_paid,
                category='كورس',
                receipt_number=f"CP-{course_pay.id}-{uuid.uuid4().hex[:4].upper()}",
                notes=f"تحصيل كورس: {enrollment.course_info.subject.name} - {notes}",
                date=timezone.now(),
                collected_by=request.user
            )

            return redirect('course_prices')

    return render(request, 'students/collect_fee.html', {'enrollment': enrollment})

@login_required
@require_POST
def save_admin_decision(request):
    """الربط الذكي: تنفيذ القرارات الإدارية السيادية لشئون الطلاب وتسميعها في الكنترول"""
    student_id = request.POST.get('student_id')
    decision_type = request.POST.get('decision_type')
    reason = request.POST.get('decision_reason')

    try:
        student = get_object_or_404(Student, id=student_id)
        active_year = get_active_year()

        with transaction.atomic():
            # 1. تحديث الملاحظات الإدارية للطالب
            student.enrollment_notes = f"[{timezone.now().date()}] قرار إداري: {reason}"

            # 🟢 الحل هنا: تهيئة المتغير لمنع خطأ المتصفح الصامت (UnboundLocalError)
            msg = ""

            # 🟢 --- 1. الحالة الجديدة: تفعيل الطالب وإعادة قيده ---
            if decision_type == 're_enroll':
                student.enrollment_status = 'Re_enrolled' # 🟢 تغيير الحالة لـ "تم إعادة قيده"
                student.is_active = True

                from students.models import ReEnrollmentRecord
                # تحديث سجل الفصل وتحويله لمعاد قيده
                latest_dismissal = ReEnrollmentRecord.objects.filter(
                    student=student, academic_year=active_year, status='dismissed'
                ).last()

                if latest_dismissal:
                    latest_dismissal.status = 're_enrolled'
                    latest_dismissal.reenrollment_date = timezone.now().date()
                    latest_dismissal.save()
                else:
                    ReEnrollmentRecord.objects.create(
                        student=student, academic_year=active_year,
                        status='re_enrolled', reenrollment_date=timezone.now().date()
                    )
                msg = f"✅ تم تفعيل الطالب ({student.get_full_name()}) وتحويل حالته إلى 'تم إعادة قيده' بنجاح."

            # --- 2. حالة (لم يتقدم للامتحانات) ---
            elif decision_type == 'did_not_attend':
                student.enrollment_status = 'Retained' # باقٍ للإعادة

                # تصفير الكنترول أوتوماتيكياً في كل المواد!
                from .models import SubjectConfig, ExamResult, StudentControlSheet
                subjects_configs = SubjectConfig.objects.filter(grade=student.grade, academic_year=active_year)

                for config in subjects_configs:
                    for term in ['term1', 'term2']:
                        ExamResult.objects.update_or_create(
                            student=student, subject=config.subject, academic_year=active_year, exam_type='term', term=term,
                            defaults={'is_absent': True, 'cultural_score': 0, 'practical_score': 0}
                        )
                    StudentControlSheet.objects.update_or_create(
                        student=student, subject=config.subject, academic_year=active_year,
                        defaults={'term1_is_absent': True, 'term2_is_absent': True, 'status': 'failed'}
                    )

                msg = f"✅ تم تسجيل ({student.get_full_name()}) كـ 'لم يتقدم'، وتم إغلاق شيت الكنترول وتصفير كافة مواده."

            # --- 3. حالة (الفصل الإداري النهائي) ---
            elif decision_type == 'admin_dismissal':
                student.enrollment_status = 'Dismissed' # مفصول
                from students.models import ReEnrollmentRecord
                ReEnrollmentRecord.objects.create(student=student, academic_year=active_year, status='dismissed')
                msg = f"✅ تم تنفيذ الفصل الإداري للطالب ({student.get_full_name()}) بنجاح."

            else:
                msg = "تم تحديث ملاحظات السجل الإداري بنجاح."

            student.save()

        return JsonResponse({'success': True, 'message': msg})

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)})



@login_required
def student_registry_view(request):
    # ========================================================
    # 🟢 1. استقبال طلب الـ AJAX الخاص بالـ Timeline (الخط الزمني)
    # ========================================================
    if request.GET.get('action') == 'get_timeline':
        student_id = request.GET.get('student_id')
        student = get_object_or_404(Student, id=student_id)
        events = []

        # أ. حدث فتح الملف
        events.append({
            'date': student.created_at.strftime('%Y-%m-%d') if student.created_at else '---',
            'type': 'success',
            'icon': 'bi-person-add',
            'title': 'فتح الملف (القيد المبدئي)',
            'desc': f'تم تسجيل الطالب بالمنظومة والحالة المبدئية: {student.get_initial_status_display()}'
        })

        if student.enrollment_notes:
            events.append({
                'date': 'سجل إداري',
                'type': 'secondary',
                'icon': 'bi-briefcase-fill',
                'title': 'قرار / ملاحظة من شئون الطلاب',
                'desc': student.enrollment_notes
            })

        # ب. سجلات الفصل وإعادة القيد
        reenrolls = ReEnrollmentRecord.objects.filter(student=student).order_by('dismissal_date')
        for r in reenrolls:
            events.append({
                'date': r.dismissal_date.strftime('%Y-%m-%d') if r.dismissal_date else 'غير محدد',
                'type': 'danger',
                'icon': 'bi-person-dash-fill',
                'title': 'قرار فصل أكاديمي',
                'desc': 'تم فصل الطالب إدارياً لتخطي نسبة الغياب المقررة.'
            })
            if r.status == 're_enrolled' and r.reenrollment_date:
                events.append({
                    'date': r.reenrollment_date.strftime('%Y-%m-%d'),
                    'type': 'primary',
                    'icon': 'bi-arrow-repeat',
                    'title': 'إعادة قيد للط الطالب',
                    'desc': 'تم استكمال إجراءات إعادة القيد وعودة الطالب للدراسة.'
                })

        # ج. سجلات الغياب عن الامتحانات
        absent_exams = ExamResult.objects.filter(student=student, is_absent=True).select_related('subject')
        for exam in absent_exams:
            exam_date = exam.created_at.strftime('%Y-%m-%d') if hasattr(exam, 'created_at') and exam.created_at else '---'
            events.append({
                'date': exam_date,
                'type': 'warning',
                'icon': 'bi-exclamation-triangle-fill',
                'title': 'غياب عن امتحان رسمي',
                'desc': f'تخلف الطالب عن أداء امتحان مادة ( {exam.subject.name} ) - {exam.get_term_display()}'
            })

        return JsonResponse({'success': True, 'student_name': student.get_full_name(), 'events': events})

    # ========================================================
    # 🟢 2. المعالجة الأساسية للوحة السجل المدني والفلترة
    # ========================================================
    year_id = request.GET.get('year_id')
    if year_id:
        target_year = get_object_or_404(AcademicYear, id=year_id)
        base_query = Student.objects.filter(academic_year=target_year)
    else:
        active_year = AcademicYear.objects.filter(is_active=True).first()
        target_year = active_year
        # 🟢 التعديل: إظهار الطلاب النشطين أو من عليهم مديونية سابقة
        base_query = Student.objects.filter(
            Q(is_active=True) | Q(previous_debt__gt=0),
            academic_year=active_year
        )

    query = request.GET.get('q', '').strip()
    grade_id = request.GET.get('grade_id', '')
    classroom_id = request.GET.get('classroom_id', '')
    spec = request.GET.get('specialization', '')
    gender = request.GET.get('gender', '')
    religion = request.GET.get('religion', '')
    is_disability = request.GET.get('is_disability', '')
    quick_filter = request.GET.get('quick_filter', '')

    # 🚀 التحديث الجوهري 1: خوارزمية البحث الذكية والمفهرسة (تلغي بطء الـ Annotate وتحل مشكلة منة/منه)
    if query:
        words = query.split()
        for word in words:
            norm_word = word.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')
            base_query = base_query.filter(
                Q(search_name__icontains=norm_word) |
                Q(student_code__icontains=word) |
                Q(national_id__icontains=word)
            )

    # تطبيق باقي الفلاتر
    if grade_id: base_query = base_query.filter(grade_id=grade_id)
    if classroom_id: base_query = base_query.filter(classroom_id=classroom_id)
    if spec: base_query = base_query.filter(specialization=spec)
    if gender: base_query = base_query.filter(gender=gender)
    if religion: base_query = base_query.filter(religion=religion)
    if is_disability:
        base_query = base_query.filter(integration_status=(is_disability == 'true'))

    # ========================================================
    # 🟢 3. العمود الذكي: الاستعلامات الفرعية العميقة وتطبيق الفلاتر السريعة المحدثة (تعتمد على enrollment_status لدقة 100%)
    # ========================================================
    latest_reenrollment = ReEnrollmentRecord.objects.filter(
        student=OuterRef('pk'), academic_year=target_year
    ).order_by('-id')

    base_query = base_query.annotate(
        last_dismissal_date=Subquery(latest_reenrollment.values('dismissal_date')[:1]),
        last_reenrollment_date=Subquery(latest_reenrollment.values('reenrollment_date')[:1]),
        reenroll_status_db=Subquery(latest_reenrollment.values('status')[:1]),
        missed_exams_count=Count('exam_results', filter=Q(exam_results__is_absent=True, exam_results__academic_year=target_year), distinct=True)
    )

    if quick_filter == 'dismissed':
        base_query = base_query.filter(enrollment_status='Dismissed')
    elif quick_filter == 'reenrolled':
        base_query = base_query.filter(enrollment_status='Re_enrolled')
    elif quick_filter == 'retained':
        base_query = base_query.filter(enrollment_status='Retained')
    elif quick_filter == 'promoted':
        base_query = base_query.filter(enrollment_status='Promoted')
    elif quick_filter == 'did_not_attend':
        base_query = base_query.filter(enrollment_status='Did_Not_Attend')
    elif quick_filter == 'missed_exams':
        base_query = base_query.filter(missed_exams_count__gt=0)

    # ========================================================
    # 🚀 التحديث الجوهري 2: حساب الإحصائيات باستعلام واحد فقط (Aggregation)
    # ========================================================
    # بدلاً من تنفيذ 6 استعلامات .count() تبطئ السيرفر، نقوم بجمعها في استعلام قاعدة بيانات واحد
    agg_stats = base_query.aggregate(
        total_count=Count('id'),
        male_count=Count('id', filter=Q(gender='Male')),
        female_count=Count('id', filter=Q(gender='Female')),
        muslim_count=Count('id', filter=Q(religion='Muslim')),
        christian_count=Count('id', filter=Q(religion='Christian')),
        integration_count=Count('id', filter=Q(integration_status=True))
    )

    # حساب العدادات الخاصة بالفلاتر السريعة (على مستوى السنة كلها لتظل ظاهرة للرقم الكلي)
    # 🟢 التعديل: تجميع الطلاب النشطين + أصحاب المديونيات لتبقى العدادات مطابقة
    all_active_students = Student.objects.filter(
        Q(is_active=True) | Q(previous_debt__gt=0),
        academic_year=target_year
    )

    stats = {
        'total': agg_stats['total_count'],
        'male': agg_stats['male_count'],
        'female': agg_stats['female_count'],
        'muslim': agg_stats['muslim_count'],
        'christian': agg_stats['christian_count'],
        'integration': agg_stats['integration_count'],

        # 🟢 عدادات الفلاتر السريعة المحدثة:
        'dismissed_count': all_active_students.filter(enrollment_status='Dismissed').count(),
        'reenrolled_count': all_active_students.filter(enrollment_status='Re_enrolled').count(),
        'retained_count': all_active_students.filter(enrollment_status='Retained').count(),
        'promoted_count': all_active_students.filter(enrollment_status='Promoted').count(),
        'did_not_attend_count': all_active_students.filter(enrollment_status='Did_Not_Attend').count(),
        'missed_exams_count': all_active_students.filter(exam_results__is_absent=True, exam_results__academic_year=target_year).distinct().count()
    }

    # ========================================================
    # 🟢 4. الترتيب والتقسيم (Pagination)
    # ========================================================
    student_list = base_query.order_by('first_name', 'id')
    paginator = Paginator(student_list, 20)
    page_number = request.GET.get('page')
    students_page = paginator.get_page(page_number)

    context = {
        'students': students_page,
        'stats': stats,
        'all_grades': Grade.objects.all(),
        'all_classrooms': Classroom.objects.all(),
        'all_specs': Student.SPECIALIZATION_CHOICES if hasattr(Student, 'SPECIALIZATION_CHOICES') else [],

        'selected_grade': grade_id,
        'selected_classroom': classroom_id,
        'selected_specialization': spec,
        'selected_gender': gender,
        'selected_religion': religion,
        'selected_is_disability': is_disability,
        'search_query': query,
        'quick_filter': quick_filter,

        'current_year': target_year if year_id else active_year,
        'is_archive': bool(year_id),
    }

    return render(request, 'student_registry.html', context)


def get_pending_sales_api(request, student_id):
    sales = BookSale.objects.filter(student_id=student_id).exclude(status='paid')

    sales_data = []
    for s in sales:
        if s.remaining_amount > 0:
            sales_data.append({
                'id': s.id,
                'item_name': s.item.display_name,
                'remaining': float(s.remaining_amount)
            })

    return JsonResponse({'sales': sales_data})



# استدعاء نماذج المخازن المركزية فقط (الخيار الأول)
from core_inventory.models import ItemMaster, Warehouse, StockTransaction, StockBalance


@login_required
def admin_add_restock(request):
    """
    شاشة التوريد المركزية (ERP) بالتصميم الاحترافي الذكي
    """
    active_year = get_active_year()

    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        warehouse_id = request.POST.get('warehouse_id')
        quantity_str = request.POST.get('quantity', '0')
        note = request.POST.get('note', '').strip()

        try:
            with transaction.atomic():
                qty = Decimal(quantity_str)
                if qty <= 0:
                    messages.error(request, "🛑 يرجى إدخال كمية توريد أكبر من الصفر!")
                    return redirect('admin_add_restock')

                item = get_object_or_404(ItemMaster, id=item_id)
                warehouse = get_object_or_404(Warehouse, id=warehouse_id)

                # 1. تسجيل حركة التوريد
                StockTransaction.objects.create(
                    item=item,
                    warehouse=warehouse,
                    movement_type='IN_PURCHASE',  # حركة توريد جديدة
                    quantity=qty,
                    notes=note,
                    created_by=request.user
                )

                # 2. تحديث الرصيد الفعلي (التصحيح هنا)
                balance, created = StockBalance.objects.get_or_create(
                    item=item,
                    warehouse=warehouse,
                    defaults={'quantity_on_hand': 0}
                )
                balance.quantity_on_hand += qty
                balance.save()

                messages.success(request, f"✅ تم توريد ({qty}) قطعة بنجاح للصنف [{item.name}].")

        except Exception as e:
            messages.error(request, f"❌ فشلت عملية التوريد! السبب: {str(e)}")

        return redirect('admin_add_restock')

    # === GET Request ===
    warehouses = Warehouse.objects.filter(is_active=True)

    # 🚀 السطر المفقود: جلب الصفوف الدراسية
    grades = Grade.objects.all().order_by('id')

    # جلب جميع الأصناف كـ JSON للفلترة اللحظية (تأكد من وجود حقل item_type في ItemMaster)
    raw_items = list(ItemMaster.objects.values('id', 'name', 'sku', 'item_type').order_by('name'))
    items_json = json.dumps(raw_items)

    # جلب أحدث 20 حركة توريد للمستودعات
    recent_restocks = StockTransaction.objects.filter(
        movement_type__in=['IN_OPENING', 'IN_PURCHASE']
    ).select_related('item', 'warehouse').order_by('-date')[:20]

    context = {
        'warehouses': warehouses,
        'grades': grades,  # 🚀 السطر المفقود: إرسال الصفوف لملف الـ HTML
        'items_json': items_json,
        'recent_restocks': recent_restocks,
        'active_year': active_year,
    }
    return render(request, 'students/admin_restock.html', context)

def get_item_history(request, item_id):
    try:
        item = InventoryItem.objects.get(id=item_id)
        history_list = []

        restocks = InventoryRestock.objects.filter(item_id=item_id).order_by('-restock_date')

        for stock in restocks:
            history_list.append({
                'date': stock.restock_date.strftime('%Y-%m-%d') if stock.restock_date else "---",
                'type': 'وارد (توريد)',
                'color': 'success',
                'qty': stock.quantity,
                'note': stock.note or "إضافة كمية للمخزن"
            })

        if not restocks.exists():
            history_list.append({
                'date': "---",
                'type': 'وارد (رصيد أول)',
                'color': 'success',
                'qty': item.stock_quantity,
                'note': "الكمية الأساسية عند تعريف الصنف"
            })

        sales = BookSale.objects.filter(item_id=item_id).order_by('-sale_date')

        for sale in sales:
            student_name = f"{sale.student.first_name} {sale.student.last_name}" if sale.student else "---"

            history_list.append({
                'date': sale.sale_date.strftime('%Y-%m-%d') if sale.sale_date else "---",
                'type': 'منصرف',
                'color': 'danger',
                'qty': sale.quantity,
                'note': f"طالب: {student_name}"
            })

        return JsonResponse({'history': history_list})

    except InventoryItem.DoesNotExist:
        return JsonResponse({'history': [], 'error': 'Item not found'})


@login_required
def inventory_category_report(request):
    """
    منظومة الجرد الفعلي الموحد للمخزن:
    1. تفصل بين الكتب الدراسية والزي المدرسي بتبويبات مستقلة.
    2. تصفى الأصناف الصورية لمنع التدبيل وتجمع الأصناف الحقيقية حسب الصفوف.
    3. تعرض أول المدة، الشراء والتوريد الإضافي، إجمالي الوارد، المنصرف، والرصيد المتبقي.
    """
    # معالجة الخطأ المحتمل إذا لم تكن الدالة موجودة
    active_year = get_active_year() if 'get_active_year' in globals() else "2025/2026"

    # 🟢 1. التصحيح الجذري: إزالة .values() لجلب "كائنات" حقيقية (Objects)
    raw_items = ItemMaster.objects.all().order_by('name')

    physical_items = []
    for item in raw_items:
        # 🟢 2. استخدام hasattr و getattr لحماية السيرفر من التعطل إذا اختلف اسم الحقل
        has_subject = getattr(item, 'subject_id', None)
        has_uniform = getattr(item, 'uniform_id', None)

        # التأكد من وجود العلاقات بأمان قبل استخدام .exists()
        has_restocks = hasattr(item, 'restocks') and item.restocks.exists()
        has_sales = hasattr(item, 'booksale_set') and item.booksale_set.exists()

        if has_subject or has_uniform or has_restocks or has_sales or getattr(item, 'item_type', None) in ['book', 'uniform']:
            physical_items.append(item)

    books_by_grade = {}
    uniform_by_grade = {}

    total_books_incoming = 0
    total_books_sold = 0
    total_books_remaining = 0

    total_uniform_incoming = 0
    total_uniform_sold = 0
    total_uniform_remaining = 0

    for item in physical_items:
        # جلب البيانات بأمان تام (Fallback values) لتجنب أي أخطاء في العرض
        grade = getattr(item, 'grade', None)
        grade_name = getattr(grade, 'name', "عام / بدون صف") if grade else "عام / بدون صف"

        opening_stock = getattr(item, 'stock_quantity', 0)

        # جلب الكميات الموردة
        restocks_qty = sum(r.quantity for r in item.restocks.all()) if hasattr(item, 'restocks') else 0

        total_incoming = getattr(item, 'total_incoming', opening_stock + restocks_qty)
        total_sold = getattr(item, 'total_sold_count', 0)
        remaining = getattr(item, 'remaining_qty', total_incoming - total_sold)

        display_name = getattr(item, 'display_name', getattr(item, 'name', 'صنف غير محدد'))
        item_type = getattr(item, 'item_type', 'book')

        item_data = {
            'id': item.id,
            'name': display_name,
            'grade_name': grade_name,
            'opening_stock': opening_stock,
            'restocks_qty': restocks_qty,
            'total_incoming': total_incoming,
            'total_sold': total_sold,
            'remaining': remaining,
            'item_type': item_type,
        }

        if item_type == 'book':
            if grade_name not in books_by_grade:
                books_by_grade[grade_name] = []
            books_by_grade[grade_name].append(item_data)

            total_books_incoming += total_incoming
            total_books_sold += total_sold
            total_books_remaining += remaining

        elif item_type == 'uniform':
            if grade_name not in uniform_by_grade:
                uniform_by_grade[grade_name] = []
            uniform_by_grade[grade_name].append(item_data)

            total_uniform_incoming += total_incoming
            total_uniform_sold += total_sold
            total_uniform_remaining += remaining

    context = {
        'books_by_grade': books_by_grade,
        'uniform_by_grade': uniform_by_grade,
        'stats': {
            'total_items': len(physical_items),
            'books_incoming': total_books_incoming,
            'books_sold': total_books_sold,
            'books_remaining': total_books_remaining,
            'uniform_incoming': total_uniform_incoming,
            'uniform_sold': total_uniform_sold,
            'uniform_remaining': total_uniform_remaining,
            'grand_remaining': total_books_remaining + total_uniform_remaining,
        },
        'active_year': active_year,
        'title': 'تقرير الجرد والرقابة المخزنية الموحدة'
    }

    return render(request, 'students/books/inventory_report.html', context)



@login_required
@require_POST
def ajax_toggle_delivery(request, sale_id):
    """دالة آياكس لتأكيد استلام الصنف بضغطة زر دون إعادة تحميل الصفحة"""
    try:
        sale = get_object_or_404(BookSale, id=sale_id)
        sale.mark_as_delivered(request.user)
        return JsonResponse({
            'success': True,
            'message': f'✅ تم تأكيد تسليم ({sale.item.display_name}) للطالب ({sale.student.get_full_name()}) بنجاح.'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)



@login_required
def confirm_delivery_view(request, sale_id):
    """دالة تأكيد تسليم الصنف بواسطة أمين المخزن - قفل نهائي"""
    if request.method == 'POST':
        sale = get_object_or_404(BookSale, id=sale_id)

        if sale.is_delivered:
            return JsonResponse({
                'success': False,
                'error': 'تم تسليم هذا الإذن بالفعل سابقاً، ولا يمكن التراجع عن التسليم إلا من خلال لوحة الأدمن.'
            })

        sale.mark_as_delivered(request.user)

        return JsonResponse({
            'success': True,
            'message': 'تم توثيق تسليم الصنف بنجاح بواسطة أمين المخزن.',
            'delivered_by': sale.delivered_by.get_full_name() or sale.delivered_by.username,
            'delivered_at': sale.delivered_at.strftime("%Y-%m-%d %I:%M %p")
        })

    return JsonResponse({'success': False, 'error': 'طلب غير مصرح به.'}, status=400)


@login_required
def toggle_delivery_view(request, sale_id):
    """دالة تأكيد تسليم الصنف فوراً من قبل أمين المخزن عبر AJAX مع حماية تسجيل الدخول"""
    if request.method == 'POST':
        sale = get_object_or_404(BookSale, id=sale_id)

        sale.is_delivered = True
        sale.delivered_at = timezone.now()
        sale.delivered_by = request.user
        sale.save()

        delivered_by_name = sale.delivered_by.get_full_name() or sale.delivered_by.username

        return JsonResponse({
            'success': True,
            'message': 'تم توثيق تسليم الصنف بنجاح',
            'delivered_by': delivered_by_name,
            'delivered_at': sale.delivered_at.strftime("%Y-%m-%d %I:%M %p")
        })

    return JsonResponse({'success': False, 'error': 'طلب غير مصرح به'}, status=400)



def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'




@login_required
def add_book_sale(request):
    """شاشة تسجيل إذن صرف جديد - قفل سيرفر حديدي يمنع حفظ أي مبلغ زائد أو يتجاوز الباقة"""
    active_year = get_active_year()
    next_url = request.GET.get('next') or request.POST.get('next')

    # 🟢 استقبال رقم طالب مُمرَّر من صفحة تانية (زي شاشة الكاونتر) عشان يتحدد
    # تلقائياً في شاشة البحث هنا من غير ما يدوّر عليه المستخدم تاني
    preselected_student = None
    preselected_student_id = request.GET.get('student_id')
    if preselected_student_id and request.method != 'POST':
        _pre_student = Student.objects.filter(id=preselected_student_id).select_related('grade').first()
        if _pre_student:
            preselected_student = {
                'id': _pre_student.id,
                'name': _pre_student.get_full_name(),
                'grade': _pre_student.grade.name if _pre_student.grade else '---',
                'code': _pre_student.student_code,
            }

    if request.method == 'POST':
        is_ajax = _is_ajax(request)

        student_id = request.POST.get('student')
        item_type = request.POST.get('item_type')
        quantity = int(request.POST.get('quantity', 1))
        try:
            pay_now = Decimal(str(request.POST.get('pay_now', '0.00') or '0.00'))
        except Exception:
            pay_now = Decimal('0.00')

        is_delivered = request.POST.get('is_delivered') == 'on' or request.POST.get('is_delivered') == 'true'

        if not student_id or not item_type:
            err_msg = "🛑 يرجى تحديد الطالب ونوع الصنف."
            if is_ajax:
                return JsonResponse({'success': False, 'error': err_msg}, status=400)
            messages.error(request, err_msg)
            return redirect('add_book_sale')

        student = get_object_or_404(Student, id=student_id)
        item_label = "الكتب الدراسية" if item_type == 'book' else "الزي المدرسي"

        # 1. جلب سعر الباقة المقرر للصف من إعدادات النظام
        package = (
            GradePackagePrice.objects.filter(grade=student.grade, academic_year=student.academic_year).first()
            or GradePackagePrice.objects.filter(grade=student.grade, academic_year=active_year).first()
            or GradePackagePrice.objects.filter(grade=student.grade).first()
        )

        package_price = Decimal('0.00')
        if package:
            package_price = package.books_price if item_type == 'book' else package.uniform_price

        # حماية 1: إذا لم يتم تحديد سعر للباقة في إعدادات النظام
        if not package or package_price <= Decimal('0.00'):
            grade_name = student.grade.name if student.grade else 'هذا الصف'
            err_msg = f"🛑 حظر: لم يتم تحديد سعر باقة {item_label} لـ ({grade_name}) في إعدادات النظام! يرجى تحديد أسعار الباقات أولاً."
            if is_ajax:
                return JsonResponse({'success': False, 'error': err_msg}, status=400)
            messages.error(request, err_msg)
            return redirect('add_book_sale')

        # 2. حساب المبالغ المدفوعة سابقاً لنفس الصنف
        previous_sales = BookSale.objects.filter(student=student, item__item_type=item_type)
        already_paid = sum(s.calculated_paid_amount for s in previous_sales)

        # حساب الحد الأقصى المسموح تحصيله الآن
        max_allowed_now = max(Decimal('0.00'), package_price - already_paid)

        # 🛑 حماية حاسمة على السيرفر: رفض تام للحفظ إذا كان المبلغ المدخل أكبر من المتبقي المسموح
        if pay_now > max_allowed_now:
            if already_paid >= package_price:
                err_msg = f"🛑 تجاوز الحد المسموح: الطالب ({student.get_full_name()}) مسدد بالكامل سابقاً لباقة {item_label} ({package_price} ج.م). لا يمكن تحصيل أي مبالغ إضافية!"
            else:
                err_msg = f"🛑 تجاوز الحد المسموح: المبلغ المدخل ({pay_now} ج.م) أكبر من المتبقي للباقة ({max_allowed_now} ج.م). إجمالي الباقة: {package_price} ج.م | المدفوع سابقاً: {already_paid} ج.م."

            if is_ajax:
                return JsonResponse({'success': False, 'error': err_msg}, status=400)
            messages.error(request, err_msg)
            return redirect('add_book_sale')

        item = InventoryItem.objects.filter(grade=student.grade, item_type=item_type).first()
        if not item:
            item = InventoryItem.objects.create(
                item_type=item_type,
                grade=student.grade,
                stock_quantity=100
            )

        sale = BookSale(
            student=student,
            item=item,
            quantity=quantity,
            total_amount=package_price,
            pay_now=pay_now,
            is_delivered=is_delivered
        )
        sale._current_user = request.user

        if is_delivered:
            sale.delivered_by = request.user
            sale.delivered_at = timezone.now()

        sale.save()

        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': f'✅ تم تسجيل إذن الصرف برقم (# {sale.id}) بنجاح.',
                'sale': {
                    'id': sale.id,
                    'time': timezone.localtime(sale.sale_date).strftime('%I:%M %p'),
                    'student_name': student.get_full_name(),
                    'grade_name': student.grade.name if student.grade else '---',
                    'item_label': item_label,
                    'quantity': sale.quantity,
                    'pay_now': str(sale.pay_now),
                    'is_delivered': sale.is_delivered,
                    'employee': request.user.get_full_name() or request.user.username,
                },
                'print_url': reverse('print_book_receipt', args=[sale.id]),
            })

        messages.success(request, f"✅ تم تسجيل إذن الصرف برقم (# {sale.id}) بنجاح.")

        if request.POST.get('print_after_save') == 'true':
            return redirect('print_book_receipt', sale_id=sale.id)
        elif next_url:
            return redirect(next_url)
        return redirect('book_sales_list')

    context = {
        'next_url': next_url,
        'active_year': active_year,
        'title': 'نقطة تسجيل إذن صرف جديد',
        'preselected_student': preselected_student,
    }
    return render(request, 'books/add_sale.html', context)


# @login_required
# def add_book_sale(request):
#     """شاشة تسجيل إذن صرف جديد - قفل سيرفر حديدي يمنع حفظ أي مبلغ زائد أو يتجاوز الباقة"""
#     active_year = get_active_year()
#     next_url = request.GET.get('next') or request.POST.get('next')

#     if request.method == 'POST':
#         is_ajax = _is_ajax(request)

#         student_id = request.POST.get('student')
#         item_type = request.POST.get('item_type')
#         quantity = int(request.POST.get('quantity', 1))
#         try:
#             pay_now = Decimal(str(request.POST.get('pay_now', '0.00') or '0.00'))
#         except Exception:
#             pay_now = Decimal('0.00')

#         is_delivered = request.POST.get('is_delivered') == 'on' or request.POST.get('is_delivered') == 'true'

#         if not student_id or not item_type:
#             err_msg = "🛑 يرجى تحديد الطالب ونوع الصنف."
#             if is_ajax:
#                 return JsonResponse({'success': False, 'error': err_msg}, status=400)
#             messages.error(request, err_msg)
#             return redirect('add_book_sale')

#         student = get_object_or_404(Student, id=student_id)
#         item_label = "الكتب الدراسية" if item_type == 'book' else "الزي المدرسي"

#         # 1. جلب سعر الباقة المقرر للصف من إعدادات النظام
#         package = (
#             GradePackagePrice.objects.filter(grade=student.grade, academic_year=student.academic_year).first()
#             or GradePackagePrice.objects.filter(grade=student.grade, academic_year=active_year).first()
#             or GradePackagePrice.objects.filter(grade=student.grade).first()
#         )

#         package_price = Decimal('0.00')
#         if package:
#             package_price = package.books_price if item_type == 'book' else package.uniform_price

#         # حماية 1: إذا لم يتم تحديد سعر للباقة في إعدادات النظام
#         if not package or package_price <= Decimal('0.00'):
#             grade_name = student.grade.name if student.grade else 'هذا الصف'
#             err_msg = f"🛑 حظر: لم يتم تحديد سعر باقة {item_label} لـ ({grade_name}) في إعدادات النظام! يرجى تحديد أسعار الباقات أولاً."
#             if is_ajax:
#                 return JsonResponse({'success': False, 'error': err_msg}, status=400)
#             messages.error(request, err_msg)
#             return redirect('add_book_sale')

#         # 2. حساب المبالغ المدفوعة سابقاً لنفس الصنف
#         previous_sales = BookSale.objects.filter(student=student, item__item_type=item_type)
#         already_paid = sum(s.calculated_paid_amount for s in previous_sales)

#         # حساب الحد الأقصى المسموح تحصيله الآن
#         max_allowed_now = max(Decimal('0.00'), package_price - already_paid)

#         # 🛑 حماية حاسمة على السيرفر: رفض تام للحفظ إذا كان المبلغ المدخل أكبر من المتبقي المسموح
#         if pay_now > max_allowed_now:
#             if already_paid >= package_price:
#                 err_msg = f"🛑 تجاوز الحد المسموح: الطالب ({student.get_full_name()}) مسدد بالكامل سابقاً لباقة {item_label} ({package_price} ج.م). لا يمكن تحصيل أي مبالغ إضافية!"
#             else:
#                 err_msg = f"🛑 تجاوز الحد المسموح: المبلغ المدخل ({pay_now} ج.م) أكبر من المتبقي للباقة ({max_allowed_now} ج.م). إجمالي الباقة: {package_price} ج.م | المدفوع سابقاً: {already_paid} ج.م."

#             if is_ajax:
#                 return JsonResponse({'success': False, 'error': err_msg}, status=400)
#             messages.error(request, err_msg)
#             return redirect('add_book_sale')

#         item = InventoryItem.objects.filter(grade=student.grade, item_type=item_type).first()
#         if not item:
#             item = InventoryItem.objects.create(
#                 item_type=item_type,
#                 grade=student.grade,
#                 stock_quantity=100
#             )

#         sale = BookSale(
#             student=student,
#             item=item,
#             quantity=quantity,
#             total_amount=package_price,
#             pay_now=pay_now,
#             is_delivered=is_delivered
#         )
#         sale._current_user = request.user

#         if is_delivered:
#             sale.delivered_by = request.user
#             sale.delivered_at = timezone.now()

#         sale.save()

#         if is_ajax:
#             return JsonResponse({
#                 'success': True,
#                 'message': f'✅ تم تسجيل إذن الصرف برقم (# {sale.id}) بنجاح.',
#                 'sale': {
#                     'id': sale.id,
#                     'time': timezone.localtime(sale.sale_date).strftime('%I:%M %p'),
#                     'student_name': student.get_full_name(),
#                     'grade_name': student.grade.name if student.grade else '---',
#                     'item_label': item_label,
#                     'quantity': sale.quantity,
#                     'pay_now': str(sale.pay_now),
#                     'is_delivered': sale.is_delivered,
#                     'employee': request.user.get_full_name() or request.user.username,
#                 },
#                 'print_url': reverse('print_book_receipt', args=[sale.id]),
#             })

#         messages.success(request, f"✅ تم تسجيل إذن الصرف برقم (# {sale.id}) بنجاح.")

#         if request.POST.get('print_after_save') == 'true':
#             return redirect('print_book_receipt', sale_id=sale.id)
#         elif next_url:
#             return redirect(next_url)
#         return redirect('book_sales_list')

#     context = {
#         'next_url': next_url,
#         'active_year': active_year,
#         'title': 'نقطة تسجيل إذن صرف جديد'
#     }
#     return render(request, 'books/add_sale.html', context)


@login_required
def api_today_book_sales(request):
    """
    📋 جلب كل عمليات الصرف اللي تمت اليوم فقط (لعرضها في جدول شاشة الإصدار السريع
    من غير أي إعادة تحميل للصفحة)
    """
    today = timezone.localdate()
    sales_qs = BookSale.objects.filter(sale_date__date=today).select_related(
        'student', 'student__grade', 'item', 'delivered_by'
    ).order_by('-sale_date')[:50]

    sales_data = []
    for s in sales_qs:
        item_label = "الكتب الدراسية" if s.item and s.item.item_type == 'book' else "الزي المدرسي"
        sales_data.append({
            'id': s.id,
            'time': timezone.localtime(s.sale_date).strftime('%I:%M %p'),
            'student_name': s.student.get_full_name() if s.student else '---',
            'grade_name': s.student.grade.name if s.student and s.student.grade else '---',
            'item_label': item_label,
            'quantity': s.quantity,
            'pay_now': str(s.pay_now),
            'is_delivered': s.is_delivered,
            'print_url': reverse('print_book_receipt', args=[s.id]),
        })

    return JsonResponse({'success': True, 'sales': sales_data, 'count': len(sales_data)})


@login_required
def print_receipt_view(request, sale_id):
    """إذن استلام عهدة مخزنية رسمي قابل للطباعة الفورية دون حظر مالي"""
    sale = get_object_or_404(BookSale, id=sale_id)
    student = sale.student
    item_type = sale.item.item_type

    # جلب جميع أصناف ومواد الصف لتوضيحها في كشف الاستلام
    grade_items = InventoryItem.objects.filter(
        grade=student.grade,
        item_type=item_type
    ).select_related('subject', 'uniform')

    context = {
        'sale': sale,
        'grade_items': grade_items,
        'item_type_label': "الكتب الدراسية" if item_type == 'book' else "الزي المدرسي",
        'title': f'إذن استلام عهدة - {student.get_full_name()}'
    }
    return render(request, 'books/print_receipt.html', context)



def collect_course_fee_view(request, enrollment_id):
    enrollment = get_object_or_404(CourseGroup, id=enrollment_id)

    if request.method == 'POST':
        amount = request.POST.get('amount_paid')
        notes = request.POST.get('notes')

        if amount and float(amount) > 0:
            CoursePayment.objects.create(
                course_enrollment=enrollment,
                amount_paid=amount,
                collected_by=request.user,
                notes=notes
            )
            messages.success(request, f"تم تحصيل {amount} ج.م بنجاح من الطالب {enrollment.student}")
            return redirect('course_prices')
        else:
            messages.error(request, "يرجى إدخال مبلغ صحيح")

    context = {
        'enrollment': enrollment,
        'title': 'تحصيل رسوم كورس'
    }
    return render(request, 'students/collect_fee.html', context)


def debt_history(request, student_id):
    student = get_object_or_404(Student, id=student_id)

    accounts = StudentAccount.objects.filter(student=student).order_by('-created_at')
    payments = Payment.objects.filter(student=student).order_by('-payment_date')

    context = {
        "student": student,
        "accounts": accounts,
        "payments": payments,
    }
    return render(request, "debt_history.html", context)


def get_classrooms(request):
    grade_id = request.GET.get('grade_id')
    classrooms = Classroom.objects.filter(grade_id=grade_id).values('id', 'name')
    return JsonResponse(list(classrooms), safe=False)


@login_required
def student_dashboard(request, student_id=None):
    if student_id:
        student = get_object_or_404(Student, id=student_id)
        current_year = student.academic_year

        installments = StudentInstallment.objects.filter(
            student=student,
            academic_year=current_year
        ).order_by('due_date')

        total_required = installments.aggregate(s=Sum('amount_due'))['s'] or Decimal('0.00')
        total_paid = installments.aggregate(s=Sum('paid_amount'))['s'] or Decimal('0.00')
        remaining_balance = total_required - total_paid

        today = timezone.now().date()
        total_overdue = installments.filter(
            due_date__lt=today
        ).aggregate(
            s=Sum(F('amount_due') - F('paid_amount'))
        )['s'] or Decimal('0.00')

        total_overdue = max(Decimal('0.00'), total_overdue)

        if total_required > 0:
            paid_percentage = round((total_paid / total_required) * 100)
        else:
            paid_percentage = 0

        context = {
            "student": student,
            "installments": installments,
            "total_required": total_required,
            "total_paid": total_paid,
            "total_overdue": total_overdue,
            "remaining_balance": remaining_balance,
            "paid_percentage": paid_percentage,
        }

        return render(request, "students/student_dashboard.html", context)

    return redirect('student_list')


def is_manager(user):
    return user.is_authenticated and (user.is_superuser or user.is_staff)

@login_required
def student_list(request):
    all_years = AcademicYear.objects.all().order_by('-name')
    all_grades = Grade.objects.all().order_by('id')
    all_classrooms = Classroom.objects.select_related('grade').all()

    selected_year_id = request.GET.get('year_id')
    grade_id = request.GET.get('grade_id')
    classroom_id = request.GET.get('classroom_id')
    specialization = request.GET.get('specialization')
    gender = request.GET.get('gender')
    religion = request.GET.get('religion')
    is_disability = request.GET.get('is_disability')
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status')

    if selected_year_id:
        current_view_year = get_object_or_404(AcademicYear, id=selected_year_id)
        is_archive = not current_view_year.is_active
    else:
        current_view_year = AcademicYear.objects.filter(is_active=True).first() or all_years.first()
        is_archive = False

    if current_view_year:
        if status_filter == 'graduated':
            base_query = Student.objects.filter(academic_year=current_view_year, enrollment_status='Graduated').select_related("grade", "classroom")
        else:
            # 🟢 التعديل: إظهار الطلاب النشطين أو من عليهم مديونية قديمة
            base_query = Student.objects.filter(
                Q(is_active=True) | Q(previous_debt__gt=0),
                academic_year=current_view_year
            ).select_related("grade", "classroom")

        graduated_count = Student.objects.filter(academic_year=current_view_year, enrollment_status='Graduated').count()

        if grade_id:
            base_query = base_query.filter(grade_id=grade_id)
        if classroom_id:
            base_query = base_query.filter(classroom_id=classroom_id)
        if specialization:
            base_query = base_query.filter(specialization=specialization)
        if gender:
            base_query = base_query.filter(gender=gender)
        if religion:
            base_query = base_query.filter(religion=religion)
        if is_disability:
            base_query = base_query.filter(integration_status=(is_disability == 'true'))

        if search_query:
            words = search_query.split()
            for word in words:
                # توحيد الحروف العربية للبحث المرن
                norm_word = word.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')
                base_query = base_query.filter(
                    Q(search_name__icontains=norm_word) |
                    Q(student_code__icontains=word) |
                    Q(national_id__icontains=word)
                )

        installments_exists_subquery = StudentInstallment.objects.filter(student=OuterRef('pk'), academic_year=current_view_year)

        # 🟢 المسدد من المصاريف الحالية (شامل التسويات القديمة ليظهر المحصل كاملاً)
        receipts_subquery = Payment.objects.filter(
            student=OuterRef('pk'),
            academic_year=current_view_year,
            is_cancelled=False
        ).exclude(revenue_category__name__icontains="مديوني").values('student').annotate(t=Sum('amount_paid')).values('t')

        # 🟢 المسدد من المديونية القديمة (شامل التسويات القديمة)
        old_debt_receipts_subquery = Payment.objects.filter(
            student=OuterRef('pk'),
            academic_year=current_view_year,
            is_cancelled=False,
            revenue_category__name__icontains="مديوني"
        ).values('student').annotate(t=Sum('amount_paid')).values('t')

        discount_subquery = StudentAccount.objects.filter(student=OuterRef('pk'), academic_year=current_view_year).values('student').annotate(t=Sum('discount')).values('t')
        installments_subquery = StudentInstallment.objects.filter(student=OuterRef('pk'), academic_year=current_view_year).values('student').annotate(t=Sum('amount_due')).values('t')
        late_fees_subquery = StudentInstallment.objects.filter(student=OuterRef('pk'), academic_year=current_view_year).values('student').annotate(t=Sum('late_fee')).values('t')

        financial_annotations = {
            'is_assigned': Exists(installments_exists_subquery),
            'fees_display': Coalesce(Subquery(installments_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            'late_fees_display': Coalesce(Subquery(late_fees_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            'total_paid_display': Coalesce(Subquery(receipts_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            'old_debt_paid_display': Coalesce(Subquery(old_debt_receipts_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
            'discount_display': Coalesce(Subquery(discount_subquery, output_field=DecimalField()), Value(0, output_field=DecimalField())),
        }

        if status_filter == 'assigned':
            base_query = base_query.filter(installments__academic_year=current_view_year).distinct()
        elif status_filter == 'unassigned':
            base_query = base_query.exclude(installments__academic_year=current_view_year)
        elif status_filter in ['debt', 'paid']:
            base_query = base_query.annotate(**financial_annotations).annotate(
                net_old_debt=ExpressionWrapper(
                    Coalesce(F('previous_debt'), Value(0, output_field=DecimalField())) - F('old_debt_paid_display'),
                    output_field=DecimalField()
                ),
                calculated_remaining_approx=ExpressionWrapper(
                    (F('net_old_debt') + F('fees_display') + F('late_fees_display')) -
                    (F('total_paid_display') + F('discount_display')), output_field=DecimalField()
                )
            )
            if status_filter == 'debt':
                base_query = base_query.filter(calculated_remaining_approx__gt=0.01)
            elif status_filter == 'paid':
                base_query = base_query.filter(is_assigned=True, calculated_remaining_approx__lte=0.01)

        base_query = base_query.order_by('first_name', 'id')
        paginator = Paginator(base_query, 20)
        current_page_number = request.GET.get('page', 1)
        students_page = paginator.get_page(current_page_number)

        page_student_ids = [student.id for student in students_page.object_list]

        annotated_20_students = Student.objects.filter(id__in=page_student_ids).annotate(**financial_annotations)
        financial_map = {s.id: s for s in annotated_20_students}

        for student in students_page.object_list:
            fin_data = financial_map.get(student.id)
            student.is_assigned = fin_data.is_assigned if fin_data else False
            student.fees_display = fin_data.fees_display if fin_data else Decimal('0.00')
            student.late_fees_display = fin_data.late_fees_display if fin_data else Decimal('0.00')
            student.total_paid_display = fin_data.total_paid_display if fin_data else Decimal('0.00')
            student.old_debt_paid_display = getattr(fin_data, 'old_debt_paid_display', Decimal('0.00')) if fin_data else Decimal('0.00')
            student.discount_display = fin_data.discount_display if fin_data else Decimal('0.00')

            # 🟢 المديونية القديمة الصافية
            old_d = student.previous_debt or Decimal('0.00')
            student.net_old_debt_display = max(Decimal('0.00'), old_d - student.old_debt_paid_display)
            student.old_debt_display = student.net_old_debt_display

            raw_remaining = (
                student.net_old_debt_display + student.fees_display + student.late_fees_display
            ) - (student.total_paid_display + student.discount_display)

            student.calculated_remaining = max(Decimal('0.00'), raw_remaining)

        force_refresh = request.GET.get('refresh') == '1'
        filter_raw_str = f"y_{selected_year_id}_g_{grade_id}_c_{classroom_id}_sp_{specialization}_gen_{gender}_rel_{religion}_dis_{is_disability}_q_{search_query}_st_{status_filter}"
        cache_hash = hashlib.md5(filter_raw_str.encode('utf-8')).hexdigest()
        cache_key = f"student_stats_v4_{cache_hash}"

        if force_refresh:
            cache.delete(cache_key)

        stats = cache.get(cache_key)

        if not stats:
            stats_base_qs = Student.objects.filter(academic_year=current_view_year)
            if status_filter == 'graduated':
                stats_base_qs = stats_base_qs.filter(enrollment_status='Graduated')
            else:
                stats_base_qs = stats_base_qs.filter(is_active=True)

            if grade_id: stats_base_qs = stats_base_qs.filter(grade_id=grade_id)
            if classroom_id: stats_base_qs = stats_base_qs.filter(classroom_id=classroom_id)
            if specialization: stats_base_qs = stats_base_qs.filter(specialization=specialization)
            if gender: stats_base_qs = stats_base_qs.filter(gender=gender)
            if religion: stats_base_qs = stats_base_qs.filter(religion=religion)
            if is_disability: stats_base_qs = stats_base_qs.filter(integration_status=(is_disability == 'true'))

            if search_query:
                words = search_query.split()
                for word in words:
                    norm_word = word.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')
                    stats_base_qs = stats_base_qs.filter(
                        Q(search_name__icontains=norm_word) |
                        Q(student_code__icontains=word) |
                        Q(national_id__icontains=word)
                    )

            total_st_count = stats_base_qs.count()
            assigned_st_count = stats_base_qs.filter(installments__academic_year=current_view_year).distinct().count()
            unassigned_st_count = total_st_count - assigned_st_count

            annotated_stats_qs = stats_base_qs.annotate(**financial_annotations).annotate(
                calc_net_old=ExpressionWrapper(
                    Coalesce(F('previous_debt'), Value(0, output_field=DecimalField())) - F('old_debt_paid_display'),
                    output_field=DecimalField()
                ),
                calc_rem=ExpressionWrapper(
                    (F('calc_net_old') + F('fees_display') + F('late_fees_display')) -
                    (F('total_paid_display') + F('discount_display')), output_field=DecimalField()
                )
            )

            debt_st_count = annotated_stats_qs.filter(calc_rem__gt=0.01).count()
            paid_st_count = annotated_stats_qs.filter(is_assigned=True, calc_rem__lte=0.01).count()

            stats = {
                'total': total_st_count,
                'assigned': assigned_st_count,
                'unassigned': unassigned_st_count,
                'paid': paid_st_count,
                'debt': debt_st_count,
            }
            cache.set(cache_key, stats, 300)

        total_count = stats.get('total', 0)
        assigned_count = stats.get('assigned', 0)
        unassigned_count = stats.get('unassigned', 0)
        paid_count = stats.get('paid', 0)
        debt_count = stats.get('debt', 0)

    else:
        students_page = []
        total_count = assigned_count = unassigned_count = paid_count = debt_count = graduated_count = 0

    context = {
        "students": students_page,
        "all_years": all_years,
        "all_grades": all_grades,
        "all_classrooms": all_classrooms,
        "current_view_year": current_view_year,
        "selected_grade": grade_id,
        "selected_classroom": classroom_id,
        "selected_specialization": specialization,
        "selected_gender": gender,
        "selected_religion": religion,
        "selected_is_disability": is_disability,
        "is_archive": is_archive,
        "total_count": total_count,
        "assigned_count": assigned_count,
        "unassigned_count": unassigned_count,
        "paid_count": paid_count,
        "debt_count": debt_count,
        "graduated_count": graduated_count,
        "search_query": search_query,
        "status_filter": status_filter,
    }
    return render(request, "students/student_list.html", context)





def add_student(request):
    student_id = request.GET.get('edit_id')
    notify_id = request.GET.get('notify_id')  # 🟢 استقبال رقم إشعار التقديم
    student = None

    if student_id:
        student = get_object_or_404(Student, id=student_id)

    # 🟢 سحب بيانات الطالب من الإشعار (إن وجد) لتعبئة الحقول تلقائياً
    initial_data = {}
    pending_notice = None

    if notify_id and not student_id:
        pending_notice = PendingAdmissionNotification.objects.filter(id=notify_id, is_processed=False).first()
        if pending_notice:
            # فصل الاسم الرباعي إلى اسم أول وعائلة
            name_parts = pending_notice.full_name_ar.strip().split(' ', 1)
            initial_data = {
                'first_name': name_parts[0],
                'last_name': name_parts[1] if len(name_parts) > 1 else '',
                'national_id': pending_notice.national_id,
                'phone': pending_notice.phone,
                'whatsapp_number': pending_notice.whatsapp_number,
                'address': pending_notice.address,
                'gender': pending_notice.gender,
                'birth_place': pending_notice.birth_governorate,
                'date_of_birth': pending_notice.birth_date,
            }

    search_query = request.GET.get('q', '')
    grade_id = request.GET.get('grade_id', '')
    classroom_id = request.GET.get('classroom_id', '')
    specialization = request.GET.get('specialization', '')
    gender = request.GET.get('gender', '')
    religion = request.GET.get('religion', '')
    is_disability = request.GET.get('is_disability', '')
    page = request.GET.get('page', '1')

    if request.method == 'POST':
        form = StudentForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            is_new = student is None
            saved_student = form.save(commit=False)

            # 🟢 عند إضافة طالب جديد لأول مرة فقط
            if is_new:
                # 1. مزامنة حالة القيد الحالية مع حالة فتح الملف
                saved_student.enrollment_status = saved_student.initial_status or "New"

                # 2. جلب رسوم فتح الملف المحددة بالسنة الدراسية (إذا لم يكن معافى)
                if saved_student.is_application_fee_exempt:
                    saved_student.application_fee_amount = Decimal('0.00')
                else:
                    if saved_student.academic_year:
                        saved_student.application_fee_amount = getattr(saved_student.academic_year, 'application_fee', Decimal('0.00'))
                    else:
                        saved_student.application_fee_amount = Decimal('0.00')

                # 🌟 3. نقل الصور والمستندات من الإشعار إلى ملف الطالب الجديد الفعلي (تم تعديل اسم الحقل إلى image)
                if pending_notice:
                    if hasattr(pending_notice, 'student_photo') and pending_notice.student_photo:
                        saved_student.image = pending_notice.student_photo  # 🟢 الربط المباشر بحقل صورة الطالب image
                    if hasattr(pending_notice, 'parent_id_photo') and pending_notice.parent_id_photo:
                        saved_student.parent_id_photo = pending_notice.parent_id_photo
                    if hasattr(pending_notice, 'birth_certificate') and pending_notice.birth_certificate:
                        saved_student.birth_certificate = pending_notice.birth_certificate
                    if hasattr(pending_notice, 'qualification_photo') and pending_notice.qualification_photo:
                        saved_student.qualification_photo = pending_notice.qualification_photo

            saved_student.save()
            form.save_m2m()

            # 🟢 إغلاق الإشعار واعتباره "مُعالج" حتى لا يظهر مرة أخرى
            if pending_notice:
                pending_notice.is_processed = True
                pending_notice.save()

            # 🟢 التسميع الفوري في الخزينة العامة إذا كانت الرسوم أكبر من الصفر
            registered_in_treasury = False
            if is_new and getattr(saved_student, 'application_fee_amount', Decimal('0.00')) > Decimal('0.00'):
                try:
                    receipt_code = f"APP-{saved_student.id}-{int(time.time())}"
                    GeneralLedger.objects.create(
                        student=saved_student,
                        amount=saved_student.application_fee_amount,
                        category='ملف',
                        notes=f"تحصيل رسوم فتح ملف للطالب: {saved_student.get_full_name()}",
                        receipt_number=receipt_code,
                        collected_by=request.user
                    )
                    registered_in_treasury = True
                except Exception as e:
                    print(f"⚠️ تنبيه: تم حفظ الطالب وتعذر تسجيل قيد الخزينة: {e}")

            # 🟢 إعداد الرسائل وتنسيق التوجيه
            if student:
                messages.success(request, f"تم تحديث بيانات الطالب {saved_student.get_full_name()} بنجاح.")
                registry_url = reverse('student_registry')
                redirect_url = f"{registry_url}?page={page}"
                if search_query: redirect_url += f"&q={search_query}"
                if grade_id: redirect_url += f"&grade_id={grade_id}"
                if classroom_id: redirect_url += f"&classroom_id={classroom_id}"
                if specialization: redirect_url += f"&specialization={specialization}"
                if gender: redirect_url += f"&gender={gender}"
                if religion: redirect_url += f"&religion={religion}"
                if is_disability: redirect_url += f"&is_disability={is_disability}"

                redirect_url += f"#student-{saved_student.id}"
                return redirect(redirect_url)
            else:
                if registered_in_treasury:
                    messages.success(request, f"تم إضافة الطالب {saved_student.get_full_name()} وتسجيل رسوم فتح الملف ({saved_student.application_fee_amount} ج.م) بالخزينة بنجاح.")
                else:
                    messages.success(request, f"تم إضافة الطالب الجديد {saved_student.get_full_name()} بنجاح.")

                return redirect('student_registry')
    else:
        # 🟢 إذا كان هناك إشعار، نمرر البيانات المسحوبة للفورم
        if pending_notice:
            form = StudentForm(instance=student, initial=initial_data)
            messages.info(request, "تم سحب بيانات الطالب من بوابة التقديم بنجاح. يرجى مراجعتها وتحديد (الصف والفصل الدراسي) ثم الحفظ.")
        else:
            form = StudentForm(instance=student)

    grades = Grade.objects.all()
    classrooms = Classroom.objects.all()

    context = {
        'form': form,
        'student': student,
        'notification': pending_notice,  # 🌟 تم تمرير الإشعار لـ HTML بقالب add_student
        'grades': grades,
        'classrooms': classrooms,
        'is_edit': student is not None,
        'is_from_notification': bool(pending_notice),
        'search_params': {
            'q': search_query, 'grade_id': grade_id, 'classroom_id': classroom_id,
            'specialization': specialization, 'gender': gender, 'religion': religion,
            'is_disability': is_disability, 'page': page
        }
    }
    return render(request, 'students/add_student.html', context)



from django.contrib.auth.decorators import user_passes_test

@user_passes_test(lambda u: u.is_superuser)
def promote_student(request, student_id):
    try:
        if not request.user.is_superuser:
            messages.error(request, "عذراً، لا تمتلك صلاحية تنفيذ هذا الإجراء الحساس.")
            return redirect("students_list")

        student = get_object_or_404(Student, id=student_id)

        all_years = list(AcademicYear.objects.all().order_by('name'))
        next_year = None
        for i, year in enumerate(all_years):
            if year.id == student.academic_year.id:
                if i + 1 < len(all_years):
                    next_year = all_years[i+1]
                break

        if not next_year:
            messages.warning(request, "لا توجد سنة تالية")
            return redirect("students_list")

        success = promote_student_action(
            student_id=student.id,
            target_year_id=next_year.id,
            target_grade_id=student.grade.id
        )

        if success:
            messages.success(request, f"تم ترحيل الطالب {student.get_full_name()} بنجاح")
        else:
            messages.error(request, "فشل الترحيل، يرجى مراجعة سجل الأخطاء")

    except Exception as e:
        messages.error(request, f"خطأ غير متوقع: {str(e)}")

    return redirect("students_list")


def student_detail_view(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    account = getattr(student, 'account', None)
    installments = student.installments.all().order_by('due_date')

    context = {
        'student': student,
        'account': account,
        'installments': installments,
        'student_admin_mode': True,
    }
    return render(request, 'students/add_student.html', context)


from treasury.models import GeneralLedger
from .forms import GeneralLedgerForm

def add_ledger_entry(request):
    if request.method == 'POST':
        form = GeneralLedgerForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.collected_by = request.user
            entry.save()
            return redirect('student_list')
    else:
        form = GeneralLedgerForm()

    return render(request, 'treasury/treasury_form.html', {'form': form})


def get_first_day_of_next_month(d):
    """إرجاع أول يوم في الشهر التالي لتطبيق شرط الغرامة"""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)

@login_required
def overdue_installments_list(request):
    """
    Call Center CRM View - Super Fast ORM Querying with Live Instant Search
    🟢 تم إضافة التعديل السحري لعزل المديونية القديمة عن حسابات العام الحالي
    """
    today = timezone.localtime().date()
    current_year = AcademicYear.objects.filter(is_active=True).first()

    action = request.GET.get('action') or request.POST.get('action')

    # 1. AJAX: Student details for modal
    if action == 'get_student_details':
        student_id = request.GET.get('student_id')
        student = get_object_or_404(Student, id=student_id)

        account = StudentAccount.objects.filter(student=student, academic_year=current_year).first()
        total_fees = account.total_fees if account else Decimal('0.00')
        old_debt = student.previous_debt or Decimal('0.00')

        # 🟢 العزل: حساب ما تم سداده من المديونية القديمة فقط
        old_debt_paid = Payment.objects.filter(
            student=student,
            academic_year=current_year,
            is_cancelled=False,
            is_settlement_only=False,
            revenue_category__name__icontains="مديوني"
        ).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')

        net_old_debt = max(Decimal('0.00'), old_debt - old_debt_paid)

        installments = StudentInstallment.objects.filter(student=student).order_by('due_date')

        # 🟢 العزل: حساب المسدد من الأقساط الحالية فقط (استبعاد المديونية القديمة والتسويات)
        current_paid = Payment.objects.filter(
            student=student,
            academic_year=current_year,
            is_cancelled=False,
            is_settlement_only=False
        ).exclude(revenue_category__name__icontains="مديوني").aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')

        installments_data = []
        for inst in installments:
            remaining = max(Decimal('0.00'), inst.amount_due - inst.paid_amount)
            penalty_start = get_first_day_of_next_month(inst.due_date)
            applied_late_fee = inst.late_fee if today >= penalty_start else Decimal('0.00')

            if today >= inst.due_date and (remaining > 0 or applied_late_fee > 0):
                installments_data.append({
                    'number': inst.installment_number,
                    'due_date': inst.due_date.strftime('%Y-%m-%d'),
                    'amount_due': float(inst.amount_due),
                    'paid_amount': float(inst.paid_amount),
                    'remaining': float(remaining),
                    'late_fee': float(applied_late_fee),
                    'total_required': float(remaining + applied_late_fee),
                    'status_display': inst.get_status_display()
                })

        total_late_fees = sum(i['late_fee'] for i in installments_data)
        total_obligation = max(Decimal('0.00'), (total_fees + net_old_debt + total_late_fees) - current_paid)

        return JsonResponse({
            'status': 'success',
            'student_name': student.get_full_name(),
            'installments': installments_data,
            'total_inst_due': float(total_fees + net_old_debt),
            'total_fees': float(total_fees),
            'old_debt': float(net_old_debt),
            'total_paid': float(current_paid),
            'total_late_fee': float(total_late_fees),
            'total_obligation': float(total_obligation)
        })

    # 2. AJAX: Get call notes
    if action == 'get_notes':
        student_id = request.GET.get('student_id')
        notes_list = []
        try:
            CallNoteModel = apps.get_model('finance', 'StudentCallNote')
            for n in CallNoteModel.objects.filter(student_id=student_id).select_related('author'):
                author_name = n.author.get_full_name() or n.author.username if n.author else "موظف النظام"
                notes_list.append({
                    'author': author_name,
                    'time': timezone.localtime(n.created_at).strftime('%Y-%m-%d %I:%M %p'),
                    'text': n.note_text
                })
        except Exception:
            pass
        return JsonResponse({'status': 'success', 'notes': notes_list})

    # 3. AJAX: Add call note
    if request.method == 'POST' and action == 'add_note':
        student_id = request.POST.get('student_id')
        note_text = request.POST.get('note_text', '').strip()

        if student_id and note_text:
            student = get_object_or_404(Student, id=student_id)
            try:
                CallNoteModel = apps.get_model('finance', 'StudentCallNote')
                note = CallNoteModel.objects.create(
                    student=student,
                    author=request.user,
                    note_text=note_text
                )
                author_name = request.user.get_full_name() or request.user.username
                return JsonResponse({
                    'status': 'success',
                    'message': 'تم تسجيل نتيجة المكالمة بنجاح.',
                    'latest_note': note.note_text,
                    'note': {
                        'author': author_name,
                        'time': timezone.localtime(note.created_at).strftime('%Y-%m-%d %I:%M %p'),
                        'text': note.note_text
                    }
                })
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        return JsonResponse({'status': 'error', 'message': 'بيانات غير مكتملة.'}, status=400)

    # 4. Main Query Optimization
    search_q = request.GET.get('q', '').strip()
    grade_id = request.GET.get('grade_id', '')
    specialization = request.GET.get('specialization', '')

    base_students = Student.objects.filter(is_active=True).filter(
        Q(previous_debt__gt=0) |
        Q(installments__due_date__lte=today, installments__paid_amount__lt=F('installments__amount_due'))
    ).distinct().select_related('grade')

    if grade_id:
        base_students = base_students.filter(grade_id=grade_id)
    if specialization:
        base_students = base_students.filter(specialization=specialization)

    if search_q:
        base_students = base_students.annotate(
            full_name_db=Concat('first_name', Value(' '), 'last_name', output_field=CharField())
        )
        for w in search_q.split():
            q_cond = (
                Q(first_name__icontains=w) |
                Q(last_name__icontains=w) |
                Q(full_name_db__icontains=w) |
                Q(student_code__icontains=w) |
                Q(national_id__icontains=w)
            )
            for p_field in ['phone', 'whatsapp_number', 'parent_phone', 'guardian_phone', 'father_phone', 'mother_phone']:
                if hasattr(Student, p_field):
                    q_cond |= Q(**{f"{p_field}__icontains": w})
            base_students = base_students.filter(q_cond)

    base_students = base_students.order_by('first_name', 'id')

    paginator = Paginator(base_students, 20)
    page_number = request.GET.get('page', 1)
    students_page = paginator.get_page(page_number)

    page_student_objs = students_page.object_list
    page_student_ids = [st.id for st in page_student_objs]

    # 🟢 جلب مدفوعات المديونية القديمة الحقيقية فقط لكل طلاب الصفحة لعزلها
    old_debt_payments_qs = Payment.objects.filter(
        student_id__in=page_student_ids,
        academic_year=current_year,
        is_cancelled=False,
        is_settlement_only=False,
        revenue_category__name__icontains="مديوني"
    ).values('student_id').annotate(total=Sum('amount_paid'))
    old_debt_paid_map = {item['student_id']: item['total'] for item in old_debt_payments_qs}

    CallNoteModel = apps.get_model('finance', 'StudentCallNote')
    latest_notes_dict = {}
    notes_count_dict = {}
    try:
        notes_qs = CallNoteModel.objects.filter(student_id__in=page_student_ids).order_by('created_at')
        for n in notes_qs:
            latest_notes_dict[n.student_id] = n.note_text
            notes_count_dict[n.student_id] = notes_count_dict.get(n.student_id, 0) + 1
    except Exception:
        pass

    inst_qs = StudentInstallment.objects.filter(
        student_id__in=page_student_ids,
        due_date__lte=today,
        paid_amount__lt=F('amount_due')
    )
    inst_map = {}
    for inst in inst_qs:
        if inst.student_id not in inst_map:
            inst_map[inst.student_id] = []
        inst_map[inst.student_id].append(inst)

    students_list = []
    for st in page_student_objs:
        # 🟢 حساب المديونية القديمة الصافية بعد خصم المدفوع منها
        old_d = st.previous_debt or Decimal('0.00')
        old_d_paid = old_debt_paid_map.get(st.id, Decimal('0.00'))
        net_old_debt = max(Decimal('0.00'), old_d - old_d_paid)

        phone = getattr(st, 'parent_phone', None) or getattr(st, 'guardian_phone', None) or getattr(st, 'phone', '---')
        whatsapp = getattr(st, 'whatsapp_number', None) or phone

        total_req = net_old_debt
        total_overdue_amount = net_old_debt
        total_late_fee = Decimal('0.00')
        overdue_cnt = 1 if net_old_debt > 0 else 0

        st_insts = inst_map.get(st.id, [])
        for inst in st_insts:
            inst_remaining = max(Decimal('0.00'), inst.amount_due - inst.paid_amount)
            penalty_start = get_first_day_of_next_month(inst.due_date)
            applied_late_fee = inst.late_fee if today >= penalty_start else Decimal('0.00')

            if inst_remaining > 0 or applied_late_fee > 0:
                overdue_cnt += 1
                total_overdue_amount += inst_remaining
                total_late_fee += applied_late_fee
                total_req += (inst_remaining + applied_late_fee)

        students_list.append({
            'id': st.id,
            'full_name': st.get_full_name(),
            'student_code': getattr(st, 'student_code', '---'),
            'grade': st.grade.name if st.grade else 'غير محدد',
            'specialization': st.get_specialization_display() if st.specialization else 'شعبة عامة',
            'phone': phone,
            'whatsapp_number': whatsapp,
            'overdue_count': overdue_cnt,
            'overdue_amount': float(total_overdue_amount), # 🟢 تم الربط بمتغيرات الـ HTML بدقة
            'late_fee_amount': float(total_late_fee),      # 🟢 تم الربط بمتغيرات الـ HTML بدقة
            'total_required': float(total_req),            # 🟢 تم الربط بمتغيرات الـ HTML بدقة
            'notes_count': notes_count_dict.get(st.id, 0),
            'latest_note': latest_notes_dict.get(st.id, "لا يوجد اتصال سابق")
        })

    students_page.object_list = students_list

    context = {
        'today': today,
        'students_list': students_page,
        'total_cases_count': paginator.count,
        'all_grades': Grade.objects.all(),
        'all_specs': Student.SPECIALIZATION_CHOICES if hasattr(Student, 'SPECIALIZATION_CHOICES') else [],
        'selected_grade': grade_id,
        'selected_spec': specialization,
        'search_q': search_q,
    }
    return render(request, 'finance/overdue_report.html', context)


# @login_required
# def overdue_installments_list(request):
#     """
#     Call Center CRM View - Super Fast ORM Querying with Live Instant Search
#     """
#     today = timezone.localtime().date()
#     current_year = AcademicYear.objects.filter(is_active=True).first()

#     action = request.GET.get('action') or request.POST.get('action')

#     # 1. AJAX: Student details for modal
#     if action == 'get_student_details':
#         student_id = request.GET.get('student_id')
#         student = get_object_or_404(Student, id=student_id)

#         account = StudentAccount.objects.filter(student=student, academic_year=current_year).first()
#         total_fees = account.total_fees if account else Decimal('0.00')
#         old_debt = student.previous_debt or Decimal('0.00')

#         installments = StudentInstallment.objects.filter(student=student).order_by('due_date')
#         total_paid = installments.aggregate(s=Sum('paid_amount'))['s'] or Decimal('0.00')

#         installments_data = []
#         for inst in installments:
#             remaining = max(Decimal('0.00'), inst.amount_due - inst.paid_amount)
#             penalty_start = get_first_day_of_next_month(inst.due_date)
#             applied_late_fee = inst.late_fee if today >= penalty_start else Decimal('0.00')

#             if today >= inst.due_date and (remaining > 0 or applied_late_fee > 0):
#                 installments_data.append({
#                     'number': inst.installment_number,
#                     'due_date': inst.due_date.strftime('%Y-%m-%d'),
#                     'amount_due': float(inst.amount_due),
#                     'paid_amount': float(inst.paid_amount),
#                     'remaining': float(remaining),
#                     'late_fee': float(applied_late_fee),
#                     'total_required': float(remaining + applied_late_fee),
#                     'status_display': inst.get_status_display()
#                 })

#         total_obligation = max(Decimal('0.00'), (total_fees + old_debt + sum(i['late_fee'] for i in installments_data)) - total_paid)

#         return JsonResponse({
#             'status': 'success',
#             'student_name': student.get_full_name(),
#             'installments': installments_data,
#             'total_fees': float(total_fees),
#             'old_debt': float(old_debt),
#             'total_paid': float(total_paid),
#             'total_late_fee': float(sum(i['late_fee'] for i in installments_data)),
#             'total_obligation': float(total_obligation)
#         })

#     # 2. AJAX: Get call notes
#     if action == 'get_notes':
#         student_id = request.GET.get('student_id')
#         notes_list = []
#         try:
#             CallNoteModel = apps.get_model('finance', 'StudentCallNote')
#             for n in CallNoteModel.objects.filter(student_id=student_id).select_related('author'):
#                 author_name = n.author.get_full_name() or n.author.username if n.author else "موظف النظام"
#                 notes_list.append({
#                     'author': author_name,
#                     'time': timezone.localtime(n.created_at).strftime('%Y-%m-%d %I:%M %p'),
#                     'text': n.note_text
#                 })
#         except Exception:
#             pass
#         return JsonResponse({'status': 'success', 'notes': notes_list})

#     # 3. AJAX: Add call note
#     if request.method == 'POST' and action == 'add_note':
#         student_id = request.POST.get('student_id')
#         note_text = request.POST.get('note_text', '').strip()

#         if student_id and note_text:
#             student = get_object_or_404(Student, id=student_id)
#             try:
#                 CallNoteModel = apps.get_model('finance', 'StudentCallNote')
#                 note = CallNoteModel.objects.create(
#                     student=student,
#                     author=request.user,
#                     note_text=note_text
#                 )
#                 author_name = request.user.get_full_name() or request.user.username
#                 return JsonResponse({
#                     'status': 'success',
#                     'message': 'تم تسجيل نتيجة المكالمة بنجاح.',
#                     'latest_note': note.note_text,
#                     'note': {
#                         'author': author_name,
#                         'time': timezone.localtime(note.created_at).strftime('%Y-%m-%d %I:%M %p'),
#                         'text': note.note_text
#                     }
#                 })
#             except Exception as e:
#                 return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
#         return JsonResponse({'status': 'error', 'message': 'بيانات غير مكتملة.'}, status=400)

#     # 4. Main Query Optimization (Direct Indexed DB Search)
#     search_q = request.GET.get('q', '').strip()
#     grade_id = request.GET.get('grade_id', '')
#     specialization = request.GET.get('specialization', '')

#     base_students = Student.objects.filter(is_active=True).filter(
#         Q(previous_debt__gt=0) |
#         Q(installments__due_date__lte=today, installments__paid_amount__lt=F('installments__amount_due'))
#     ).distinct().select_related('grade')

#     if grade_id:
#         base_students = base_students.filter(grade_id=grade_id)
#     if specialization:
#         base_students = base_students.filter(specialization=specialization)

#     if search_q:
#         base_students = base_students.annotate(
#             full_name_db=Concat('first_name', Value(' '), 'last_name', output_field=CharField())
#         )
#         for w in search_q.split():
#             q_cond = (
#                 Q(first_name__icontains=w) |
#                 Q(last_name__icontains=w) |
#                 Q(full_name_db__icontains=w) |
#                 Q(student_code__icontains=w) |
#                 Q(national_id__icontains=w)
#             )
#             for p_field in ['phone', 'whatsapp_number', 'parent_phone', 'guardian_phone', 'father_phone', 'mother_phone']:
#                 if hasattr(Student, p_field):
#                     q_cond |= Q(**{f"{p_field}__icontains": w})
#             base_students = base_students.filter(q_cond)

#     base_students = base_students.order_by('first_name', 'id')

#     paginator = Paginator(base_students, 20)
#     page_number = request.GET.get('page', 1)
#     students_page = paginator.get_page(page_number)

#     page_student_objs = students_page.object_list
#     page_student_ids = [st.id for st in page_student_objs]

#     CallNoteModel = apps.get_model('finance', 'StudentCallNote')
#     latest_notes_dict = {}
#     notes_count_dict = {}
#     try:
#         notes_qs = CallNoteModel.objects.filter(student_id__in=page_student_ids).order_by('created_at')
#         for n in notes_qs:
#             latest_notes_dict[n.student_id] = n.note_text
#             notes_count_dict[n.student_id] = notes_count_dict.get(n.student_id, 0) + 1
#     except Exception:
#         pass

#     inst_qs = StudentInstallment.objects.filter(
#         student_id__in=page_student_ids,
#         due_date__lte=today,
#         paid_amount__lt=F('amount_due')
#     )
#     inst_map = {}
#     for inst in inst_qs:
#         if inst.student_id not in inst_map:
#             inst_map[inst.student_id] = []
#         inst_map[inst.student_id].append(inst)

#     students_list = []
#     for st in page_student_objs:
#         old_d = st.previous_debt or Decimal('0.00')
#         phone = getattr(st, 'parent_phone', None) or getattr(st, 'guardian_phone', None) or getattr(st, 'phone', '---')
#         whatsapp = getattr(st, 'whatsapp_number', None) or phone

#         total_req = old_d
#         overdue_cnt = 1 if old_d > 0 else 0

#         st_insts = inst_map.get(st.id, [])
#         for inst in st_insts:
#             inst_remaining = max(Decimal('0.00'), inst.amount_due - inst.paid_amount)
#             penalty_start = get_first_day_of_next_month(inst.due_date)
#             applied_late_fee = inst.late_fee if today >= penalty_start else Decimal('0.00')

#             if inst_remaining > 0 or applied_late_fee > 0:
#                 overdue_cnt += 1
#                 total_req += (inst_remaining + applied_late_fee)

#         students_list.append({
#             'id': st.id,
#             'full_name': st.get_full_name(),
#             'student_code': getattr(st, 'student_code', '---'),
#             'grade': st.grade.name if st.grade else 'غير محدد',
#             'specialization': st.get_specialization_display() if st.specialization else 'شعبة عامة',
#             'phone': phone,
#             'whatsapp_number': whatsapp,
#             'overdue_count': overdue_cnt,
#             'total_required': total_req,
#             'notes_count': notes_count_dict.get(st.id, 0),
#             'latest_note': latest_notes_dict.get(st.id, "لا يوجد اتصال سابق")
#         })

#     students_page.object_list = students_list

#     context = {
#         'today': today,
#         'students_list': students_page,
#         'total_cases_count': paginator.count,
#         'all_grades': Grade.objects.all(),
#         'all_specs': Student.SPECIALIZATION_CHOICES if hasattr(Student, 'SPECIALIZATION_CHOICES') else [],
#         'selected_grade': grade_id,
#         'selected_spec': specialization,
#         'search_q': search_q,
#     }
#     return render(request, 'finance/overdue_report.html', context)



class StudentListAPI(generics.ListAPIView):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['first_name', 'last_name', 'national_id']


from .models import RemedialProgramRecord

def get_remedial_balance_api(request, student_id):
    """API مخصص لجلب رصيد البرنامج العلاجي"""
    try:
        remedial_qs = RemedialProgramRecord.objects.filter(
            student_id=student_id,
            is_paid=False
        )

        remedial_debt = remedial_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        remedial_notes_list = list(remedial_qs.values_list('notes', flat=True))
        remedial_notes = " - ".join([note for note in remedial_notes_list if note])

        return JsonResponse({
            'success': True,
            'remedial_debt': float(remedial_debt),
            'remedial_notes': remedial_notes,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})




# ==========================================
# 1. API البحث الفوري عن الطلاب
# ==========================================
@login_required
def api_search_students_sale(request):
    """
    مُحرك بحث سريع يقرأ الحروف المدخلة ويرجع النتائج في أجزاء من الثانية
    """
    q = request.GET.get('q', '').strip()

    # توفير موارد السيرفر: لا تبحث إذا كان النص أقل من حرفين
    if len(q) < 2:
        return JsonResponse({'students': []})

    # استخدام select_related لجلب بيانات الصف (Grade) في نفس الاستعلام لتسريع الأداء
    matched_students = Student.objects.select_related('grade').filter(
        Q(name__icontains=q) | Q(student_code__icontains=q)
    )[:10] # نكتفي بـ 10 نتائج فقط لتظل القائمة المنسدلة سريعة جداً

    students_data = [
        {
            'id': st.id,
            'name': st.name, # أو st.get_full_name() حسب الموديل لديك
            'grade': st.grade.name if st.grade else 'غير محدد',
            'code': st.student_code,
        }
        for st in matched_students
    ]

    return JsonResponse({'students': students_data})


# ==========================================
# 2. API الاستعلام المالي اللحظي للطالب
# ==========================================
@login_required
def api_financial_info(request, student_id):
    """
    بمجرد اختيار الطالب، يقوم هذا الـ API بحساب:
    (إجمالي قيمة باقة الكتب/الزي المقررة لصفه) - (ما تم سداده مسبقاً)
    """
    student = get_object_or_404(Student, id=student_id)

    # 1. جلب قيمة الباقات المقررة بناءً على الصف الدراسي للطالب
    books_pkg = GradeItemPackage.objects.filter(grade=student.grade, package_type='book').first()
    uniform_pkg = GradeItemPackage.objects.filter(grade=student.grade, package_type='uniform').first()

    books_total = books_pkg.total_price if books_pkg else 0.00
    uniform_total = uniform_pkg.total_price if uniform_pkg else 0.00

    # 2. حساب ما قام الطالب بدفعه مسبقاً (تجميع كل المبالغ من جدول عمليات الصرف)
    books_paid_agg = StudentSaleRecord.objects.filter(
        student=student, sale_type='book'
    ).aggregate(Sum('paid_amount'))
    books_paid = books_paid_agg['paid_amount__sum'] or 0.00

    uniform_paid_agg = StudentSaleRecord.objects.filter(
        student=student, sale_type='uniform'
    ).aggregate(Sum('paid_amount'))
    uniform_paid = uniform_paid_agg['paid_amount__sum'] or 0.00

    # 3. إرسال البيانات كـ JSON لتقرأها شاشة الـ POS
    data = {
        'books_total': float(books_total),
        'books_paid': float(books_paid),
        'uniform_total': float(uniform_total),
        'uniform_paid': float(uniform_paid),
    }
    return JsonResponse(data)


# ربط الاسم القديم بالدالة الجديدة لحل مشكلة السطر 185 فوراً
api_save_attendance_single = api_save_attendance_robust