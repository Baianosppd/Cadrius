"""CAD-222: novos gatilhos, triagem de e-mails, envio pelo melhor canal com horário comercial e compromissos do Google Agenda."""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from automations import catalog, engine, messaging
from automations.models import Rule, RuleRun
from automations.templates import TEMPLATES
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.maria = Contact.objects.create(organization=self.org, name='Maria Cliente', email='maria@c.com', phone='11999998888',
                                            email_consent=True, whatsapp_consent=True)
        on_commit = mock.patch('django.db.transaction.on_commit', side_effect=lambda fn: fn())
        on_commit.start()
        self.addCleanup(on_commit.stop)

    def rule(self, key, **kw):
        t = dict(TEMPLATES[key])
        kw.setdefault('enabled', True)
        kw.setdefault('require_approval', False)
        return Rule.objects.create(organization=self.org, **{**catalog.clean_rule(t), 'name': t['name'], **kw})


class MessagingTests(Base):
    def test_melhor_canal_respeita_consentimento_e_conexao(self):
        self.assertEqual(messaging.pick_channel(self.org, self.maria, 'melhor'), 'email')      # sem conexão de WhatsApp
        with mock.patch.object(messaging, 'whatsapp_connection', return_value=object()):
            self.assertEqual(messaging.pick_channel(self.org, self.maria, 'melhor'), 'whatsapp')
        self.maria.opted_out = True
        with self.assertRaises(messaging.Blocked):
            messaging.pick_channel(self.org, self.maria, 'melhor')

    def test_horario_comercial(self):
        tz = timezone.get_current_timezone()
        def local(y, m, d, h):
            return timezone.make_aware(timezone.datetime(y, m, d, h, 30), tz)
        self.assertTrue(messaging.business_hours(local(2030, 3, 6, 10)))      # quarta 10h
        self.assertFalse(messaging.business_hours(local(2030, 3, 6, 22)))     # quarta 22h
        self.assertFalse(messaging.business_hours(local(2030, 3, 10, 10)))    # domingo
        self.assertFalse(messaging.business_hours(local(2030, 12, 25, 10)))   # Natal
        nxt = messaging.next_business_moment(local(2030, 3, 6, 22))
        self.assertEqual((nxt.day, nxt.hour), (7, 8))

    def test_fora_do_horario_agenda_e_retoma(self):
        from carteira.models import Receivable
        rec = Receivable.objects.create(organization=self.org, contact=self.maria, description='Parcela 1/3', amount_cents=200000,
                                        due_date=timezone.localdate(), status='pago', paid_cents=200000, paid_at=timezone.localdate())
        rule = self.rule('pagamento_agradecimento')
        with mock.patch.object(messaging, 'business_hours', return_value=False), \
                mock.patch('integrations.services.send_office_email', return_value=True) as send:
            run = engine.execute(rule.pk, {'receivable_id': rec.pk}, 'paid-test')
        send.assert_not_called()
        self.assertEqual(run.status, RuleRun.Status.SCHEDULED)
        self.assertEqual(run.steps[0]['status'], 'agendado')
        from django_q.models import Schedule
        sched = Schedule.objects.get(func='automations.engine.resume_step')
        with mock.patch('integrations.services.send_office_email', return_value=True) as send:
            engine.resume_step(run.pk, 0)
        send.assert_called_once()
        run.refresh_from_db()
        self.assertEqual((run.status, run.steps[0]['resultado']['canal']), (RuleRun.Status.SUCCESS, 'email'))
        self.assertTrue(sched.next_run > timezone.now() - timedelta(minutes=1))


class TriggerTests(Base):
    def test_modelos_novos_validos_e_simulam(self):
        for key in ('agenda_audiencia_cliente', 'agenda_prazo_equipe', 'email_intimacao_tarefa', 'email_cliente_responder',
                    'email_comercial_aviso', 'pagamento_agradecimento', 'funil_reuniao_confirmacao', 'contrato_boas_vindas',
                    'tarefa_atrasada_aviso'):
            rule = self.rule(key, enabled=False)
            out = engine.simulate(rule)
            self.assertIn('passos', out, key)

    def test_eventos_de_carteira_disparam(self):
        from carteira import services
        from carteira.models import Opportunity
        with mock.patch('automations.engine.emit') as emit:
            opp = Opportunity.objects.create(organization=self.org, contact=self.maria, title='Divórcio')
            services.move_stage(opp, 'reuniao', self.owner)
            ag = services.create_agreement(self.org, self.owner, contact=self.maria, title='Alimentos', kind='avista', total_cents=100000,
                                           first_due=timezone.localdate())
            services.mark_paid(ag.receivables.first(), self.owner)
        names = [c.args[1] for c in emit.call_args_list]
        self.assertEqual(names, ['opportunity_stage', 'agreement_created', 'receivable_paid'])

    def test_tarefa_atrasada_no_tick(self):
        from tasks.models import UserTask
        UserTask.objects.create(titulo='Protocolar', scheduled_at=timezone.now() - timedelta(days=2), responsavel=self.owner)
        self.rule('tarefa_atrasada_aviso')
        with mock.patch('notifications.services.notify') as notify:
            out = engine.tick()
            engine.tick()                                           # não repete
        self.assertEqual(out['overdue'], 1)
        self.assertEqual(notify.call_count, 1)


class EmailTriageTests(Base):
    def email(self, subject, body='', sender='alguem@x.com'):
        from emails.models import EmailMessage, MailBox
        box, _ = MailBox.objects.get_or_create(user=self.owner, name='Caixa', defaults={'imap_host': 'imap.x', 'username': 'u'})
        return EmailMessage.objects.create(mailbox=box, message_id=f'<{subject}>', subject=subject, sender=sender,
                                           received_at=timezone.now(), body_text=body)

    def test_regras_classificam(self):
        from emails.triage import by_rules
        self.assertEqual(by_rules('Intimação eletrônica', '', 'naoresponda@tjsp.jus.br', False)['category'], 'intimacao')
        self.assertEqual(by_rules('Orçamento', 'gostaria de contratar um advogado', 'a@b.com', False)['category'], 'comercial')
        self.assertEqual(by_rules('Oi doutor', 'tudo bem? URGENTE', 'maria@c.com', True)['category'], 'cliente')
        self.assertEqual(by_rules('Oi doutor', 'tudo bem? URGENTE', 'maria@c.com', True)['urgency'], 'alta')
        self.assertEqual(str(by_rules('Audiência remarcada', 'nova data 10/03/2030', 'x@y.com', False)['due_date']), '2030-03-10')

    def test_triagem_cria_registro_e_dispara_regra(self):
        from emails.triage import triage_email
        from tasks.models import UserTask
        self.rule('email_cliente_responder')
        em = self.email('Dúvida sobre o processo', 'Doutor, quando sai a sentença?', sender='Maria <maria@c.com>')
        with mock.patch('emails.triage.by_ai', return_value=None), \
                mock.patch('core.queue.enqueue', side_effect=lambda f, *a: engine.execute(*a)):
            self.assertEqual(triage_email(em.pk), 'cliente')
            self.assertIsNone(triage_email(em.pk))                  # idempotente
        self.assertEqual(em.triage.contact, self.maria)
        self.assertTrue(UserTask.objects.filter(titulo__startswith='Responder Maria Cliente').exists())

    def test_ia_refina_quando_disponivel(self):
        from emails.triage import triage_email
        em = self.email('Re: caso', 'segue')
        ai = {'categoria': 'agenda', 'urgencia': 'alta', 'resumo': 'Audiência marcada.', 'acao_sugerida': 'Agendar', 'data_citada': '2030-04-01'}
        with mock.patch('emails.triage.by_ai', return_value=ai), mock.patch('automations.engine.emit'):
            triage_email(em.pk)
        em.triage.refresh_from_db()
        self.assertEqual((em.triage.category, em.triage.method, str(em.triage.due_date)), ('agenda', 'ia', '2030-04-01'))


class CalendarTests(Base):
    def link(self):
        from gcal.models import GoogleCalendarApp, GoogleCalendarLink
        app = GoogleCalendarApp.objects.create(organization=self.org, client_id='c', client_secret='s')
        return GoogleCalendarLink.objects.create(user=self.owner, app=app, refresh_token='r')

    def test_classificacao(self):
        from gcal.events import classify
        self.assertEqual(classify('Audiência de conciliação - Maria'), 'audiencia')
        self.assertEqual(classify('Protocolar contestação'), 'prazo')
        self.assertEqual(classify('Call com cliente'), 'reuniao')
        self.assertEqual(classify('Dentista'), 'outro')

    def test_importa_classifica_vincula_e_cria_tarefa(self):
        from gcal.events import pull_external
        from gcal.models import ExternalEvent
        from research.models import MonitoredCase
        from tasks.models import UserTask
        case = MonitoredCase.objects.create(organization=self.org, cnj='0001234-56.2030.8.26.0100', tribunal='tjsp')
        soon = (timezone.now() + timedelta(days=3)).isoformat()
        items = [
            {'id': 'e1', 'summary': 'Audiência de instrução', 'start': {'dateTime': soon}, 'end': {'dateTime': soon},
             'attendees': [{'email': 'dono@x.com', 'self': True}, {'email': 'maria@c.com'}]},
            {'id': 'e2', 'summary': 'Prazo contestação 0001234-56.2030.8.26.0100', 'start': {'date': (timezone.localdate() + timedelta(days=5)).isoformat()}},
            {'id': 'e3', 'summary': 'Tarefa do Cadrius', 'start': {'dateTime': soon}, 'extendedProperties': {'private': {'cadrius': '1'}}},
        ]
        link = self.link()
        with mock.patch('gcal.sync._call', return_value={'items': items}):
            stats = pull_external(link, force=True)
        self.assertEqual(stats['new'], 2)
        aud = ExternalEvent.objects.get(event_id='e1')
        prazo = ExternalEvent.objects.get(event_id='e2')
        self.assertEqual((aud.kind, aud.contact), ('audiencia', self.maria))
        self.assertEqual((prazo.kind, prazo.case, prazo.all_day), ('prazo', case, True))
        self.assertEqual(UserTask.objects.filter(titulo__startswith='Prazo: ').count(), 1)         # entra no "Prazo chegando"
        self.assertEqual(UserTask.objects.filter(titulo__startswith='Audiência: ').count(), 1)
        self.assertFalse(UserTask.objects.filter(sincronizar=True).exists())                     # não volta duplicado ao Google
        with mock.patch('gcal.sync._call', return_value={'items': [items[0]]}):
            stats = pull_external(link, force=True)
        prazo.refresh_from_db()
        self.assertTrue(prazo.cancelled)                                                          # sumiu do Google

    def test_alerta_ao_cliente_um_dia_antes(self):
        from gcal.models import ExternalEvent
        link = self.link()
        now = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        tomorrow = now + timedelta(days=1)
        ExternalEvent.objects.create(link=link, organization=self.org, event_id='x', title='Audiência', kind='audiencia',
                                     start=tomorrow.replace(hour=14), contact=self.maria)
        self.rule('agenda_audiencia_cliente')
        with mock.patch.object(messaging, 'business_hours', return_value=True), \
                mock.patch('integrations.services.send_office_email', return_value=True) as send:
            out = engine.tick(now=now)
        self.assertEqual(out['calendar'], 1)
        self.assertIn('Lembrete', send.call_args.args[1])
        self.assertIn('14:00', send.call_args.args[2])
        self.assertTrue(RuleRun.objects.get().dedupe_key.startswith('gcal-'))
