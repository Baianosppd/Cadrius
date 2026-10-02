from django.core.management.base import BaseCommand, CommandError

from audit import service
from audit.verify import verify_chain


class Command(BaseCommand):
    help = 'Verifica a integridade da cadeia de hash da trilha de auditoria (falha com código != 0 se adulterada).'

    def handle(self, *args, **options):
        result = verify_chain()
        if result['ok']:
            service.log('audit.chain_verified', actor_type='system', changes={'checked': result['checked']})
            self.stdout.write(self.style.SUCCESS(f"Cadeia íntegra ({result['checked']} eventos)."))
            return
        service.log('audit.chain_broken', actor_type='system', outcome='error', reason=result['reason'],
                    changes={'first_bad_seq': result['first_bad_seq']})
        raise CommandError(f"CADEIA ADULTERADA no evento #{result['first_bad_seq']}: {result['reason']}")
