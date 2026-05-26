# 🌐 Como Publicar o Tesouraria INJ Online (GRÁTIS)

## Opção Recomendada: Render.com (grátis, permanente)

### Passo 1 — Criar conta no GitHub
1. Acesse https://github.com e crie uma conta gratuita
2. Clique em "New repository"
3. Nome: `tesouraria-inj`
4. Deixe como "Public" e clique "Create repository"

### Passo 2 — Enviar os arquivos para o GitHub
Abra o Terminal e execute:
```bash
cd ~/Documents/TesourariaINJ
git init
git add .
git commit -m "Tesouraria INJ - versão inicial"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/tesouraria-inj.git
git push -u origin main
```

### Passo 3 — Publicar no Render
1. Acesse https://render.com e crie conta (grátis)
2. Clique em "New +" → "Web Service"
3. Conecte sua conta GitHub
4. Escolha o repositório `tesouraria-inj`
5. Configure:
   - **Name**: tesouraria-inj
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
6. Clique "Create Web Service"
7. Aguarde 2-3 minutos
8. ✅ Seu link será algo como: `https://tesouraria-inj.onrender.com`

---

## Usuário Admin Padrão
- **Usuário**: admin
- **Senha**: admin123
- ⚠️ MUDE A SENHA após o primeiro acesso!

## Como adicionar uma Congregação
1. Entre com o usuário admin
2. Clique em "Administrador" no menu
3. Clique "Nova Congregação"
4. Defina nome, usuário e senha
5. Envie o link + usuário + senha para o tesoureiro

## Link para compartilhar
Após publicar, o link será algo como:
`https://tesouraria-inj.onrender.com`

Cada congregação entra com seu próprio usuário e vê apenas seus dados.
