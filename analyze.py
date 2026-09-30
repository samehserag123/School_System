from hr.models import Employee, DailyAttendance, MissionRequest

employee = Employee.objects.filter(name__icontains="إيمان سعد").first()

if not employee:
    print("❌ لم يتم العثور على الموظفة، يرجى التأكد من الاسم.")
else:
    print(f"=== 👤 تحليل بيانات الموظف: {employee.name} (كود: {employee.emp_id}) ===")
    print()

    missions = MissionRequest.objects.filter(employee=employee).order_by('-start_date')
    print("📋 [1] سجل المأموريات الخارجية:")
    if not missions.exists():
        print("   لا توجد مأموريات مسجلة.")
    for m in missions:
        print(f"   - المعرف (ID: {m.id}): من {m.start_date} إلى {m.end_date} | الحالة: {m.status} | السبب: {m.reason}")
    print("\n" + "="*60 + "\n")

    absent_records = DailyAttendance.objects.filter(
        employee=employee,
        status__in=['absent', 'mission']
    ).order_by('-date')

    print("📊 [2] سجلات الحضور (الغياب والمأموريات والجزاءات):")
    for att in absent_records:
        print(f"   - التاريخ: {att.date} | الحالة: {att.status} | حضور: {att.check_in or '--:--'} | انصراف: {att.check_out or '--:--'} | الجزاءات: {att.administrative_penalty_days} يوم")
    print("\n" + "="*60 + "\n")

    print("🔍 [3] نتيجة تحليل التعارضات:")
    approved_missions = MissionRequest.objects.filter(employee=employee, status='approved')
    conflicts_found = False

    for m in approved_missions:
        mismatched = DailyAttendance.objects.filter(
            employee=employee,
            date__range=[m.start_date, m.end_date]
        ).exclude(status='mission')

        for record in mismatched:
            conflicts_found = True
            print(f"   ⚠️ تعارض في يوم {record.date}: المأمورية معتمدة ولكن سجل الحضور مسجل بـ ({record.get_status_display()}) وجزاء ({record.administrative_penalty_days} يوم).")

    if not conflicts_found:
        print("   ✅ جميع المأموريات المعتمدة متطابقة تماماً مع سجل الحضور ولا توجد تعارضات.")

    # إصلاح تلقائي عند وجود تعارض
    if conflicts_found:
        print("\n🔄 جاري إعادة مزامنة وتعديل سجل الحضور وتعديل الجزاءات تلقائياً...")
        for mission in approved_missions:
            mission.save()
        print("✨ تم التحديث بنجاح وتصحيح أيام المأموريات وإلغاء الجزاءات!")
