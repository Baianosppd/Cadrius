"""Validação de documentos brasileiros (dígitos verificadores)."""
import re


def only_digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _check_digit(digits: str, weights) -> int:
    total = sum(int(d) * w for d, w in zip(digits, weights))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def is_valid_cpf(value) -> bool:
    cpf = only_digits(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    first = _check_digit(cpf[:9], range(10, 1, -1))
    second = _check_digit(cpf[:10], range(11, 1, -1))
    return cpf[-2:] == f"{first}{second}"


def is_valid_cnpj(value) -> bool:
    cnpj = only_digits(value)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    first = _check_digit(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = _check_digit(cnpj[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return cnpj[-2:] == f"{first}{second}"


def format_cpf(value) -> str:
    cpf = only_digits(value)
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def format_cnpj(value) -> str:
    cnpj = only_digits(value)
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
