from django.urls import path
from . import views
from students.views import get_pending_sales_api

urlpatterns = [
    # =========================================================
    # 📑 1. السجلات وإدارة الطلاب الأساسية
    # =========================================================
    path('', views.student_list, name='student_list'),
    path('add/', views.add_student, name='add_student'),
    path('student/dashboard/<int:student_id>/', views.student_dashboard, name='student_dashboard'),
    path('students/registry/', views.student_registry_view, name='student_registry'),
    path('bulk-update-specialization/', views.bulk_update_specialization, name='bulk_update_specialization'),

    # =========================================================
    # ⏱️ 2. الحضور والغياب وإعادة القيد
    # =========================================================
    path('attendance/take/', views.take_daily_attendance_view, name='take_attendance'),
    path('attendance/re-enroll/', views.manage_reenrollments_view, name='manage_reenrollments'),
    path('attendance/report/', views.attendance_report_view, name='attendance_report'),

    # =========================================================
    # 🔒 3. أنظمة الحماية والماسح الذكي للأسوار والبوابة
    # =========================================================
    path('scanner/', views.security_scanner_view, name='security_scanner'),
    path('api/qr-attendance/', views.api_record_qr_attendance, name='api_record_qr_attendance'),
    path('students/gate-block/save/', views.save_student_gate_block, name='save_student_gate_block'),

    # =========================================================
    # 🟢 4. استخراج تقارير الـ PDF وكشوف الطباعة
    # =========================================================
    path('reports/class-roster/', views.report_class_roster_view, name='report_class_roster'),
    path('reports/student-registry/', views.report_student_registry_view, name='report_student_registry'),
    path('reports/dismissed-students/', views.report_dismissed_students_view, name='report_dismissed_students'),

    # =========================================================
    # 📝 5. الكنترول العام ورصد النتائج والدرجات
    # =========================================================
    path('exam/marks/record/', views.record_exam_marks_view, name='record_marks'),
    path('academic/report/final/', views.academic_final_report_view, name='academic_final_report_legacy'),

    # =========================================================
    # 💰 6. الخزنة، الأقساط، والمبيعات المالية
    # =========================================================
    path('overdue-calls/', views.overdue_installments_list, name='overdue_calls'),
    path('treasury/add/', views.add_ledger_entry, name='add_ledger_entry'),
    path('course-prices/', views.course_prices_view, name='course_prices'),
    path('mark-session/<int:enrollment_id>/', views.mark_session_attendance, name='mark_session_attendance'),
    path('session-history-api/<int:enrollment_id>/', views.session_history_api, name='session_history_api'),
    path('misc-revenue/', views.misc_revenue_view, name='misc_revenue'),
    path('sales/', views.book_sales_list, name='book_sales_list'),
    path('sales/add/', views.add_book_sale, name='add_book_sale'),
    path('sales/print/<int:sale_id>/', views.print_receipt_view, name='print_book_receipt'),
    path('api/financial-info/<int:student_id>/', views.student_financial_api, name='student_financial_api'),
    path('students/api/get-pending-sales/<int:student_id>/', views.get_pending_sales_api, name='get_pending_sales_api'),
    path('collect-fee/<int:enrollment_id>/', views.collect_fee_view, name='collect_fee'),
    path('api/today-sales/', views.api_today_book_sales, name='api_today_book_sales'),

    # =========================================================
    # 📊 7. شاشات الإحصاء والتحليل الأكاديمي
    # =========================================================
    path('student-analytics/<int:student_id>/', views.student_detail_analytics, name='student_analytics_detail'),
    path('analytics/<int:student_id>/', views.student_detail_analytics),
    path('students/analytics/<int:student_id>/', views.student_detail_analytics),
    path('students/analytics/', views.students_analytics_view, name='students_analytics'),

    # 🟢 مسار النافذة المنبثقة الذكية لتحليل الطالب السريع
    path('api/student-quick-analytics/<int:student_id>/', views.api_student_quick_analytics, name='api_student_quick_analytics'),
    path('students/api/student-quick-analytics/<int:student_id>/', views.api_student_quick_analytics),

    # =========================================================
    # 🚌 8. إدارة منظومة الحافلات والاشتراكات
    # =========================================================
    path('bus-dashboard/', views.bus_dashboard_view, name='bus_dashboard'),

    # =========================================================
    # 📦 9. إدارة المخازن والتسليم الذكي التفصيلي للمقررات
    # =========================================================
    path('inventory/report/', views.inventory_category_report, name='inventory_report'),
    path('admin/inventory/add-stock/', views.admin_add_restock, name='admin_add_restock'),
    path('api/search-students-sale/', views.api_search_students_for_sale, name='api_search_students_for_sale'),
    path('courses/api/search-students/', views.api_search_students_for_courses, name='api_search_students_for_courses'),
    path('sales/confirm-delivery/<int:sale_id>/', views.confirm_delivery_view, name='confirm_delivery_view'),
    path('sales/toggle-delivery/<int:sale_id>/', views.toggle_delivery_view, name='toggle_delivery_view'),

    # 🚀 مسارات الـ API للمودال التفاعلي والتسليم الجزئي للكتب مع ربط الجرد
    path('sales/api/delivery-details/<int:sale_id>/', views.api_get_sale_delivery_details, name='api_get_sale_delivery_details'),
    path('sales/api/save-delivery/<int:sale_id>/', views.api_save_partial_delivery, name='api_save_partial_delivery'),

    # =========================================================
    # 🎓 10. البرامج العلاجية ومجموعات التقوية
    # =========================================================
    path('remedial/add/', views.add_remedial_program, name='add_remedial_program'),
    path('remedial/dashboard/', views.manage_remedial_dashboard, name='remedial_dashboard'),
    path('remedial/save-quick/', views.save_remedial_from_registry, name='save_remedial_from_registry'),
    path('api/remedial/pay/<int:record_id>/', views.pay_remedial_record, name='pay_remedial_record'),
    path('api/remedial-balance/<int:student_id>/', views.get_remedial_balance_api, name='get_remedial_balance_api'),

    # =========================================================
    # 📱 11. كروت الهوية الذكية وحضور الـ QR Code
    # =========================================================
    path('student/card/<str:student_code>/', views.student_id_card_view, name='student_id_card'),
    path('security/scanner/', views.security_scanner_view, name='security_scanner_alt'),
    path('api/qr-attendance-alt/', views.api_record_qr_attendance, name='api_record_qr_attendance_alt'),

    # =========================================================
    # 🔄 12. مسارات AJAX للحركات اللحظية
    # =========================================================
    path('ajax/update-status/', views.update_single_status_ajax, name='ajax_update_status'),
    path('ajax/bulk-status/', views.bulk_update_academic_status_ajax, name='ajax_bulk_status'),
    path('api/teacher-courses/<int:teacher_id>/', views.get_teacher_courses_api, name='get_teacher_courses_api'),

    # =========================================================
    # 🎯 13. الكنترول الفرعي وأرقام الجلوس واللجان
    # =========================================================
    path('control/analytics/', views.academic_final_report_view, name='academic_final_report'),
    path('control/numbers/', views.control_numbers_dashboard_view, name='control_numbers_dashboard'),
    path('control/print-committees/', views.print_committees_roster_view, name='print_committees_roster'),
    path('control/manage-subjects/', views.manage_student_subjects_view, name='manage_student_subjects'),
    path('api/control/bulk-status/', views.ajax_bulk_status, name='api_control_bulk_status'),

    # =========================================================
    # 🏛️ 14. منظومة الأكاديمية والدبلومات والبرامج (14 شهر)
    # =========================================================
    path('academy/dashboard/', views.academy_dashboard_view, name='academy_dashboard'),
    path('academy/study-plan/', views.academy_study_plan_view, name='academy_study_plan'),
    path('academy/attendance/', views.academy_attendance_sheet_view, name='academy_attendance_sheet'),
    path('academy/api/student-details/<int:enrollment_id>/', views.api_academy_student_details, name='api_academy_student_details'),
    path('students/academy/api/student-details/<int:enrollment_id>/', views.api_academy_student_details),
    path('academy/api/check-enrollment/', views.api_check_academy_enrollment, name='api_check_academy_enrollment'),
    path('students/academy/api/check-enrollment/', views.api_check_academy_enrollment),
    path('academy/api/courses-for-term/', views.api_academy_courses_for_term, name='api_academy_courses_for_term'),
    path('academy/api/subjects-for-term-course/', views.api_academy_subjects_for_term_course, name='api_academy_subjects_for_term_course'),

    # =========================================================
    # 🌐 15. ربط القبول والتسجيل الإلكتروني الخارجي (Microservices & APIs)
    # =========================================================
    # شاشة إشعارات الطلبات المقبولة
    path('pending-admissions/', views.pending_admissions_list, name='pending_admissions_list'),
    path('students/pending-admissions/', views.pending_admissions_list),
    
    # 🔴 مسارات حذف إشعارات التقديم المرفوضة
    path('pending-admissions/delete/<int:pk>/', views.delete_pending_notification, name='delete_pending_notification'),
    path('pending-admissions/delete-all/', views.delete_all_pending_notifications, name='delete_all_pending_notifications'),

    # 🟢 مسارات API لاستقبال وتأكيد نقل بيانات الطلاب المقبولين من لوحة الموظف
    path('api/receive-approved-student/', views.api_receive_approved_student, name='api_receive_approved_student'),
    path('students/api/receive-approved-student/', views.api_receive_approved_student),

    # 🟢 مسارات API لاستقبال تقديمات الموقع المباشرة (تمنع خطأ 404 Not Found)
    path('api/online-admission/receive/', views.receive_online_admission, name='receive_online_admission'),
    path('students/api/online-admission/receive/', views.receive_online_admission),
]