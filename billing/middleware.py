from django.utils.deprecation import MiddlewareMixin
from .models import OrganizationMembership

class MultiTenantMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.user.is_authenticated:
            # Tenta encontrar a qual escritório o utilizador pertence
            membership = OrganizationMembership.objects.filter(user=request.user).first()
            if membership:
                request.organization = membership.organization
            else:
                request.organization = None
        else:
            request.organization = None