from django.core.management.base import BaseCommand

from accounts.models import Organization
from brain import autonomy, feedback, profile, style, suggestions


class Command(BaseCommand):
    help = 'Aprendizado diário: sugere automações, atualiza o perfil, propõe regras (correções repetidas) e sugere promoções de autonomia. Nada vale sem a aprovação de uma pessoa.'

    def handle(self, *args, **options):
        rules = proposals = suggested = 0
        for org in Organization.objects.filter(is_active=True).iterator():
            rules += len(feedback.mine_rules(org))
            rules += len(style.mine_terms(org))                  # CAD-174: vocabulário do escritório
            proposals += len(autonomy.evaluate_promotions(org))
            suggested += len(suggestions.refresh(org))          # CAD-174: padrões do escritório → automações sugeridas
            profile.refresh_stats(org)
        self.stdout.write(f'{rules} regra(s) proposta(s), {proposals} sugestão(ões) de autonomia, {suggested} automação(ões) sugerida(s)')
