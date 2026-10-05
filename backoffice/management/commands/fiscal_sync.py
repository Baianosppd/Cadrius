from django.core.management.base import BaseCommand

from backoffice import nfse, obligations


class Command(BaseCommand):
    help = 'Fiscal da Cadrius: consulta as NFS-e em processamento no emissor e avisa a equipe Fiscal das obrigações que vencem.'

    def handle(self, *args, **options):
        out = nfse.sync_processing()
        sent = obligations.remind()
        self.stdout.write(f'NFS-e: {out["consultadas"]} consultada(s), {out["emitidas"]} emitida(s), {out["erros"]} com erro; '
                          f'{sent} lembrete(s) de obrigação')
