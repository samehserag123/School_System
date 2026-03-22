from django.urls import path
from .views import add_student, student_list
from . import views
urlpatterns = [
    path('promote/<int:student_id>/', views.promote_student, name='promote_student'),
    path('', student_list, name='student_list'),
    path('add/', add_student, name='add_student'),
    path('ajax/load-classrooms/', views.get_classrooms, name='ajax_load_classrooms'),
    path('debt-history/<int:student_id>/', views.debt_history, name='debt_history'),
    path('course-prices/', views.course_prices_view, name='course_prices'),
    path('collect-fee/<int:enrollment_id>/', views.collect_course_fee_view, name='collect_fee'),
    
]
