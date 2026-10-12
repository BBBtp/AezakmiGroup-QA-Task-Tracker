import type { Run } from './types'

// Illustrative local snapshot; no orchestrator, Tracker, DoQA or CI connection.
export const mockRuns: Run[] = [
  {
    "issueKey": "FRONT-174",
    "title": "Фильтры приложений: метки в списке",
    "state": "Передача остановлена",
    "stateKind": "blocked",
    "subtitle": "Один запуск от входных критериев до проверки передачи разработчику.",
    "startedAt": "08:56:00",
    "lastObservedAt": "09:11:18",
    "axisEndAt": "09:20:00",
    "signal": "подтверждён",
    "defaultRowId": "doqa",
    "lane": "design",
    "reason": "DoQA case ID не подтверждён",
    "nextStep": "Сверить числовой ID и статус planned",
    "recentEvent": "Условие передачи остановило запуск",
    "recentSource": "Tracker / DoQA",
    "recentTime": "09:11",
    "rows": [
      {
        "id": "run",
        "parentId": null,
        "kind": "group",
        "label": "Запуск FRONT-174",
        "detail": "15m 18s",
        "status": "Наблюдение остановлено на условии передачи.",
        "summary": "Выполнение дошло до проверки обязательного DoQA case ID. Следующие роли не начинали работу.",
        "source": "Локальный снимок запуска",
        "time": "08:56–09:11",
        "span": {
          "startAt": "08:56:00",
          "endAt": "09:11:18",
          "tone": "muted"
        }
      },
      {
        "id": "analyst",
        "parentId": "run",
        "kind": "group",
        "label": "Аналитик · критерии",
        "detail": "4m 02s",
        "status": "Этап завершён",
        "summary": "Критерии зафиксированы и переданы дизайнеру тестов.",
        "source": "Иллюстративный handoff",
        "time": "08:56–09:00",
        "span": {
          "startAt": "08:56:00",
          "endAt": "09:00:02",
          "tone": "green"
        }
      },
      {
        "id": "criteria",
        "parentId": "analyst",
        "kind": "event",
        "label": "Критерии получены",
        "detail": "08:57:14",
        "status": "Событие подтверждено",
        "summary": "Локальная запись содержит входные критерии задачи.",
        "source": "Tracker · локальная запись",
        "time": "08:57:14",
        "observedAt": "08:57:14",
        "pointTone": "green"
      },
      {
        "id": "handoff-a",
        "parentId": "analyst",
        "kind": "event",
        "label": "Передача дизайнеру тестов",
        "detail": "09:00:02",
        "status": "Передача зафиксирована",
        "summary": "Аналитик завершил шаг и передал критерии следующей роли.",
        "source": "Handoff · локальная запись",
        "time": "09:00:02",
        "observedAt": "09:00:02",
        "pointTone": "green"
      },
      {
        "id": "designer",
        "parentId": "run",
        "kind": "group",
        "label": "Дизайнер тестов · поиск сценария",
        "detail": "11m 16s",
        "status": "Этап дошёл до условия",
        "summary": "Найден кандидат на ручной сценарий, но обязательный числовой case ID со статусом planned не подтверждён.",
        "source": "Локальная запись роли",
        "time": "09:00–09:11",
        "span": {
          "startAt": "09:00:02",
          "endAt": "09:11:18",
          "tone": "green"
        }
      },
      {
        "id": "lookup",
        "parentId": "designer",
        "kind": "event",
        "label": "Поиск ручного сценария",
        "detail": "09:03:41",
        "status": "Событие подтверждено",
        "summary": "Поиск выполнен по критериям из handoff.",
        "source": "DoQA · иллюстративный поиск",
        "time": "09:03:41",
        "observedAt": "09:03:41",
        "pointTone": "green"
      },
      {
        "id": "candidate",
        "parentId": "designer",
        "kind": "event",
        "label": "Найден кандидат · совпадение неполное",
        "detail": "09:08:26",
        "status": "Кандидат найден",
        "summary": "Название похоже на нужный сценарий; числовой ID и статус planned в снимке отсутствуют.",
        "source": "DoQA · иллюстративный результат",
        "time": "09:08:26",
        "observedAt": "09:08:26",
        "pointTone": "green"
      },
      {
        "id": "doqa",
        "parentId": "designer",
        "kind": "gate",
        "label": "Условие · DoQA case ID",
        "recordType": "Условие передачи",
        "detail": "09:11:18",
        "status": "Передача остановлена",
        "summary": "Нет подтверждённого числового case ID со статусом planned. Передача разработчику пока не доказана.",
        "source": "Tracker / DoQA · локальный снимок",
        "time": "09:11:18",
        "observedAt": "09:11:18",
        "pointTone": "amber",
        "ref": "gate-front-174-doqa",
        "events": [
          [
            "Критерии получены",
            "08:57"
          ],
          [
            "Кандидат найден",
            "09:08"
          ],
          [
            "ID и статус planned не подтверждены",
            "09:11"
          ]
        ],
        "facts": [
          [
            "Ожидалось",
            "числовой case ID · planned"
          ],
          [
            "Наблюдалось",
            "кандидат без подтверждённого ID"
          ],
          [
            "Следующий шаг",
            "сверить ID и статус в DoQA"
          ]
        ],
        "payload": {
          "issueKey": "FRONT-174",
          "caseIds": [],
          "gate": "blocked"
        },
        "needsAttention": true
      },
      {
        "id": "developer",
        "parentId": "run",
        "kind": "pending",
        "label": "Разработчик · реализация",
        "detail": "ожидает",
        "status": "Ожидает передачи",
        "summary": "Этап не начался. Нет подтверждения, что условие DoQA выполнено.",
        "source": "Локальный снимок",
        "time": "—"
      },
      {
        "id": "review",
        "parentId": "run",
        "kind": "pending",
        "label": "Независимый review",
        "detail": "ожидает",
        "status": "Ожидает реализации",
        "summary": "Review не запускался в этом иллюстративном запуске.",
        "source": "Локальный снимок",
        "time": "—"
      },
      {
        "id": "ci",
        "parentId": "run",
        "kind": "pending",
        "label": "CI · проверка",
        "detail": "ожидает",
        "status": "Ожидает review",
        "summary": "CI не запускался в этом иллюстративном запуске.",
        "source": "Локальный снимок",
        "time": "—"
      }
    ]
  },
  {
    "issueKey": "FRONT-186",
    "title": "Проверка почтовых ящиков в интерфейсе",
    "state": "Проверка не пройдена",
    "stateKind": "failed",
    "subtitle": "Реализация прошла review; сценарий TC-1709 завершился с ошибкой.",
    "startedAt": "06:43:00",
    "lastObservedAt": "07:26:12",
    "axisEndAt": "07:27:00",
    "signal": "подтверждён",
    "defaultRowId": "failure",
    "lane": "check",
    "reason": "TC-1709 завершился с ошибкой",
    "nextStep": "Классифицировать падение перед повтором",
    "recentEvent": "Сценарий CI завершился с ошибкой",
    "recentSource": "CI / TC-1709",
    "recentTime": "07:26",
    "rows": [
      {
        "id": "run",
        "parentId": null,
        "kind": "group",
        "label": "Запуск FRONT-186",
        "detail": "43m 12s",
        "status": "Проверка завершилась ошибкой",
        "summary": "Следующий шаг — классифицировать падение до повтора.",
        "source": "Локальный снимок запуска",
        "time": "06:43–07:26",
        "span": {
          "startAt": "06:43:00",
          "endAt": "07:26:12",
          "tone": "muted"
        }
      },
      {
        "id": "review",
        "parentId": "run",
        "kind": "group",
        "label": "Независимый review",
        "detail": "8m 41s",
        "status": "Review пройден",
        "summary": "Независимый verdict зафиксирован.",
        "source": "Review · иллюстративная запись",
        "time": "06:43–06:51",
        "span": {
          "startAt": "06:43:00",
          "endAt": "06:51:41",
          "tone": "green"
        }
      },
      {
        "id": "verdict",
        "parentId": "review",
        "kind": "event",
        "label": "Verdict принят",
        "detail": "06:51:41",
        "status": "Событие подтверждено",
        "summary": "Review разрешил передачу в CI.",
        "source": "Review · локальная запись",
        "time": "06:51:41",
        "observedAt": "06:51:41",
        "pointTone": "green"
      },
      {
        "id": "ci",
        "parentId": "run",
        "kind": "group",
        "label": "CI · TC-1709",
        "detail": "21m 08s",
        "status": "CI завершился ошибкой",
        "summary": "Сценарий TC-1709 упал. Тип падения пока не классифицирован.",
        "source": "CI · иллюстративная запись",
        "time": "07:05–07:26",
        "span": {
          "startAt": "07:05:04",
          "endAt": "07:26:12",
          "tone": "muted"
        }
      },
      {
        "id": "start-ci",
        "parentId": "ci",
        "kind": "event",
        "label": "Проверка запущена",
        "detail": "07:05:04",
        "status": "CI запущен",
        "summary": "Проверка выполнялась на указанном локальном commit.",
        "source": "CI · локальная запись",
        "time": "07:05:04",
        "observedAt": "07:05:04",
        "pointTone": "green"
      },
      {
        "id": "failure",
        "parentId": "ci",
        "kind": "gate",
        "label": "TC-1709 · ошибка",
        "recordType": "Проверка CI",
        "detail": "07:26:12",
        "status": "Проверка не пройдена",
        "summary": "Сценарий завершился с ошибкой. До повтора нужно отделить ошибку продукта от нестабильности теста.",
        "source": "CI / TC-1709 · локальный снимок",
        "time": "07:26:12",
        "observedAt": "07:26:12",
        "pointTone": "red",
        "ref": "check-front-186-tc1709",
        "events": [
          [
            "Review пройден",
            "06:51"
          ],
          [
            "CI запущен",
            "07:05"
          ],
          [
            "TC-1709 завершился с ошибкой",
            "07:26"
          ]
        ],
        "facts": [
          [
            "Сценарий",
            "TC-1709"
          ],
          [
            "Результат",
            "failed"
          ],
          [
            "Следующий шаг",
            "классифицировать падение"
          ]
        ],
        "payload": {
          "issueKey": "FRONT-186",
          "caseIds": [
            1709
          ],
          "check": "failed"
        },
        "needsAttention": true
      }
    ]
  },
  {
    "issueKey": "FRONT-150",
    "title": "Назначение приложения: API-контракт",
    "state": "Сигнал устарел",
    "stateKind": "blocked",
    "subtitle": "Последний heartbeat не позволяет подтвердить текущую активность агента.",
    "startedAt": "08:39:00",
    "lastObservedAt": "08:45:09",
    "axisEndAt": "09:31:00",
    "signal": "устарел",
    "defaultRowId": "heartbeat",
    "lane": "implementation",
    "reason": "Heartbeat устарел",
    "nextStep": "Сверить процесс и последний сигнал",
    "recentEvent": "Последний heartbeat; затем нет наблюдений",
    "recentSource": "Локальный state",
    "recentTime": "08:45",
    "rows": [
      {
        "id": "run",
        "parentId": null,
        "kind": "group",
        "label": "Запуск FRONT-150",
        "detail": "сигнал 08:45",
        "status": "Текущий процесс неизвестен",
        "summary": "Из последнего heartbeat нельзя выводить, что агент продолжает работу.",
        "source": "Локальный state · иллюстративный",
        "time": "08:45:09",
        "span": {
          "startAt": "08:39:00",
          "endAt": "08:45:09",
          "tone": "muted"
        }
      },
      {
        "id": "handoff",
        "parentId": "run",
        "kind": "event",
        "label": "Передача в реализацию",
        "detail": "08:39:00",
        "status": "Передача зафиксирована",
        "summary": "Задача передана роли разработчика.",
        "source": "Handoff · локальная запись",
        "time": "08:39:00",
        "observedAt": "08:39:00",
        "pointTone": "green"
      },
      {
        "id": "developer",
        "parentId": "run",
        "kind": "group",
        "label": "Разработчик · последняя активность",
        "detail": "до 08:45",
        "status": "Активность была подтверждена",
        "summary": "В интервале 08:39–08:45 есть наблюдаемые события; после него данных нет.",
        "source": "Heartbeat · локальная запись",
        "time": "08:39–08:45",
        "span": {
          "startAt": "08:39:00",
          "endAt": "08:45:09",
          "tone": "green"
        }
      },
      {
        "id": "heartbeat",
        "parentId": "developer",
        "kind": "gate",
        "label": "Heartbeat · истёк срок свежести",
        "recordType": "Сигнал свежести",
        "detail": "08:45:09",
        "status": "Сигнал устарел",
        "summary": "Последний heartbeat получен в 08:45. На снимке 09:31 текущий процесс неизвестен.",
        "source": "Локальный state",
        "time": "08:45:09",
        "observedAt": "08:45:09",
        "pointTone": "amber",
        "ref": "signal-front-150-heartbeat",
        "events": [
          [
            "Передача в реализацию",
            "08:39"
          ],
          [
            "Последний heartbeat",
            "08:45"
          ],
          [
            "Снимок без нового сигнала",
            "09:31"
          ]
        ],
        "facts": [
          [
            "Последний сигнал",
            "08:45:09"
          ],
          [
            "Снимок",
            "09:31"
          ],
          [
            "Текущая активность",
            "неизвестна"
          ]
        ],
        "payload": {
          "issueKey": "FRONT-150",
          "lastHeartbeat": "08:45:09",
          "status": "stale"
        },
        "needsAttention": true
      },
      {
        "id": "review",
        "parentId": "run",
        "kind": "pending",
        "label": "Review",
        "detail": "неизвестно",
        "status": "Нет подтверждения",
        "summary": "Нельзя утверждать, что review начался или завершился.",
        "source": "Локальный снимок",
        "time": "—"
      }
    ]
  },
  {
    "issueKey": "FRONT-187",
    "title": "Сценарии фильтрации: связь с критериями",
    "state": "Свежий сигнал на снимке",
    "stateKind": "active",
    "subtitle": "В локальном снимке есть недавнее событие дизайнера тестов.",
    "startedAt": "09:17:00",
    "lastObservedAt": "09:31:00",
    "axisEndAt": "09:33:00",
    "signal": "свежий в снимке",
    "defaultRowId": "heartbeat",
    "lane": "design",
    "reason": "Свежий сигнал на момент снимка",
    "nextStep": "Дождаться подтверждённой передачи",
    "recentEvent": "Heartbeat совпал со временем снимка",
    "recentSource": "Локальный state",
    "recentTime": "09:31",
    "rows": [
      {
        "id": "run",
        "parentId": null,
        "kind": "group",
        "label": "Запуск FRONT-187",
        "detail": "14m",
        "status": "Свежий сигнал в снимке",
        "summary": "Дизайнер тестов работал над связью сценариев с критериями. Последнее событие совпадает со временем снимка.",
        "source": "Локальный снимок запуска",
        "time": "09:17–09:31",
        "span": {
          "startAt": "09:17:00",
          "endAt": "09:31:00",
          "tone": "muted"
        }
      },
      {
        "id": "handoff",
        "parentId": "run",
        "kind": "event",
        "label": "Критерии переданы",
        "detail": "09:17:00",
        "status": "Передача зафиксирована",
        "summary": "Критерии получены дизайнером тестов.",
        "source": "Handoff · локальная запись",
        "time": "09:17:00",
        "observedAt": "09:17:00",
        "pointTone": "green"
      },
      {
        "id": "designer",
        "parentId": "run",
        "kind": "group",
        "label": "Дизайнер тестов · связывает сценарии",
        "detail": "до 09:31",
        "status": "Активность наблюдалась до снимка",
        "summary": "Последовательность событий продолжается до 09:31. За пределами снимка текущее состояние неизвестно.",
        "source": "Локальная запись роли",
        "time": "09:17–09:31",
        "span": {
          "startAt": "09:17:00",
          "endAt": "09:31:00",
          "tone": "green"
        }
      },
      {
        "id": "match",
        "parentId": "designer",
        "kind": "event",
        "label": "Критерий связан со сценарием",
        "detail": "09:24:08",
        "status": "Событие подтверждено",
        "summary": "В иллюстративном снимке создана связь критерия и сценария.",
        "source": "Локальная запись дизайнера тестов",
        "time": "09:24:08",
        "observedAt": "09:24:08",
        "pointTone": "green"
      },
      {
        "id": "heartbeat",
        "parentId": "designer",
        "kind": "event",
        "label": "Последний heartbeat",
        "detail": "09:31:00",
        "status": "Свежий сигнал в снимке",
        "summary": "Heartbeat получен в 09:31, когда сделан снимок. Это не утверждение о состоянии после 09:31.",
        "source": "Локальный state",
        "time": "09:31:00",
        "observedAt": "09:31:00",
        "pointTone": "green",
        "ref": "signal-front-187-heartbeat",
        "events": [
          [
            "Критерии переданы",
            "09:17"
          ],
          [
            "Связь со сценарием записана",
            "09:24"
          ],
          [
            "Heartbeat в момент снимка",
            "09:31"
          ]
        ],
        "facts": [
          [
            "Последний сигнал",
            "09:31:00"
          ],
          [
            "Время снимка",
            "09:31:00"
          ],
          [
            "После снимка",
            "состояние неизвестно"
          ]
        ],
        "payload": {
          "issueKey": "FRONT-187",
          "lastHeartbeat": "09:31:00",
          "status": "active_at_snapshot"
        }
      },
      {
        "id": "developer",
        "parentId": "run",
        "kind": "pending",
        "label": "Разработчик · следующая роль",
        "detail": "ожидает",
        "status": "Ожидает передачи",
        "summary": "Передача следующей роли ещё не зафиксирована.",
        "source": "Локальный снимок",
        "time": "—"
      }
    ]
  }
]
