from django.contrib import admin
from .models import Workflow, Trigger, Action

class ActionInline(admin.TabularInline):
    model = Action
    extra = 1

class TriggerInline(admin.StackedInline):
    model = Trigger
    can_delete = False

@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    inlines = [TriggerInline, ActionInline]