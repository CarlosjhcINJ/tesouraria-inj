# Como publicar a Tesouraria INJ

## O que mudou e por quê

O plano gratuito do Render **apaga o banco de dados** a cada reinício do serviço e põe o
sistema para dormir depois de 15 minutos sem acesso. Para uso oficial, o sistema agora usa:

| Item | Plano no Render | Custo aproximado |
|---|---|---|
| Servidor (não dorme) | Starter | US$ 7 por mês |
| Banco de dados Postgres permanente | Basic-256mb | US$ 6 por mês |

Total: cerca de **US$ 13 por mês** (confira o valor atual em render.com/pricing).
Dividido entre as congregações, fica abaixo de R$ 1 por congregação por mês.

## Passo a passo

1. No GitHub, deixe o repositório **privado** (Settings → General → Danger Zone → Change visibility).
2. No Render, clique em **New + → Blueprint** e escolha este repositório.
   O arquivo `render.yaml` cria o servidor e o banco de dados juntos.
3. Quando o Render pedir, preencha a variável **ADMIN_SENHA** com uma senha forte
   (mínimo 8 caracteres). Ela cria o primeiro usuário da Tesouraria Nacional, com o usuário `nacional`.
   A senha nunca fica escrita no código.
4. Cadastre o cartão no Render para os planos pagos e confirme.
5. Depois de publicado, entre com `nacional` e a senha escolhida e troque a senha em **Minha conta**.

## Primeiros passos no sistema

1. **Congregações e usuários:** cadastre cada congregação com o tesoureiro e o pastor.
2. **Cartas anuais:** emita a carta do ano de cada congregação. Se os dízimos do ano anterior
   não estiverem no sistema, use **Ajustar** e digite a categoria e o % de fundo local da carta atual.
3. O pastor entra e confirma a carta.
4. O tesoureiro lança dízimos e ofertas e, no começo do mês seguinte, usa **Fechar o mês**.

## Rodar no computador (para testes)

```bash
pip install -r requirements.txt
ADMIN_SENHA="uma-senha-de-teste" python3 app.py
```

Sem `DATABASE_URL`, o sistema usa um arquivo SQLite em `data/tesouraria.db`.

## Testes automáticos

```bash
pip install pytest
python -m pytest -q
```

Os testes repetem o fechamento real de Vila Ramos de setembro de 2026 (total R$ 3.014,11).
