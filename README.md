# E90 OS

Собственная мультимедийная оболочка для Android-магнитолы KSW в BMW E90 320i (2007).

## Как работать с проектом
1. Открой папку в **Claude Code** (терминал или десктоп).
2. Напиши: «Руководитель проекта, где мы и что дальше?» — агент project-manager прочитает план и раздаст задачи команде.

Команда, правила и структура — в [`CLAUDE.md`](CLAUDE.md).

## Структура
```
.claude/agents/   команда: руководитель проекта, продакт, UX, дизайнер, Kotlin, Android, CAN/OBD, железо, QA, автотесты
.claude/skills/   навыки дизайна под Android
docs/             ТЗ, навигация (NAVIGATION.md), железо, карта экранов, план, решения, проверки, фото магнитолы
design/prototype.html  кликабельный прототип «iDrive Heritage»: 7 экранов, правое меню, DEMO/«Нет данных» (открыть в браузере; стрелки+Enter = крутилка, Esc = назад)
design/reference/heritage/  референсы владельца (7 PNG), design/archive/ — прошлые варианты
third_party/      лицензии использованных наборов агентов (MIT)
```

## Текущий статус
Дизайн «iDrive Heritage» собран прототипом. На согласовании — структура APK и план источников данных: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). 
## Благодарности
Агенты и навыки основаны на открытых наборах (MIT):
- [VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents)
- [wshobson/agents](https://github.com/wshobson/agents)
Каждый агент дополнен разделом «Роль в проекте E90 OS».
