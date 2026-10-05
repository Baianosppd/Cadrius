"""Andamentos "traduzidos" para o cliente (CAD-175).

Os nomes dos andamentos vêm da Tabela Processual Unificada do CNJ (via DataJud) e são técnicos. Aqui trocamos os mais comuns por uma
frase simples, sem IA (não gasta crédito, não envia dado a terceiros e é previsível). Quando não reconhecemos, mostramos o nome original
com um aviso genérico — nunca inventamos o significado. A ordem importa: o primeiro padrão que casar vence.
"""
from __future__ import annotations

import re
import unicodedata

RULES = [
    (r'transito em julgado', 'A decisão ficou definitiva: não cabe mais recurso.'),
    (r'arquivamento definitivo|arquivado definitivamente|baixa definitiva', 'O processo foi encerrado e arquivado.'),
    (r'arquivamento provisorio|sobrestamento|suspens', 'O processo está parado por um tempo (suspenso ou aguardando outro fato).'),
    (r'desarquiv', 'O processo foi retirado do arquivo e voltou a andar.'),
    (r'improcedencia|improcedente', 'O juiz decidiu contra o pedido. Seu advogado vai avaliar o recurso.'),
    (r'procedencia em parte|parcialmente procedente', 'O juiz aceitou parte do pedido. Seu advogado vai analisar os próximos passos.'),
    (r'procedencia|procedente', 'O juiz aceitou o pedido. Ainda pode haver recurso da outra parte.'),
    (r'homologa.*acordo|acordo homologado|homologacao de transacao', 'O juiz aprovou o acordo entre as partes.'),
    (r'extincao|extinto', 'O processo foi encerrado pelo juiz (extinção). Seu advogado explicará o motivo.'),
    (r'sentenca', 'O juiz deu a sentença (a decisão principal do processo).'),
    (r'acordao', 'O tribunal julgou o recurso (acórdão).'),
    (r'tutela|liminar', 'Houve decisão sobre um pedido urgente (liminar/tutela).'),
    (r'conclus', 'O processo está com o juiz para analisar e decidir.'),
    (r'audiencia.*(designada|marcada|agendada)|designada audiencia', 'Foi marcada uma audiência. Seu advogado vai orientar você.'),
    (r'audiencia.*(realizada|conciliacao|instrucao)', 'Aconteceu uma audiência no processo.'),
    (r'audiencia.*(cancelada|redesignada|adiada)', 'A audiência foi remarcada ou cancelada.'),
    (r'citacao|citado', 'A outra parte foi chamada oficialmente para participar do processo.'),
    (r'intimacao|intimado', 'Alguém do processo foi comunicado oficialmente de um ato ou prazo.'),
    (r'mandado', 'A justiça mandou cumprir uma ordem (por meio de oficial de justiça).'),
    (r'pericia|laudo|perito', 'Etapa de perícia: um especialista analisa o caso para o juiz.'),
    (r'calculo|contadoria', 'Estão sendo feitos os cálculos dos valores do processo.'),
    (r'alvara|levantamento', 'Foi liberada (ou pedida) a retirada de valores depositados.'),
    (r'precatorio|requisicao de pequeno valor|rpv', 'Etapa de pagamento pelo poder público (precatório/RPV).'),
    (r'penhora|bloqueio|bacenjud|sisbajud', 'A justiça bloqueou ou penhorou bens/valores para garantir o pagamento.'),
    (r'deposito|pagamento', 'Houve um depósito ou pagamento no processo.'),
    (r'apelacao|recurso|agravo|embargos', 'Foi apresentado um recurso, que será analisado.'),
    (r'remessa|remetidos os autos|encaminhad', 'O processo foi enviado para outro setor ou tribunal.'),
    (r'recebimento|recebidos os autos', 'O processo chegou a um novo setor e vai seguir dali.'),
    (r'redistribu', 'O processo mudou de vara ou de juiz.'),
    (r'distribu', 'O processo foi registrado e enviado para uma vara (início).'),
    (r'decurso de prazo|prazo decorrido', 'Terminou um prazo do processo.'),
    (r'juntada', 'Um documento ou manifestação foi anexado ao processo.'),
    (r'peticao', 'Uma das partes apresentou um pedido ou manifestação.'),
    (r'decisao', 'O juiz tomou uma decisão no processo.'),
    (r'despacho|mero expediente|ato ordinatorio', 'Andamento de rotina para dar seguimento ao processo.'),
    (r'publicacao|disponibilizad', 'Um ato do processo foi publicado no diário oficial.'),
    (r'expedicao|expedido', 'O cartório emitiu um documento do processo (ofício, carta, certidão).'),
    (r'certidao', 'O cartório registrou uma certidão no processo.'),
]
_COMPILED = [(re.compile(p), text) for p, text in RULES]
FALLBACK = 'Andamento registrado pelo tribunal. Em caso de dúvida, fale com seu advogado.'


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', text)


def explain(name: str, complement: str = '') -> tuple[str, bool]:
    """(frase simples, reconhecido?)."""
    norm = _norm(f'{name} {complement}')
    for pattern, text in _COMPILED:
        if pattern.search(norm):
            return text, True
    return FALLBACK, False
