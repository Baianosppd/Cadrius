import logging
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from accounts.models import Organization, OrganizationMembership

logger = logging.getLogger(__name__)

def _email_is_verified(sociallogin, email: str) -> bool:
    """True se o provedor SSO marcou ``email`` como verificado."""
    for address in getattr(sociallogin, 'email_addresses', []) or []:
        if (address.email or '').lower() == email.lower() and address.verified:
            return True
    return False


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

        # Só vincula automaticamente a um escritório se o provedor atestou o e-mail
        # (Microsoft pode devolver e-mails não verificados -> sequestro de vínculo por domínio).
        if not _email_is_verified(sociallogin, email):
            logger.warning("B2B Login: e-mail não verificado pelo provedor; sem auto-vínculo user_id=%s", user.pk)
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
                logger.info("B2B Login: user_id=%s auto-vinculado a org_id=%s", user.pk, org.pk)
                
            except Organization.DoesNotExist:
                # O domínio é corporativo, mas a empresa ainda não pagou/não tem conta connosco.
                # Aqui poderias, por exemplo, suspender a conta até pagarem, ou criar um Trial.
                logger.warning("B2B Login: domínio corporativo sem Organization registada (user_id=%s).", user.pk)
                user.is_active = False # Bloqueia o acesso até um administrador aprovar
                user.save()
                
        return user