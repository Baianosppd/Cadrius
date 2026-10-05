from django.contrib import admin

from automations.models import Rule


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'trigger', 'enabled', 'run_count', 'last_run_at')
    list_filter = ('trigger', 'enabled')
    readonly_fields = ('simulated_hash', 'run_count', 'last_run_at')
