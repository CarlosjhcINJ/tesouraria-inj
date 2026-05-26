"""
Script executado automaticamente ao iniciar no servidor.
Garante que o banco de dados existe antes do app rodar.
"""
from app import init_db
init_db()
print("✅ Banco de dados inicializado.")
