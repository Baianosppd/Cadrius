from django.contrib import admin
from .models import ExtractionProfile

@admin.register(ExtractionProfile)
class ExtractionProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'pydantic_schema_name')
    list_filter = ('user', 'pydantic_schema_name')
    search_fields = ('name', 'system_prompt_template')