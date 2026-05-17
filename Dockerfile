# اختيار نسخة بايثون 3.12 (متوافقة مع Django 5.1+ و Django 6)
FROM python:3.12-slim

# إعدادات لضمان ظهور رسائل الخطأ فوراً وسرعة التشغيل
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# تثبيت الأدوات اللازمة للنظام (PostgreSQL, Pillow, ReportLab, Celery)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    python3-dev \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff5-dev \
    tk-dev \
    tcl-dev \
    && rm -rf /var/lib/apt/lists/*

# تحديث أداة pip قبل البدء
RUN pip install --upgrade pip

# تثبيت المكتبات من الملف
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كل ملفات مشروعك داخل الحاوية
COPY . /app/
# تشغيل gunicorn باستخدام مجلد الإعدادات الصحيح
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "config.wsgi:application"]