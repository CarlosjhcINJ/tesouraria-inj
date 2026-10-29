"""
Mantido por compatibilidade: o serviço no Render roda
"python init_app.py && gunicorn app:app ..." antes de iniciar.
Prepara o banco de dados (o app.py também faz isso ao iniciar).
"""
from app import init_db

init_db()
print("Banco de dados inicializado.")
