from django.contrib import admin
from .models import (
    Warehouse, ItemCategory, ItemMaster,
    StockTransaction, StockBalance,
    Supplier, PurchaseInvoice, PurchaseInvoiceItem,
    UnitOfMeasure, ItemUnitConversion
)

# ==========================================
# 1. إعدادات المخازن والتصنيفات
# ==========================================
@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)

@admin.register(ItemCategory)
class ItemCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent')
    search_fields = ('name',)

@admin.register(ItemMaster)
class ItemMasterAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'category', 'item_type', 'unit_of_measure', 'tracking_type')
    list_filter = ('item_type', 'category', 'tracking_type')
    search_fields = ('sku', 'name')
    list_select_related = ('category',)  # تسريع الاستعلام بمنع N+1

# ==========================================
# 2. حركات المخزون والأرصدة الحية
# ==========================================
@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_code', 'item', 'warehouse', 'movement_type', 'quantity', 'date', 'created_by')
    list_filter = ('movement_type', 'warehouse', 'date')
    search_fields = ('transaction_code', 'item__name', 'item__sku')
    readonly_fields = ('transaction_code',)
    list_select_related = ('item', 'warehouse', 'created_by')  # أداء فائق في العرض

@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = ('item', 'warehouse', 'quantity_on_hand')
    list_filter = ('warehouse',)
    search_fields = ('item__name', 'item__sku')
    readonly_fields = ('item', 'warehouse', 'quantity_on_hand')
    list_select_related = ('item', 'warehouse')

# ==========================================
# 3. إدارة الموردين
# ==========================================
@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'current_balance', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'phone')
    readonly_fields = ('created_at',)

# ==========================================
# 4. إدارة فواتير المشتريات وتفاصيل الأصناف (Inline)
# ==========================================
class PurchaseInvoiceItemInline(admin.TabularInline):
    model = PurchaseInvoiceItem
    extra = 1
    fields = ('item', 'quantity', 'unit_price', 'total_price')
    readonly_fields = ('total_price',)
    autocomplete_fields = ('item',)  # بحث سريع بدلاً من تحميل قائمة آلاف الأصناف

@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'supplier', 'warehouse', 'date', 'net_amount', 'status', 'created_by')
    list_filter = ('status', 'warehouse', 'date')
    search_fields = ('invoice_number', 'supplier__name')
    list_select_related = ('supplier', 'warehouse', 'created_by')
    inlines = [PurchaseInvoiceItemInline]
    readonly_fields = ('created_at', 'net_amount')

# ==========================================
# 5. وحدات القياس والتحويلات
# ==========================================
@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ('name', 'symbol')
    search_fields = ('name',)

@admin.register(ItemUnitConversion)
class ItemUnitConversionAdmin(admin.ModelAdmin):
    list_display = ('item', 'from_unit', 'to_unit', 'conversion_rate')
    list_select_related = ('item', 'from_unit', 'to_unit')