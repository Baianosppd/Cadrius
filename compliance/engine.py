"""Motor de avaliação: combina verificações automáticas + avaliação manual e calcula a pontuação."""
from __future__ import annotations

from dataclasses import dataclass, field

from compliance import checks as checks_module
from compliance.catalog import CATALOG, FRAMEWORKS, Control
from compliance.models import ControlAssessment

IMPLEMENTED, PARTIAL, NOT_IMPLEMENTED, NOT_APPLICABLE, NOT_ASSESSED = (
    'implemented', 'partial', 'not_implemented', 'not_applicable', 'not_assessed')

LABELS = {
    IMPLEMENTED: 'Implementado', PARTIAL: 'Parcial', NOT_IMPLEMENTED: 'Não implementado',
    NOT_APPLICABLE: 'Não aplicável', NOT_ASSESSED: 'Não avaliado',
}
WEIGHT = {IMPLEMENTED: 1.0, PARTIAL: 0.5, NOT_IMPLEMENTED: 0.0, NOT_ASSESSED: 0.0}


@dataclass
class Row:
    control: Control
    status: str
    source: str                       # auto | manual | mixed
    auto: list = field(default_factory=list)   # [(check_name, titulo, CheckResult)]
    assessment: ControlAssessment | None = None

    @property
    def label(self) -> str:
        return LABELS[self.status]


def _auto_status(results: list) -> str | None:
    """None = nenhuma verificação conclusiva (cair para avaliação manual)."""
    statuses = [r.status for _, _, r in results if r.status != checks_module.UNKNOWN]
    if not statuses:
        return None
    if all(s == checks_module.PASS for s in statuses):
        return IMPLEMENTED
    if all(s == checks_module.FAIL for s in statuses):
        return NOT_IMPLEMENTED
    return PARTIAL


def evaluate(framework: str, results: dict | None = None) -> list[Row]:
    results = results if results is not None else checks_module.run_all()
    assessments = {a.control_id: a for a in ControlAssessment.objects.filter(framework=framework)}
    rows = []
    for control in CATALOG[framework]:
        assessment = assessments.get(control.id)
        auto = [(name, checks_module.TITLES[name], results[name]) for name in control.checks if name in results]
        auto_status = _auto_status(auto) if auto else None

        if assessment and assessment.status == NOT_APPLICABLE and assessment.justification:
            rows.append(Row(control, NOT_APPLICABLE, 'manual', auto, assessment))
        elif auto_status is not None:
            rows.append(Row(control, auto_status, 'mixed' if assessment else 'auto', auto, assessment))
        else:
            status = assessment.status if assessment else NOT_ASSESSED
            if status == NOT_APPLICABLE:  # "não aplicável" sem justificativa não vale (evita maquiar a pontuação)
                status = NOT_ASSESSED
            rows.append(Row(control, status, 'manual', auto, assessment))
    return rows


def score(rows: list[Row]) -> dict:
    counts = {k: 0 for k in LABELS}
    for r in rows:
        counts[r.status] += 1
    applicable = [r for r in rows if r.status != NOT_APPLICABLE]
    pct = (sum(WEIGHT[r.status] for r in applicable) / len(applicable) * 100) if applicable else 0.0
    return {'score': round(pct, 1), 'counts': counts, 'total': len(rows), 'applicable': len(applicable)}


def evaluate_all() -> dict:
    results = checks_module.run_all()
    out = {}
    for framework in CATALOG:
        rows = evaluate(framework, results)
        out[framework] = {'rows': rows, **score(rows), 'title': FRAMEWORKS[framework]}
    out['_checks'] = results
    scores = [v['score'] for k, v in out.items() if k != '_checks']
    out['_overall'] = round(sum(scores) / len(scores), 1)
    return out


def by_theme(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    grouped: dict[str, list[Row]] = {}
    for r in rows:
        grouped.setdefault(r.control.theme, []).append(r)
    return list(grouped.items())
