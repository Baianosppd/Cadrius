from django.core.management.base import BaseCommand

from accounts.models import Organization
from brain import autonomy, feedback


class Command(BaseCommand):
    help = 'Aprendizado diário: propõe regras (correções repetidas) e sugere promoções de autonomia. Nada vale sem a aprovação de uma pessoa.'

    def handle(self, *args, **options):
        rules = proposals = 0
        for org in Organization.objects.filter(is_active=True).iterator():
            rules += len(feedback.mine_rules(org))
            proposals += len(autonomy.evaluate_promotions(org))
        self.stdout.write(f'{rules} regra(s) proposta(s), {proposals} sugestão(ões) de autonomia')
