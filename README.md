# SecondBrainKit

> **Приватна платна бета · 3.0.0-beta.1**

Кит дає агенту зовнішню памʼять про твою історію: архіви чатів перетворюються на
локальну базу, пошук знаходить потрібне **по змісту**, а Claude Code і Codex читають
джерела замість того, щоб щоразу випитувати контекст заново.

## Три версії, одна установка

Версії **нашаровуються**. Не буває «переставити з нуля під нову» — є одна база в
одному місці й один рух: підняти тир.

| | По-простому | Що дає |
|---|---|---|
| **v1** *(безкоштовна, [публічне репо](https://github.com/steptonite/step_secondbrain_kit))* | база старту | твої архіви стають базою, яку агент читає й шукає по змісту |
| **v2** | відкалібрована робоча машинка | воно не зламається у тебе на залізі: бекап перед кожною зміною, відкат, перевірка здоровʼя |
| **v3** | та, що ловить сама себе на брехні | агент звіряє **сказане із записаним**: рішення, що прозвучало й не лягло в базу, більше не зникає |

## Установка — одна команда

```bash
bash install.sh
```

Безпечно запускати **поверх уже наявної бази** і повторно. Якщо в корені лежить
вольт від безкоштовної версії — Кит його підхопить: зробить бекап, додасть свій
шар і нічого не видалить.

Усі чотири шляхи робочі й дають однаковий результат:

```bash
bash install.sh --tier v1          # почав з безкоштовної
python3 sbkit.py upgrade --to v2   # походив на v1 → взяв наступну
```

Що стоїть зараз і які шари активні:

```bash
python3 sbkit.py tiers --root ~/SecondBrain
```

Подробиці: [docs/19-tiers.md](docs/19-tiers.md).

## Подивитись, нічого не встановлюючи

```bash
python3 sbkit.py doctor
bash scripts/setup.sh
.venv/bin/python sbkit.py demo
```

`demo` не потребує API-ключа чи особистих даних: створює синтетичний індекс,
показує, звідки взято кожен результат, і прибирає за собою.

## Звід — те, заради чого існує v3

`RECONCILE.md` — список того, що прозвучало в розмові й **не доїхало** до бази.
Наповнюється автоматично, вкидається у кожну сесію на старті, тому модель фізично
не може його не побачити.

Дзеркальний бік — `TASK_RECONCILE.md`: дії, які вже зроблено, а задача досі відкрита.

Контур зводу входить у **v3**: `python3 sbkit.py tiers` покаже, як його підняти.

## Супутники — окремі безкоштовні застосунки

Кит працює без них. Вони прибирають шви між тобою і агентом:

| | Що робить |
|---|---|
| [KobzarAI](https://github.com/steptonite/KobzarAI) | панель для локальних моделей Ollama — без термінала |
| [Pysar](https://github.com/steptonite/pysar) | диктування і розшифровка на самому Маку: натиснув Caps Lock, сказав, текст під курсором |
| [Осавул](https://github.com/steptonite/osavul) | пульт рутин: що і коли запускається, пауза й вимкнення — без моделі |

Агент пропонує їх **тільки за приводом** — коли на цій машині реально є привід — і
рівно один раз за сесію. Перевірити, що спрацює зараз:


Двигун приводів входить у **v2**: `python3 sbkit.py tiers` покаже, як його підняти.

## З безкоштовної на платну

```bash
python3 sbkit.py install --tier v2 --root ~/SecondBrain
```

Якщо конфіг від v1 лежить окремо, є явна міграція з попереднім переглядом
(dry-run нічого не змінює):

```bash
.venv/bin/python sbkit.py migrate --from v1 \
  --source-config ~/старий/config.toml --root ~/SecondBrain
.venv/bin/python sbkit.py migrate --from v1 \
  --source-config ~/старий/config.toml --root ~/SecondBrain --apply
```

## Щоденна робота

```bash
# semantic recall
SB_CONFIG="$HOME/SecondBrain/.sbkit/config.toml" \
  .venv/bin/python scripts/librarian.py search "останнє рішення" \
  --after 2026-07-01 --prefer-recent --format json

# deterministic task state
SB_CONFIG="$HOME/SecondBrain/.sbkit/config.toml" \
  .venv/bin/python scripts/task.py list

# local Claude/Codex session ingest
SB_CONFIG="$HOME/SecondBrain/.sbkit/config.toml" \
  .venv/bin/python scripts/brain_refresh.py

# read-only health report
.venv/bin/python sbkit.py health --root "$HOME/SecondBrain"
```

## Lifecycle

```text
doctor → demo → install/migrate → backup → upgrade
                              ↘ restore / rollback
```

- `search`, `stats`, `prune` dry-run і `health` не потребують write-доступу до
  індексу.
- `prune --apply`, `index`, `install`, `migrate --apply`, `upgrade`, `restore`
  та `rollback` є явними мутаціями.
- Хмарні ChatGPT/Gemini/Claude exports у 2.0 завантажуються вручну.
- Ніяких cron/launchd-автозапусків Kit не ставить.

## Підтримка платформ

- macOS — основний guided маршрут;
- Linux — підтриманий CLI-маршрут;
- Windows/WSL — не обіцяється до окремого acceptance-пілота.

## Структура

```text
install.sh                 одна команда від нуля до працюючої бази
sbkit.py                   керуюча утиліта: install / upgrade / tiers / backup
TIERS.toml                 маніфест шарів: який файл до якої версії належить

scripts/librarian.py       пошук по змісту + JSON API
scripts/task.py            задачі в Markdown, повний життєвий цикл
scripts/brain_refresh.py   інкрементальний доїзд сесій Claude/Codex


templates/                 адаптери для Claude Code і Codex + фрагменти тирів
fixtures/                  синтетичні дані для тестів
docs/                      покрокові інструкції, від експорту архівів до тирів
```

## Ліцензія й підтримка

Це приватний платний single-user продукт. Тири v2 і v3 ліцензуються окремо;
репозиторій, релізні архіви і код не можна передавати іншим. Тир v1 —
безкоштовний і публічний, він живе в окремому репозиторії й на нього ці обмеження
не поширюються. Застосунки-супутники — окремі продукти зі своїми ліцензіями. Деталі: [LICENSE.md](LICENSE.md) і
[SUPPORT.md](SUPPORT.md).
