#!/bin/bash
# ════════════════════════════════════════════
#  TESOURARIA INJ — Script de Inicialização
# ════════════════════════════════════════════

cd "$(dirname "$0")"

echo ""
echo "════════════════════════════════════════════"
echo "  🏛️  TESOURARIA INJ — Iniciando..."
echo "════════════════════════════════════════════"

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 não encontrado. Instale em https://python.org"
    exit 1
fi

# Instalar dependências se necessário
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 Instalando dependências (apenas na primeira vez)..."
    pip3 install -r requirements.txt -q
fi

# Matar processo anterior na porta 5000 (se houver)
lsof -ti:5000 | xargs kill -9 2>/dev/null

# Obter IP local
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "Verifique seu IP")

echo ""
echo "  💻  Neste computador : http://127.0.0.1:8080"
echo "  🌐  Rede local (Wi-Fi): http://${LOCAL_IP}:8080"
echo "  📱  Use o endereço da rede em celulares e tablets"
echo "  ⛔  Para parar: feche esta janela ou Ctrl+C"
echo ""

# Abrir navegador após 1.5s
(sleep 1.5 && open http://127.0.0.1:8080) &

python3 app.py
