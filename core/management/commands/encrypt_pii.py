from django.core.management.base import BaseCommand
from django.db import transaction

from core.pii import PIIIndexMixin, encrypted_fields, plaintext_counts


class Command(BaseCommand):
    help = ('Cifra (e reindexa) os dados pessoais em repouso e RE-CIFRA com a chave atual: use depois de ligar a cifra em um campo, '
            'depois de alterar dados em massa e para ROTACIONAR a ENCRYPTION_KEY ("nova,antiga" → rodar este comando → remover a antiga). '
            'Idempotente. --dry-run só conta.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--batch', type=int, default=500)

    def handle(self, *args, dry_run=False, batch=500, **options):
        before = {k: v for k, v in plaintext_counts().items() if v}
        self.stdout.write(f'Linhas em texto puro antes: {sum(before.values())} {before or ""}')
        if dry_run:
            return
        total = 0
        for model, fields in encrypted_fields():
            names = [f.name for f in fields]
            extra = []
            if issubclass(model, PIIIndexMixin):
                extra = [c for c, *_ in model.BLIND_INDEXES.values()] + [c for c, *_ in model.TOKEN_INDEXES.values()]
            pks = list(model.objects.values_list('pk', flat=True))
            for i in range(0, len(pks), batch):
                with transaction.atomic():
                    for obj in model.objects.filter(pk__in=pks[i:i + batch]):
                        obj.save(update_fields=names + extra)  # decifra (qualquer chave) → cifra com a primeira → reindexa
                        total += 1
        after = {k: v for k, v in plaintext_counts().items() if v}
        self.stdout.write(self.style.SUCCESS(f'{total} linhas regravadas. Em texto puro depois: {sum(after.values())} {after or ""}'))
