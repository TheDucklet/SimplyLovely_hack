set -eu

for city in moscow tula; do
  if [ ! -f "data/processed/$city/hex_features.parquet" ]; then
    echo "Нет данных data/processed/$city. Распакуйте архив данных команды в корень репозитория рядом с compose.demo.yml, чтобы появился каталог data/processed, и перезапустите стенд." >&2
    exit 1
  fi
done

stale=0
for city in moscow tula; do
  for niche in coffee pickup_point; do
    scores="data/scores/${city}_${niche}.parquet"
    if [ ! -f "$scores" ] || [ -n "$(find "data/processed/$city" "research" -newer "$scores" -type f | head -n 1)" ]; then
      stale=1
    fi
  done
done

if [ "$stale" -eq 1 ]; then
  echo "Расчёт карты по всем городам и нишам, около 30 секунд"
  python -m geostart.model score --city all --niche all
fi

exec uvicorn geostart.api.main:app --host 0.0.0.0 --port 8000
