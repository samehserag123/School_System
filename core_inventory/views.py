from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError
# أضف هذه الموديلات إلى سطر الاستيرادات في الأعلى
from .models import Supplier, PurchaseInvoice, PurchaseInvoiceItem

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST

@login_required
@require_POST
def ajax_add_supplier(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()

        if not name:
            return JsonResponse({'success': False, 'error': 'اسم المورد مطلوب'})

        supplier = Supplier.objects.create(name=name, phone=phone)
        return JsonResponse({
            'success': True,
            'supplier': {'id': supplier.id, 'name': supplier.name}
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# استيراد كافة الجداول من Models
from .models import (
    Warehouse, ItemCategory, ItemMaster,
    StockTransaction, StockBalance,
    UnitOfMeasure, ItemUnitConversion
)

from django.db import transaction
from decimal import Decimal

from core_inventory.models import ItemMaster, Warehouse, StockTransaction, StockBalance
import json

from finance.models import AcademicYear
from students.models import Grade


@login_required
def admin_add_restock(request):
    """
    شاشة فواتير المشتريات (تسميع فوري في المخزن وحساب المورد)
    تدعم التاريخ المخصص، الصف الدراسي الاختياري، ومعالجة أداء الاستعلامات (Bulk Operations)
    """
    from decimal import Decimal
    from django.db import transaction
    from django.db.models import F
    from django.utils import timezone
    from django.shortcuts import get_object_or_404, redirect, render
    from django.contrib import messages
    import json

    from .models import Supplier, PurchaseInvoice, PurchaseInvoiceItem, ItemMaster, Warehouse, StockTransaction
    from finance.models import AcademicYear

    # جلب موديل الصف الدراسي ديناميكياً من حقل الربط في ItemMaster
    GradeModel = ItemMaster._meta.get_field('linked_grade').remote_field.model

    if request.method == 'POST':
        supplier_id = request.POST.get('supplier_id')
        warehouse_id = request.POST.get('warehouse_id')
        invoice_number = request.POST.get('invoice_number', '').strip()
        invoice_date = request.POST.get('invoice_date') or timezone.now().date()
        notes = request.POST.get('note', '').strip()

        # استلام المصفوفات من جدول الفاتورة
        item_ids = request.POST.getlist('item_id[]')
        grade_ids = request.POST.getlist('grade_id[]')
        quantities = request.POST.getlist('quantity[]')
        prices = request.POST.getlist('price[]')

        # 1. فحص سلامة الكميات ومنع حفظ فاتورة فارغة
        has_valid_items = False
        for q in quantities:
            try:
                if q and Decimal(q) > 0:
                    has_valid_items = True
                    break
            except Exception:
                continue

        if not has_valid_items:
            messages.error(request, "🛑 يرجى إدخال صنف وكمية واحدة على الأقل أكبر من الصفر!")
            return redirect('admin_add_restock')

        try:
            with transaction.atomic():
                supplier = get_object_or_404(Supplier, id=supplier_id) if supplier_id else None
                warehouse = get_object_or_404(Warehouse, id=warehouse_id)

                if not invoice_number:
                    invoice_number = f"INV-{timezone.now().strftime('%Y%m%d%H%M%S')}"

                # إنشاء رأس الفاتورة
                invoice = PurchaseInvoice.objects.create(
                    invoice_number=invoice_number,
                    supplier=supplier,
                    warehouse=warehouse,
                    date=invoice_date,
                    notes=notes,
                    status='approved',
                    created_by=request.user
                )

                total_invoice_amount = Decimal('0.00')
                sup_label = supplier.name if supplier else "شراء نقدي / عام"

                # جلب جميع الأصناف المطلوبة دفعة واحدة لمنع استعلامات N+1
                valid_item_ids = [int(i) for i in item_ids if i and str(i).isdigit()]
                items_dict = ItemMaster.objects.in_bulk(valid_item_ids)

                invoice_items_to_create = []
                stock_txs_to_create = []
                items_to_update_grade = []

                # محاذاة البيانات المرسلة مع حقل الصف الدراسي
                zipped_data = zip(
                    item_ids,
                    quantities,
                    prices,
                    grade_ids + [''] * (len(item_ids) - len(grade_ids))
                )

                for item_id_str, qty_str, price_str, grade_id_str in zipped_data:
                    try:
                        qty = Decimal(qty_str or '0')
                        price = Decimal(price_str or '0')
                    except Exception:
                        continue

                    if qty <= 0:
                        continue

                    item_id = int(item_id_str) if item_id_str and item_id_str.isdigit() else None
                    item = items_dict.get(item_id) if item_id else None

                    if not item:
                        continue

                    # تحديث/ربط الصف الدراسي بالصنف عند اختياره في الجدول
                    if grade_id_str and str(grade_id_str).isdigit():
                        g_id = int(grade_id_str)
                        if item.linked_grade_id != g_id:
                            item.linked_grade_id = g_id
                            items_to_update_grade.append(item)

                    line_total = qty * price
                    total_invoice_amount += line_total

                    # تجهيز الكائنات للـ Bulk Insert
                    invoice_items_to_create.append(
                        PurchaseInvoiceItem(
                            invoice=invoice,
                            item=item,
                            quantity=qty,
                            unit_price=price,
                            total_price=line_total
                        )
                    )

                    stock_txs_to_create.append(
                        StockTransaction(
                            item=item,
                            warehouse=warehouse,
                            movement_type='IN_PURCHASE',
                            quantity=qty,
                            notes=f"فاتورة مشتريات رقم {invoice.invoice_number} - جهة التوريد: {sup_label}",
                            created_by=request.user
                        )
                    )

                # تنفيذ التحديثات والإدراج المجمّع لخادم قاعدة البيانات
                if items_to_update_grade:
                    ItemMaster.objects.bulk_update(items_to_update_grade, ['linked_grade'])

                if invoice_items_to_create:
                    PurchaseInvoiceItem.objects.bulk_create(invoice_items_to_create)

                if stock_txs_to_create:
                    StockTransaction.objects.bulk_create(stock_txs_to_create)

                # تحديث إجمالي الفاتورة
                invoice.total_amount = total_invoice_amount
                invoice.net_amount = total_invoice_amount
                invoice.save(update_fields=['total_amount', 'net_amount'])

                # تسميع رصيد المورد بـ F Expression لتسريع الأداء ومنع Race Conditions
                if supplier:
                    Supplier.objects.filter(id=supplier.id).update(
                        current_balance=F('current_balance') + total_invoice_amount
                    )
                    messages.success(request, f"✅ تم حفظ الفاتورة بنجاح. تمت إضافة الصافي ({total_invoice_amount} ج.م) لحساب المورد [{supplier.name}] وتحديث الأرصدة المخزنية.")
                else:
                    messages.success(request, f"✅ تم حفظ الفاتورة النقدية بنجاح بإجمالي ({total_invoice_amount} ج.م) وتحديث الأرصدة المخزنية.")

        except Exception as e:
            messages.error(request, f"❌ حدث خطأ أثناء الحفظ: {str(e)}")

        return redirect('admin_add_restock')

    # === GET Request ===
    warehouses = Warehouse.objects.filter(is_active=True).only('id', 'name')
    suppliers = Supplier.objects.filter(is_active=True).only('id', 'name')
    grades = GradeModel.objects.all().only('id', 'name')

    try:
        active_year = AcademicYear.objects.filter(is_active=True).first()
    except Exception:
        active_year = None

    raw_items = list(ItemMaster.objects.values('id', 'name', 'sku', 'item_type').order_by('name'))
    items_json = json.dumps(raw_items)

    recent_invoices = PurchaseInvoice.objects.select_related('supplier', 'warehouse').order_by('-date', '-id')[:15]

    context = {
        'warehouses': warehouses,
        'suppliers': suppliers,
        'grades': grades,
        'active_year': active_year,
        'items_json': items_json,
        'recent_invoices': recent_invoices,
        'title': 'تسجيل فواتير المشتريات (ERP)',
    }
    return render(request, 'add_restock.html', context)

# @login_required
# def admin_add_restock(request):
#     """
#     شاشة فواتير المشتريات (تسميع فوري في المخزن وحساب المورد)
#     تدعم التاريخ المخصص وحساب المورد الاختياري وفحص سلامة المدخلات
#     """
#     from .models import Supplier, PurchaseInvoice, PurchaseInvoiceItem, ItemMaster, Warehouse, StockTransaction
#     from finance.models import AcademicYear
#     from decimal import Decimal
#     from django.db import transaction
#     from django.utils import timezone
#     import json

#     if request.method == 'POST':
#         supplier_id = request.POST.get('supplier_id')
#         warehouse_id = request.POST.get('warehouse_id')
#         invoice_number = request.POST.get('invoice_number', '').strip()
#         invoice_date = request.POST.get('invoice_date') or timezone.now().date()
#         notes = request.POST.get('note', '').strip()

#         # استلام البيانات من جدول الفاتورة (مصفوفات الأصناف والأسعار)
#         item_ids = request.POST.getlist('item_id[]')
#         quantities = request.POST.getlist('quantity[]')
#         prices = request.POST.getlist('price[]')

#         # 1. فحص سلامة الكميات ومنع حفظ فاتورة فارغة
#         has_valid_items = False
#         for q in quantities:
#             try:
#                 if q and Decimal(q) > 0:
#                     has_valid_items = True
#                     break
#             except Exception:
#                 continue

#         if not has_valid_items:
#             messages.error(request, "🛑 يرجى إدخال صنف وكمية واحدة على الأقل أكبر من الصفر!")
#             return redirect('admin_add_restock')

#         try:
#             with transaction.atomic():
#                 # المورد اختياري: جلبه إن وجد أو تركه None للشراء النقدي
#                 supplier = get_object_or_404(Supplier, id=supplier_id) if supplier_id else None
#                 warehouse = get_object_or_404(Warehouse, id=warehouse_id)

#                 # توليد رقم فاتورة تلقائي إذا تُرك الحقل فارغاً
#                 if not invoice_number:
#                     invoice_number = f"INV-{timezone.now().strftime('%Y%m%d%H%M%S')}"

#                 # 2. إنشاء رأس الفاتورة بالتاريخ المحدد
#                 invoice = PurchaseInvoice.objects.create(
#                     invoice_number=invoice_number,
#                     supplier=supplier,
#                     warehouse=warehouse,
#                     date=invoice_date,
#                     notes=notes,
#                     status='approved',
#                     created_by=request.user
#                 )

#                 total_invoice_amount = Decimal('0.00')
#                 sup_label = supplier.name if supplier else "شراء نقدي / عام"

#                 # 3. إضافة الأصناف وتسميع المخزن
#                 for item_id, qty_str, price_str in zip(item_ids, quantities, prices):
#                     try:
#                         qty = Decimal(qty_str or '0')
#                         price = Decimal(price_str or '0')
#                     except Exception:
#                         continue

#                     if qty <= 0:
#                         continue

#                     item = get_object_or_404(ItemMaster, id=item_id)
#                     line_total = qty * price
#                     total_invoice_amount += line_total

#                     # تسجيل صنف الفاتورة
#                     PurchaseInvoiceItem.objects.create(
#                         invoice=invoice,
#                         item=item,
#                         quantity=qty,
#                         unit_price=price,
#                         total_price=line_total
#                     )

#                     # حركة المخزن التلقائية
#                     StockTransaction.objects.create(
#                         item=item,
#                         warehouse=warehouse,
#                         movement_type='IN_PURCHASE',
#                         quantity=qty,
#                         notes=f"فاتورة مشتريات رقم {invoice.invoice_number} - جهة التوريد: {sup_label}",
#                         created_by=request.user
#                     )

#                 # 4. تحديث إجمالي الفاتورة
#                 invoice.total_amount = total_invoice_amount
#                 invoice.net_amount = total_invoice_amount
#                 invoice.save()

#                 # 5. تسميع رصيد المورد (فقط في حال تم تحديد مورد)
#                 if supplier:
#                     supplier.current_balance += total_invoice_amount
#                     supplier.save()
#                     messages.success(request, f"✅ تم حفظ الفاتورة بنجاح. تمت إضافة الصافي ({total_invoice_amount} ج.م) لحساب المورد [{supplier.name}] وتحديث الأرصدة المخزنية.")
#                 else:
#                     messages.success(request, f"✅ تم حفظ الفاتورة النقدية بنجاح بإجمالي ({total_invoice_amount} ج.م) وتحديث الأرصدة المخزنية.")

#         except Exception as e:
#             messages.error(request, f"❌ حدث خطأ أثناء الحفظ: {str(e)}")

#         return redirect('admin_add_restock')

#     # === GET Request ===
#     warehouses = Warehouse.objects.filter(is_active=True).only('id', 'name')
#     suppliers = Supplier.objects.filter(is_active=True).only('id', 'name')

#     try:
#         active_year = AcademicYear.objects.filter(is_active=True).first()
#     except Exception:
#         active_year = None

#     raw_items = list(ItemMaster.objects.values('id', 'name', 'sku', 'item_type').order_by('name'))
#     items_json = json.dumps(raw_items)

#     recent_invoices = PurchaseInvoice.objects.select_related('supplier', 'warehouse').order_by('-date', '-id')[:15]

#     context = {
#         'warehouses': warehouses,
#         'suppliers': suppliers,
#         'active_year': active_year,
#         'items_json': items_json,
#         'recent_invoices': recent_invoices,
#         'title': 'تسجيل فواتير المشتريات (ERP)',
#     }
#     return render(request, 'add_restock.html', context)


@login_required
def manual_stock_transaction(request):
    """شاشة موحدة لعمليات المخزن اليدوية (إضافة رصيد / صرف للأقسام والمطبخ)"""
    warehouses = Warehouse.objects.filter(is_active=True)
    items = ItemMaster.objects.all().order_by('name')

    if request.method == 'POST':
        movement_type = request.POST.get('movement_type')
        warehouse_id = request.POST.get('warehouse')
        item_id = request.POST.get('item')
        quantity_str = request.POST.get('quantity', '0')
        department = request.POST.get('department', '')
        notes = request.POST.get('notes', '')

        try:
            quantity = Decimal(quantity_str)
            if quantity <= 0:
                messages.error(request, "🛑 الكمية يجب أن تكون أكبر من الصفر.")
                return redirect('manual_stock_transaction')

            warehouse = get_object_or_404(Warehouse, id=warehouse_id)
            item = get_object_or_404(ItemMaster, id=item_id)

            StockTransaction.objects.create(
                movement_type=movement_type,
                item=item,
                warehouse=warehouse,
                quantity=quantity,
                department=department,
                notes=notes,
                created_by=request.user
            )

            if movement_type.startswith('IN'):
                messages.success(request, f"✅ تم توريد ({quantity} {item.get_unit_of_measure_display()}) من [{item.name}] إلى {warehouse.name} بنجاح.")
            else:
                messages.success(request, f"✅ تم صرف ({quantity} {item.get_unit_of_measure_display()}) من [{item.name}] لقسم ({department}) بنجاح.")

        except ValidationError as ve:
            messages.error(request, ve.message if hasattr(ve, 'message') else str(ve))
        except Exception as e:
            messages.error(request, f"❌ حدث خطأ أثناء الحفظ: {str(e)}")

        return redirect('manual_stock_transaction')

    recent_transactions = StockTransaction.objects.select_related(
        'item', 'warehouse', 'created_by'
    ).order_by('-date')[:30]

    context = {
        'warehouses': warehouses,
        'items': items,
        'recent_transactions': recent_transactions,
        'title': 'حركات المخزن اليدوية'
    }
    return render(request, 'core_inventory/manual_transaction.html', context)



@login_required
def material_control_settings(request):
    """لوحة تحكم الإعدادات التأسيسية للمخازن (MC Settings)"""
    warehouses = Warehouse.objects.all()
    categories = ItemCategory.objects.all()
    units = UnitOfMeasure.objects.all()

    # 🟢 إضافة select_related('unit_of_measure') لتقليل عدد استعلامات قاعدة البيانات عند عرض الوحدة في الجدول
    items = ItemMaster.objects.select_related('category', 'unit_of_measure').all().order_by('-id')
    conversions = ItemUnitConversion.objects.select_related('item', 'from_unit', 'to_unit').all()

    if request.method == 'POST':
        action = request.POST.get('action')

        try:
            if action == 'add_warehouse':
                Warehouse.objects.create(
                    name=request.POST.get('name'),
                    location=request.POST.get('location')
                )
                messages.success(request, "✅ تم إضافة المستودع بنجاح.")

            elif action == 'add_unit':
                UnitOfMeasure.objects.create(
                    name=request.POST.get('name'),
                    symbol=request.POST.get('symbol')
                )
                messages.success(request, "✅ تم إضافة وحدة القياس بنجاح.")

            # 🟢 التحديث الجديد: استقبال معرف وحدة القياس (unit_of_measure_id) ديناميكياً
            elif action == 'add_item':
                unit_id = request.POST.get('unit_of_measure')
                ItemMaster.objects.create(
                    sku=request.POST.get('sku'),
                    name=request.POST.get('name'),
                    category_id=request.POST.get('category_id'),
                    item_type=request.POST.get('item_type'),
                    unit_of_measure_id=unit_id if unit_id else None
                )
                messages.success(request, "✅ تم تكويد الصنف بنجاح.")

            elif action == 'add_conversion':
                ItemUnitConversion.objects.create(
                    item_id=request.POST.get('item_id'),
                    from_unit_id=request.POST.get('from_unit_id'),
                    to_unit_id=request.POST.get('to_unit_id'),
                    conversion_rate=Decimal(request.POST.get('conversion_rate'))
                )
                messages.success(request, "✅ تم اعتماد معامل التحويل بنجاح.")

        except Exception as e:
            messages.error(request, f"❌ حدث خطأ: {str(e)}")

        return redirect('material_control_settings')

    context = {
        'warehouses': warehouses,
        'categories': categories,
        'units': units,
        'items': items,
        'conversions': conversions,
        'title': 'إعدادات الماتيريال كنترول (MC Settings)'
    }
    return render(request, 'core_inventory/mc_settings.html', context)

# @login_required
# def material_control_settings(request):
#     """لوحة تحكم الإعدادات التأسيسية للمخازن (MC Settings)"""
#     warehouses = Warehouse.objects.all()
#     categories = ItemCategory.objects.all()
#     units = UnitOfMeasure.objects.all()
#     items = ItemMaster.objects.select_related('category').all().order_by('-id')
#     conversions = ItemUnitConversion.objects.select_related('item', 'from_unit', 'to_unit').all()

#     if request.method == 'POST':
#         action = request.POST.get('action')

#         try:
#             if action == 'add_warehouse':
#                 Warehouse.objects.create(
#                     name=request.POST.get('name'),
#                     location=request.POST.get('location')
#                 )
#                 messages.success(request, "✅ تم إضافة المستودع بنجاح.")

#             elif action == 'add_unit':
#                 UnitOfMeasure.objects.create(
#                     name=request.POST.get('name'),
#                     symbol=request.POST.get('symbol')
#                 )
#                 messages.success(request, "✅ تم إضافة وحدة القياس بنجاح.")

#             # 🟢 التحديث الجديد: إضافة تكويد الأصناف
#             elif action == 'add_item':
#                 ItemMaster.objects.create(
#                     sku=request.POST.get('sku'),
#                     name=request.POST.get('name'),
#                     category_id=request.POST.get('category_id'),
#                     item_type=request.POST.get('item_type'),
#                     unit_of_measure=request.POST.get('unit_of_measure', 'piece')
#                 )
#                 messages.success(request, "✅ تم تكويد الصنف بنجاح.")

#             elif action == 'add_conversion':
#                 ItemUnitConversion.objects.create(
#                     item_id=request.POST.get('item_id'),
#                     from_unit_id=request.POST.get('from_unit_id'),
#                     to_unit_id=request.POST.get('to_unit_id'),
#                     conversion_rate=Decimal(request.POST.get('conversion_rate'))
#                 )
#                 messages.success(request, "✅ تم اعتماد معامل التحويل بنجاح.")

#         except Exception as e:
#             messages.error(request, f"❌ حدث خطأ: {str(e)}")

#         return redirect('material_control_settings')

#     context = {
#         'warehouses': warehouses,
#         'categories': categories,
#         'units': units,
#         'items': items,
#         'conversions': conversions,
#         'title': 'إعدادات الماتيريال كنترول (MC Settings)'
#     }
#     return render(request, 'core_inventory/mc_settings.html', context)





purchase_invoice_create = admin_add_restock
