#!/bin/sh
set -eu

output="${1:-/work/samples/meeting-ru-kk.wav}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

speak() {
  index="$1"
  voice="$2"
  pitch="$3"
  text="$4"
  espeak-ng -v "$voice" -s 145 -p "$pitch" -w "$work/raw-$index.wav" "$text"
  ffmpeg -hide_banner -loglevel error -y -i "$work/raw-$index.wav" \
    -ar 16000 -ac 1 -c:a pcm_s16le "$work/part-$index.wav"
}

speak 00 ru 36 "Добрый день. Меня зовут Айгерим Серикова. Начинаем короткий статус по проекту."
speak 01 kk 68 "Сәлеметсіздер ме. Менің атым Данияр Ахметов. Жауаптылар мен мерзімдерді белгілейік."
speak 02 ru 36 "Данияр, подготовьте список клиентов и отправьте его команде завтра до десяти утра."
speak 03 kk 68 "Жақсы, клиенттер тізімін ертең сағат онға дейін дайындап жіберемін."
speak 04 kk 68 "Айгерим, финалдық презентацияны жұмаға дейін дайындаңыз және тест нәтижелерін қосыңыз."
speak 05 ru 36 "Принято. Презентацию подготовлю к пятнице. Результаты тестов проверю до конца недели."
speak 06 kk 68 "Қорытынды: Данияр клиенттер тізіміне, Айгерим презентацияға жауап береді."
speak 07 ru 36 "Все поручения зафиксированы. На этом совещание завершено. Рахмет."

ffmpeg -hide_banner -loglevel error -y -f lavfi -i "anullsrc=r=16000:cl=mono" \
  -t 0.85 "$work/silence.wav"

concat="$work/concat.txt"
: > "$concat"
for index in 00 01 02 03 04 05 06 07; do
  printf "file '%s'\n" "$work/part-$index.wav" >> "$concat"
  if [ "$index" != "07" ]; then
    printf "file '%s'\n" "$work/silence.wav" >> "$concat"
  fi
done

mkdir -p "$(dirname "$output")"
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$concat" \
  -c:a pcm_s16le "$output"
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$output"
