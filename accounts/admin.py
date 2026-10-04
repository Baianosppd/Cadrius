from django import forms
from core.utils import EncryptedTextField
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Organization, OrganizationMembership, UserMessageSendCount

# =====================================================================
# 1. INLINES (Para mostrar os vínculos dentro da página principal)
# =====================================================================
class OrganizationMembershipInline(admin.TabularInline):
    """
    Mostra os membros dentro da página da Organização, 
    ou as Organizações dentro da página do Utilizador.
    """
    model = OrganizationMembership
    extra = 1 # Linhas em branco extra para adicionar novos rapidamente
    autocomplete_fields = ['user', 'organization'] # Melhora a performance se houver muitos dados

# =====================================================================
# 2. ADMIN DA ORGANIZAÇÃO
# =====================================================================
@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'cnpj', 'plan', 'is_active', 'created_at')
    list_filter = ('account_type', 'company_size', 'is_active')
    formfield_overrides = {EncryptedTextField: {'widget': forms.TextInput}}
    search_fields = ('name', 'allowed_domain')   # CNPJ é cifrado: busca exata por get_search_results abaixo

    def get_search_results(self, request, queryset, search_term):
        qs, distinct = super().get_search_results(request, queryset, search_term)
        from core.pii import blind_index
        digits = blind_index('org.cnpj', search_term)
        return (qs | queryset.filter(cnpj_bidx=digits)) if digits else qs, distinct
    list_filter = ('is_active',)
    inlines = [OrganizationMembershipInline] # Liga a tabela intermediária aqui!

# =====================================================================
# 3. ADMIN DO UTILIZADOR CUSTOMIZADO
# =====================================================================
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')
    search_fields = ('username', 'email')   # nome/CPF são cifrados: busca por índice em get_search_results
    formfield_overrides = {EncryptedTextField: {'widget': forms.TextInput}}

    def get_search_results(self, request, queryset, search_term):
        qs, distinct = super().get_search_results(request, queryset, search_term)
        from core.pii import blind_index, filter_by_term
        extra = filter_by_term(queryset, 'name_idx', 'user.name', search_term) if search_term.strip() else queryset.none()
        cpf = blind_index('user.cpf', search_term)
        if cpf:
            extra = extra | queryset.filter(cpf_bidx=cpf)
        return qs | extra, distinct
    
    # Removemos qualquer referência ao antigo campo 'organization'
    # e usamos o Inline para mostrar a quais escritórios ele pertence
    inlines = [OrganizationMembershipInline]

    # Adiciona o campo 'phone' que criámos no modelo novo
    fieldsets = UserAdmin.fieldsets + (
        ('Informações Adicionais (B2B)', {'fields': ('phone',)}),
    )

# =====================================================================
# 4. ADMIN DO VÍNCULO (Opcional, mas útil para gestão)
# =====================================================================
@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'is_active', 'joined_at')
    list_filter = ('role', 'is_active', 'organization')
    search_fields = ('user__email', 'user__username', 'organization__name')

@admin.register(UserMessageSendCount)
class UserMessageSendCountAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'whatsapp_count',
        'email_count',
        'automations_run_count',
        'document_analysis_count',
    )
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('user',)