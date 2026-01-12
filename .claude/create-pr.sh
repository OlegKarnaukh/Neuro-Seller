#!/bin/bash
# Автоматическое создание PR для Railway deployment

CURRENT_BRANCH=$(git branch --show-current)
COMMITS_COUNT=$(git log origin/main..HEAD --oneline | wc -l)

if [ "$COMMITS_COUNT" -eq 0 ]; then
    echo "✅ Нет новых коммитов для PR. Ветка синхронизирована с main."
    exit 0
fi

echo "📊 Найдено $COMMITS_COUNT коммитов для PR"
echo ""
echo "🔗 Создайте PR здесь:"
echo "https://github.com/OlegKarnaukh/Neuro-Seller/compare/main...$CURRENT_BRANCH"
echo ""
echo "📝 Или используйте команду (если gh установлен):"
echo "gh pr create --base main --head $CURRENT_BRANCH --fill"
