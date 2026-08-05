import re

view_code = '''

def get_first_day_of_next_month(d):
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


@login_required
def overdue_installments_list(request):
    today = timezone.localtime().date()
    current_year = AcademicYear.objects.filter(is_active=True).first()

    action = request.GET.get('action') or request.POST.get('action')

    if action == 'get_student_details':
        student_id = request.GET.get('student_id')
        student = get_object_or_404(Student, id=student_id)

        account = StudentAccount.objects.filter(student=student, academic_year=current_year).first()
        total_fees = account.total_fees if account else Decimal('0.00')
        old_debt = student.previous_debt or Decimal('0.00')

        installments = StudentInstallment.objects.filter(student=student).order_by('due_date')
        total_paid = installments.aggregate(s=Sum('paid_amount'))['s'] or Decimal('0.00')

        installments_data = []
        total_inst_due = Decimal('0.00')
        total_late_fee = Decimal('0.00')

        for inst in installments:
            remaining = max(Decimal('0.00'), inst.amount_due - inst.paid_amount)
            penalty_start = get_first_day_of_next_month(inst.due_date)
            applied_late_fee = inst.late_fee if today >= penalty_start else Decimal('0.00')

            if today >= inst.due_date and (remaining > 0 or applied_late_fee > 0):
                total_inst_due += remaining
                total_late_fee += applied_late_fee

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

        total_obligation = max(Decimal('0.00'), (total_fees + old_debt + total_late_fee) - total_paid)

        return JsonResponse({
            'status': 'success',
            'student_name': student.get_full_name(),
            'installments': installments_data,
            'total_fees': float(total_fees),
            'old_debt': float(old_debt),
            'total_paid': float(total_paid),
            'total_late_fee': float(total_late_fee),
            'total_obligation': float(total_obligation)
        })

    if action == 'get_notes':
        student_id = request.GET.get('student_id')
        notes_list = []
        try:
            CallNoteModel = apps.get_model('finance', 'StudentCallNote')
            notes_qs = CallNoteModel.objects.filter(student_id=student_id).select_related('author')
            for n in notes_qs:
                author_name = n.author.get_full_name() or n.author.username if n.author else "موظف النظام"
                notes_list.append({
                    'author': author_name,
                    'time': timezone.localtime(n.created_at).strftime('%Y-%m-%d %I:%M %p'),
                    'text': n.note_text
                })
        except Exception:
            pass
        return JsonResponse({'status': 'success', 'notes': notes_list})

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

    search_q = request.GET.get('q', '').strip()
    grade_id = request.GET.get('grade_id', '')
    specialization = request.GET.get('specialization', '')

    base_students = Student.objects.filter(is_active=True).select_related('grade')

    if grade_id:
        base_students = base_students.filter(grade_id=grade_id)
    if specialization:
        base_students = base_students.filter(specialization=specialization)

    if search_q:
        words = search_q.split()
        for w in words:
            q_cond = (
                Q(first_name__icontains=w) |
                Q(last_name__icontains=w) |
                Q(student_code__icontains=w) |
                Q(national_id__icontains=w) |
                Q(phone__icontains=w) |
                Q(whatsapp_number__icontains=w)
            )
            if hasattr(Student, 'parent_phone'):
                q_cond |= Q(parent_phone__icontains=w)
            if hasattr(Student, 'guardian_phone'):
                q_cond |= Q(guardian_phone__icontains=w)
            base_students = base_students.filter(q_cond)

    students_map = {}

    students_with_old_debts = base_students.filter(previous_debt__gt=0)
    for st in students_with_old_debts:
        old_d = st.previous_debt or Decimal('0.00')
        phone = getattr(st, 'parent_phone', None) or getattr(st, 'guardian_phone', None) or getattr(st, 'phone', '---')
        whatsapp = getattr(st, 'whatsapp_number', None) or phone

        latest_note = "لا يوجد اتصال سابق"
        n_count = 0
        try:
            CallNoteModel = apps.get_model('finance', 'StudentCallNote')
            n_qs = CallNoteModel.objects.filter(student=st)
            n_count = n_qs.count()
            last_obj = n_qs.first()
            if last_obj:
                latest_note = last_obj.note_text
        except Exception:
            pass

        students_map[st.id] = {
            'id': st.id,
            'full_name': st.get_full_name(),
            'student_code': getattr(st, 'student_code', '---'),
            'grade': st.grade.name if st.grade else 'غير محدد',
            'specialization': st.get_specialization_display() if st.specialization else 'شعبة عامة',
            'phone': phone,
            'whatsapp_number': whatsapp,
            'overdue_count': 1,
            'total_required': old_d,
            'notes_count': n_count,
            'latest_note': latest_note
        }

    inst_query = Q(due_date__lte=today) & Q(paid_amount__lt=F('amount_due')) & Q(student__in=base_students)
    overdue_installments = StudentInstallment.objects.filter(inst_query).select_related('student', 'student__grade')

    for inst in overdue_installments:
        st = inst.student
        inst_remaining = max(Decimal('0.00'), inst.amount_due - inst.paid_amount)
        penalty_start = get_first_day_of_next_month(inst.due_date)
        applied_late_fee = inst.late_fee if today >= penalty_start else Decimal('0.00')

        if inst_remaining <= 0 and applied_late_fee <= 0:
            continue

        phone = getattr(st, 'parent_phone', None) or getattr(st, 'guardian_phone', None) or getattr(st, 'phone', '---')
        whatsapp = getattr(st, 'whatsapp_number', None) or phone

        if st.id not in students_map:
            latest_note = "لا يوجد اتصال سابق"
            n_count = 0
            try:
                CallNoteModel = apps.get_model('finance', 'StudentCallNote')
                n_qs = CallNoteModel.objects.filter(student=st)
                n_count = n_qs.count()
                last_obj = n_qs.first()
                if last_obj:
                    latest_note = last_obj.note_text
            except Exception:
                pass

            students_map[st.id] = {
                'id': st.id,
                'full_name': st.get_full_name(),
                'student_code': getattr(st, 'student_code', '---'),
                'grade': st.grade.name if st.grade else 'غير محدد',
                'specialization': st.get_specialization_display() if st.specialization else 'شعبة عامة',
                'phone': phone,
                'whatsapp_number': whatsapp,
                'overdue_count': 0,
                'total_required': Decimal('0.00'),
                'notes_count': n_count,
                'latest_note': latest_note
            }

        students_map[st.id]['overdue_count'] += 1
        students_map[st.id]['total_required'] += (inst_remaining + applied_late_fee)

    all_cases = [s for s in students_map.values() if s['total_required'] > 0]

    paginator = Paginator(all_cases, 20)
    page_number = request.GET.get('page', 1)
    students_page = paginator.get_page(page_number)

    context = {
        'today': today,
        'students_list': students_page,
        'total_cases_count': len(all_cases),
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

if 'def overdue_installments_list' in content:
    content = re.sub(r'def overdue_installments_list\(request\):[\s\S]*?(?=\n\nclass |\n\ndef |\Z)', '', content)

content += '\n\n' + view_code
with open('students/views.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Updated students/views.py successfully")
