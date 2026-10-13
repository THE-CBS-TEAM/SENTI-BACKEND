from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from apps.accounts.models import User, Workspace, Brand


class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'username', 'role', 'is_staff', 'created_at')
    list_filter = ('role', 'is_staff', 'is_superuser')
    fieldsets = UserAdmin.fieldsets + (
        ('Custom Fields', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Custom Fields', {'fields': ('role', 'email')}),
    )


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'owner', 'created_at')
    list_filter = ('type',)
    search_fields = ('name', 'owner__email')


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'created_at')
    search_fields = ('name', 'workspace__name')


admin.site.register(User, CustomUserAdmin)
