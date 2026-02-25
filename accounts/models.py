# accounts/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser

class Organization(models.Model):
    name = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class CustomUser(AbstractUser):
    # Adicionando o vínculo com a Organização
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        related_name='members',
        null=True # Null para permitir migração de usuários antigos
    )
    role = models.CharField(
        max_length=20, 
        choices=[('admin', 'Admin'), ('member', 'Member')], 
        default='member'
    )