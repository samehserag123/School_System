import re

view_code = '''
@login_required
def overdue_installments_list(request):
    """
    Call Center CRM View - Super Fast, Reliable Pagination, Full Field Search
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

        installments = StudentInstallment.objects.filter(student=student).order_by('due_date')
        total_paid = installments.aggregate(s=Sum('paid_amount'))['s'] or Decimal('0.00')

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

        total_obligation = max(Decimal('0.00'), (total_fees + old_debt + sum(i['late_fee'] for i in installments_data)) - total_paid)

        return JsonResponse({
            'status': 'success',
            'student_name': student.get_full_name(),
            'installments': installments_data,
            'total_fees': float(total_fees),
            'old_debt': float(old_debt),
            'total_paid': float(total_paid),
            'total_late_fee': float(sum(i['late_fee'] for i in installments_data)),
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

    overdue_inst_ids = set(
        StudentInstallment.objects.filter(
            due_date__lte=today,
            paid_amount__lt=F('amount_due')
        ).values_list('student_id', flat=True)
    )
    old_debt_ids = set(
        Student.objects.filter(is_active=True, previous_debt__gt=0).values_list('id', flat=True)
    )
    all_target_ids = overdue_inst_ids.union(old_debt_ids)

    base_students = Student.objects.filter(
        id__in=all_target_ids,
        is_active=True
    ).select_related('grade')

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
        old_d = st.previous_debt or Decimal('0.00')
        phone = getattr(st, 'parent_phone', None) or getattr(st, 'guardian_phone', None) or getattr(st, 'phone', '---')
        whatsapp = getattr(st, 'whatsapp_number', None) or phone

        total_req = old_d
        overdue_cnt = 1 if old_d > 0 else 0

        st_insts = inst_map.get(st.id, [])
        for inst in st_insts:
            inst_remaining = max(Decimal('0.00'), inst.amount_due - inst.paid_amount)
            penalty_start = get_first_day_of_next_month(inst.due_date)
            applied_late_fee = inst.late_fee if today >= penalty_start else Decimal('0.00')

            if inst_remaining > 0 or applied_late_fee > 0:
                overdue_cnt += 1
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
            'total_required': total_req,
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
'''

with open('students/views.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r'@login_required\s+def overdue_installments_list\(request\):[\s\S]*?(?=\n\nclass |\n\ndef |\Z)'
content = re.sub(pattern, view_code.strip(), content)

with open('students/views.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Views updated successfully")
