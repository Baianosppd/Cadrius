from django.utils.deprecation import MiddlewareMixin

class TenantMiddleware(MiddlewareMixin):
    """
    Middleware Multi-Tenant atualizado para a nova arquitetura de Memberships.
    """
    def process_request(self, request):
        # 1. Se não estiver logado, não há tenant a isolar
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            request.tenant = None
            return None

        # 2. NÃO aplicamos bloqueio Multi-Tenant nas páginas do Admin do Django.
        # O Superadmin precisa de ter visão global de todos os dados.
        if request.path.startswith('/admin/'):
            request.tenant = None
            return None

        # 3. Lógica B2B: Se for uma requisição da API ou Front-end
        # Procuramos o primeiro escritório em que este utilizador tem vínculo ativo
        membership = request.user.memberships.filter(is_active=True).first()
        
        if membership:
            request.tenant = membership.organization
        else:
            request.tenant = None