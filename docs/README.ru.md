# Resolve Track Visualizer

[English README](../README.md)

Resolve Track Visualizer создает карточки музыкальных треков на таймлайне DaVinci Resolve. Lua-скрипт читает активный таймлайн, bundled engine готовит метаданные и обложки, а Resolve рисует текущее время и прогресс средствами Fusion. Рендер alpha MOV остается запасным режимом.

## Статус

Версия `0.1.0` является preview-версией. Она проверена только с **DaVinci Resolve Studio 20.2.1 на Windows x64**. Текущий интерфейс UIManager требует Resolve Studio, поэтому Resolve Free не поддерживается. Проверка Resolve 21 отложена; Resolve 19 и старше, Resolve 21 и Resolve на Linux не сертифицированы. См. [матрицу совместимости](compatibility.md).

Windows x64 является единственной целью release candidate. Linux x64 собирается только отдельным ручным unpublished canary workflow. macOS не поддерживается, не собирается и не входит в текущий release scope. Наличие build target не означает, что работа плагина проверена внутри Resolve. Точные ограничения описаны в [release process](releasing.md).

Preview-артефакты **не подписаны**. Непосредственно перед каждой загрузкой workflow повторно проверяет private visibility через GitHub API; срок хранения артефактов составляет один день. Workflow не создаёт GitHub Release. Перед изменением visibility нужно удалить все сохранённые native-артефакты и соответствующие workflow runs: завершённый workflow не может защитить уже сохранённые данные. Собранный private-артефакт распаковывается в `artifacts/`, `source/` и корневой `SHA256SUMS`. Перед запуском внутренней тестовой сборки из корня распакованного артефакта нужно проверить все относительные пути:

```bash
sha256sum -c SHA256SUMS
```

## Язык

При первом запуске режим `Авто (системный)` выбирает русский для русскоязычной системы и английский для всех остальных языков. Настройки пользователей предыдущей русскоязычной версии при миграции остаются на русском.

Язык можно изменить вручную в `Расширенные -> Действия со стилем -> Язык`. После изменения закройте и снова откройте Track Visualizer; настройки тем и стилей сохранятся. Установщик также принимает `--language auto`, `--language en` и `--language ru`.

## Установка

Пользователю не нужны отдельно установленные Python или FFmpeg. Проверенный Windows installer версии 0.1.0 называется `TrackVisualizerSetup-0.1.0-windows-x64.exe`.

Installer размещает engine и FFmpeg в:

```text
%LOCALAPPDATA%\DavinciTrackVisualizer\
```

Resolve-скрипт устанавливается в:

```text
%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Track Visualizer.lua
```

После установки полностью перезапустите Resolve и откройте:

```text
Workspace -> Scripts -> Utility -> Track Visualizer
```

В русском интерфейсе пункт находится в `Рабочая область -> Сценарии -> Utility -> Track Visualizer`.

Если пункт меню не появился, проверьте путь к Lua-файлу и убедитесь, что Resolve был полностью закрыт перед повторным запуском.

Удаление выполняется тем же setup-файлом:

```powershell
.\TrackVisualizerSetup-0.1.0-windows-x64.exe --uninstall --no-pause
```

Удаляются только управляемые runtime-файлы и Resolve-скрипт. Настройки, логи, задания, временные и отрендеренные файлы сохраняются.

Отдельный ручной workflow готовит unpublished Linux x64 canary, требующий glibc 2.28 или новее. Packaging smoke проходит на Windows и Linux, но интеграция с Resolve проверена только на Windows x64.

## Работа В Resolve

1. Разместите музыкальные клипы на дорожках `A1`, `A2`, `A3` или других аудиодорожках.
2. Откройте Track Visualizer.
3. Укажите аудиодорожки и целевую видеодорожку, по умолчанию `V2`.
4. Выберите тему и палитру.
5. Нажмите `Создать / обновить визуализаторы`.

Доступны темы `Классический`, `Минимал` и `Портретное стекло`. Точная перегенерация поддерживает номера клипов, диапазоны и `@playhead`.

При включенном переключении на старте следующего трека визуализатор предыдущего клипа заканчивается в точке старта следующего. Это позволяет корректно обрабатывать crossfade между дорожками.

## Режимы Рендера

Основной режим `Fusion на лету (авто)` работает так:

1. Engine читает теги и создает статичную полноразмерную RGBA PNG-карточку.
2. Lua размещает карточку через служебный helper timeline.
3. Resolve добавляет легкую Fusion Composition.
4. Время, progress line и knob рассчитываются на FPS таймлайна.

Если Resolve не может создать live carrier или нужный Fusion input, проблемный клип может автоматически перейти на legacy alpha MOV. Принудительный режим `Только legacy MOV` доступен в расширенных настройках.

Служебные timelines с префиксом `TVIZ__SOURCE__` нельзя удалять, пока их используют nested clips.

## Метаданные И Файлы

Поддерживаемые входные форматы: MP3, WAV, FLAC, M4A, AAC и OGG. Название, артист, альбом и embedded cover читаются через Mutagen. При отсутствии обложки используется bundled `aplus.png` или выбранная пользователем PNG.

Пути и теги обрабатываются как UTF-8. Если Resolve не возвращает путь к исходному аудио через официальный API, диагностические свойства первого такого клипа записываются в:

```text
%LOCALAPPDATA%\DavinciTrackVisualizer\tmp\clip_property_dump.txt
```

Настройки пользователя сохраняются в:

```text
%LOCALAPPDATA%\DavinciTrackVisualizer\settings.json
```

После изменения trim, позиции или метаданных клипов нужно снова выполнить `Создать / обновить визуализаторы`.

## Разработка

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Установка dev-версии в текущий Resolve:

```powershell
.\.venv\Scripts\python scripts\install_resolve_script.py
```

Поддерживаемый воспроизводимый путь release-сборки — запускаемый вручную GitHub Actions workflow в private-репозитории. Прямой запуск `scripts/build_release.py` является расширенным эквивалентом: он требует строго Python 3.12.10 на Windows или 3.12.13 на Linux, проверенную парную сборку FFmpeg/FFprobe и явные значения `--ffmpeg-license`, `--ffmpeg-version`, `--ffmpeg-source-url` и `--ffmpeg-source-sha256`. Одного наличия FFmpeg в `PATH` недостаточно. На Windows также нужно передать проверенные файлы через `--windows-libffi-license` и `--windows-openssl-license`; скрипт дополнительно проверяет изоляцию Python user site.

Лицензия проекта: [GNU GPL версии 3 или новее](../LICENSE), SPDX `GPL-3.0-or-later`.

DaVinci Resolve является товарным знаком Blackmagic Design Pty Ltd. Проект независимый и не аффилирован с Blackmagic Design.
