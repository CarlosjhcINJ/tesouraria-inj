# Como publicar a Tesouraria INJ

## Publicação gratuita (custo zero)

O disco do plano gratuito do Render **é apagado a cada reinício**. Por isso os dados ficam num
banco Postgres gratuito e permanente no **Neon**, e o Render fica só com o programa.

| Item | Onde | Custo |
|---|---|---|
| Programa (servidor) | Render, plano Free | R$ 0 (dorme após 15 min sem uso; o primeiro acesso leva cerca de 1 minuto) |
| Banco de dados | Neon, plano Free (1 GB, sem cartão) | R$ 0 (os dados não são apagados por inatividade) |

As fotos de comprovante são reduzidas automaticamente para cerca de 200 KB, para caber no 1 GB.
Com 18 congregações, isso dá alguns anos de comprovantes. Quando o espaço passar de 80%, será hora
de avaliar um plano pago ou guardar comprovantes antigos fora do sistema.

## Passo a passo

1. **Neon:** crie uma conta em neon.com (pode entrar com o GitHub), crie um projeto chamado
   `tesouraria-inj`, região mais próxima disponível, e copie a **connection string**
   (começa com `postgresql://`).
2. **GitHub:** deixe o repositório privado (Settings → General → Danger Zone → Change visibility).
3. **Render:** abra o serviço `tesouraria-inj` → **Environment** e preencha:
   - `DATABASE_URL` = a connection string do Neon
   - `ADMIN_SENHA` = uma senha forte (mínimo 8 caracteres) para o usuário `nacional`
4. Aprove o pedido de aprovação no GitHub (Merge). O Render publica sozinho.
5. Entre com `nacional` e a senha, e troque a senha em **Minha conta**.

Sem `DATABASE_URL`, o sistema se recusa a iniciar no Render, justamente para não perder dados.

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
