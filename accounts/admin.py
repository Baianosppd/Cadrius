from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Organization, OrganizationMembership

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
    list_display = ('name', 'cnpj', 'allowed_domain', 'is_active', 'created_at')
    search_fields = ('name', 'cnpj', 'allowed_domain')
    list_filter = ('is_active',)
    inlines = [OrganizationMembershipInline] # Liga a tabela intermediária aqui!

# =====================================================================
# 3. ADMIN DO UTILIZADOR CUSTOMIZADO
# =====================================================================
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    
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