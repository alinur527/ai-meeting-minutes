# API и AI на разных компьютерах

Frontend, API, PostgreSQL и worker могут работать на компьютере A; AI и Ollama — на B. Установка окружений: [DEPLOYMENT.md](docs/DEPLOYMENT.md).

1. На B подготовьте модели и AI `.env`. `INTERNAL_TOKEN` должен совпадать с `AI_INTERNAL_TOKEN` на A. Не передавайте его через frontend или URL.
2. На B запустите AI на приватном интерфейсе, например `python -m uvicorn app.main:app --env-file .env --host 192.168.1.20 --port 8000`. Разрешите порт 8000 только для A. Firewall меняет оператор; проект не открывает порты автоматически.
3. В backend/.env на A: `AI_BASE_URL=http://192.168.1.20:8000`, `AI_MODE=http`, `AI_EXPECTED_MODE=real`. Для mock задайте backend `AI_EXPECTED_MODE=mock`, а в AI — `AI_MODE=mock`.
4. Перезапустите API и worker. Из backend-окружения выполните `python -m app.check_ai`. С `--audio PATH` проверяется передача разрешённого файла и ответ сервиса. Один health не доказывает готовности моделей.
5. Проверьте `/ready` API или `/api/ready` через proxy. При недоступном AI, несовпадении режима/лимитов или отсутствии worker получите 503.

Worker передаёт **байты файла по multipart HTTP**, а не локальный путь. Хранилище A не нужно подключать к B. API и worker используют одну БД и один STORAGE_DIR.

`localhost` означает текущий компьютер/контейнер. BACKEND_URL Vite должен быть доступен процессу Vite. FRONTEND_ORIGIN точно совпадает с origin браузера, включая схему и порт. Предпочтителен один reverse proxy с относительным `/api`.

HTTP подходит для локальной проверки в доверенной сети. Для рабочих записей используйте HTTPS или защищённую приватную сеть. Публичный доступ к AI, PostgreSQL и Ollama не требуется. GPU и скорость на двух компьютерах здесь не проверялись.
