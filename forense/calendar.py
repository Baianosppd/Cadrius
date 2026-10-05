"""Calendário forense e contagem de prazos em dias úteis (CAD-172).

Regras usadas (CPC/2015): art. 219 (só dias úteis), art. 224 (exclui o dia do começo, inclui o do vencimento; começo/fim em dia
não útil passa para o próximo útil), art. 220 (prazos suspensos de 20/12 a 20/01). Publicação no Diário eletrônico: considera-se o
1º dia útil seguinte ao da disponibilização (Lei 11.419/2006, art. 4º, §3º).

**[VALIDAR]** Carnaval, Sexta-feira Santa e Corpus Christi são tratados como dias sem expediente forense (o mais comum nos tribunais),
mas variam por tribunal; a Justiça Federal (Lei 5.010/66, art. 62) fecha também quarta e quinta da Semana Santa, 11/08, 01/11 e
08/12. Feriados estaduais, municipais e do tribunal: o escritório cadastra (``Holiday``). O resultado é SUGESTÃO; o advogado confere.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

FIXED = {(1, 1): 'Confraternização Universal', (4, 21): 'Tiradentes', (5, 1): 'Dia do Trabalho', (9, 7): 'Independência',
         (10, 12): 'Nossa Senhora Aparecida', (11, 2): 'Finados', (11, 15): 'Proclamação da República',
         (11, 20): 'Dia Nacional de Zumbi e da Consciência Negra', (12, 25): 'Natal'}
FEDERAL_EXTRA = {(8, 11): 'Dia da Justiça (Justiça Federal)', (11, 1): 'Todos os Santos (Justiça Federal)',
                 (12, 8): 'Dia da Justiça (Justiça Federal)'}
MAX_DAYS = 365


def easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=64)
def national_closures(year: int, federal: bool = False) -> dict:
    """{data: motivo} — feriados nacionais + fechamentos forenses móveis."""
    out = {date(year, m, d): name for (m, d), name in FIXED.items()}
    e = easter(year)
    out[e - timedelta(days=48)] = 'Carnaval (segunda-feira)'
    out[e - timedelta(days=47)] = 'Carnaval (terça-feira)'
    out[e - timedelta(days=2)] = 'Sexta-feira Santa'
    out[e + timedelta(days=60)] = 'Corpus Christi'
    if federal:
        out[e - timedelta(days=4)] = 'Semana Santa (Justiça Federal)'
        out[e - timedelta(days=3)] = 'Semana Santa (Justiça Federal)'
        out.update({date(year, m, d): name for (m, d), name in FEDERAL_EXTRA.items()})
    return out


def in_recess(day: date) -> bool:
    """CPC art. 220: suspensão de 20 de dezembro a 20 de janeiro (inclusive)."""
    return (day.month == 12 and day.day >= 20) or (day.month == 1 and day.day <= 20)


class Calendar:
    """Calendário de um escritório/tribunal: nacionais + recesso + feriados cadastrados."""

    def __init__(self, organization=None, tribunal: str = ''):
        self.tribunal = (tribunal or '').lower()
        self.federal = self.tribunal.startswith('trf')
        self.custom = {}
        if organization is not None:
            from forense.models import Holiday
            for h in Holiday.objects.filter(organization=organization):
                if not h.tribunal or h.tribunal.lower() == self.tribunal:
                    self.custom[(None if h.yearly else h.date.year, h.date.month, h.date.day)] = h.name

    def reason(self, day: date) -> str | None:
        """Motivo de o dia NÃO ser útil para prazo (None = dia útil)."""
        if day.weekday() == 5:
            return 'sábado'
        if day.weekday() == 6:
            return 'domingo'
        if in_recess(day):
            return 'recesso forense (CPC art. 220)'
        name = national_closures(day.year, self.federal).get(day)
        if name:
            return name
        return self.custom.get((day.year, day.month, day.day)) or self.custom.get((None, day.month, day.day))

    def is_business_day(self, day: date) -> bool:
        return self.reason(day) is None

    def next_business_day(self, day: date, skipped: list) -> date:
        while (why := self.reason(day)) is not None:
            skipped.append({'data': day, 'motivo': why})
            day += timedelta(days=1)
        return day

    def count(self, start: date, days: int, *, from_availability: bool = False) -> dict:
        """Prazo de ``days`` dias úteis a partir de ``start`` (intimação/publicação; ou disponibilização no Diário eletrônico)."""
        if not 1 <= days <= MAX_DAYS:
            raise ValueError(f'Prazo entre 1 e {MAX_DAYS} dias.')
        skipped = []
        publication = start
        if from_availability:                                    # Lei 11.419, art. 4º §3º
            publication = self.next_business_day(start + timedelta(days=1), skipped)
        day, counted = publication, 0
        while counted < days:                                   # exclui o dia do começo (CPC art. 224)
            day += timedelta(days=1)
            why = self.reason(day)
            if why is None:
                counted += 1
            else:
                skipped.append({'data': day, 'motivo': why})
        return {'inicio': start, 'publicacao': publication if from_availability else None, 'vencimento': day,
                'dias_uteis': days, 'pulados': skipped}

    def add(self, day: date, n: int) -> date:
        """``n`` dias úteis depois de ``day`` (0 = o próprio dia, ou o próximo útil se não for útil)."""
        if n <= 0:
            return self.next_business_day(day, [])
        return self.count(day, n)['vencimento']

    def back(self, day: date, n: int) -> date:
        """``n`` dias úteis antes de ``day`` (para lembrar com antecedência)."""
        while n > 0:
            day -= timedelta(days=1)
            if self.is_business_day(day):
                n -= 1
        return day
