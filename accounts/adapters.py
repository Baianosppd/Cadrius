import logging
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from billing.models import Organization, OrganizationMembership

logger = logging.getLogger(__name__)

class B2BSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Adaptador que intercepta o momento exato em que o utilizador faz login 
    via Google ou Microsoft com sucesso.
    """
    def save_user(self, request, sociallogin, form=None):
       
        user = super().save_user(request, sociallogin, form)
        
        
        email = user.email
        
        if not email:
            return user
            
        
        domain = email.split('@')[-1].lower()
        
        # Domínios públicos ignorados (não criam organizações automáticas corporativas)
        public_domains = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com']
        
        if domain not in public_domains:
         
            try:
                org = Organization.objects.get(allowed_domain=domain)
                
                
                OrganizationMembership.objects.get_or_create(
                    user=user,
                    organization=org,
                    defaults={'role': 'MEMBER'}
                )
                logger.info(f"✅ B2B Login: Utilizador {email} auto-vinculado ao escritório {org.name}")
                
            except Organization.DoesNotExist:
                # O domínio é corporativo, mas a empresa ainda não pagou/não tem conta connosco.
                # Aqui poderias, por exemplo, suspender a conta até pagarem, ou criar um Trial.
                logger.warning(f"⚠️ B2B Login: Domínio {domain} fez login, mas não tem Organization registada.")
                user.is_active = False # Bloqueia o acesso até um administrador aprovar
                user.save()
                
        return user