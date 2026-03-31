# Server Event Handler Refactor

## Cel

Uproscic obsluge websocketowych eventow w serwerze przez rozdzielenie:

- transportu i lifecycle polaczenia,
- parsowania ramek sieciowych,
- routingu eventow,
- logiki domenowej agentow, taskow i process managera.

Docelowo `server.py` ma byc cienkim miejscem integracji FastAPI, a nie glownym miejscem logiki eventowej.
Punktem wyjscia ma byc istniejaca wspolna warstwa `shared/`, a nie nowy lokalny framework handlerow tylko dla serwera.

## Obecny stan

Aktualnie wspolna warstwa eventow juz istnieje w `shared/`, ale serwer wykorzystuje ja tylko czesciowo, a glowny routing i skutki uboczne sa skupione w `server.py`.

Najbardziej widoczne symptomy:

- `/ws` obsluguje handshake agenta, heartbeat, task output, task status i process screenshot w jednym `match`.
- frontendowa sesja websocket tez ma osobny `match` dla komend i watcherow.
- `shared.network.events.parse(...)` juz potrafi sparsowac event na podstawie wspolnego rejestru typow.
- serwerowy `NetworkEventHandler` duplikuje czesc tej odpowiedzialnosci i nadal nie jest realnym handlerem domenowym.
- `tasks/` ma juz wlasne `db`, `dispatcher` i `service`, ale eventy taskowe nadal zyja poza domena taskow.

## Rekomendowany kierunek

### 1. Oprzec parser na shared, nie tworzyc nowego lokalnego parsera

Nie traktowac obecnego serwerowego `NetworkEventHandler` jako wspolnej bazy dla domen.
Wspolna odpowiedzialnosc transportowa juz istnieje w `shared`:

- `shared.network.events.REGISTRY`,
- `shared.network.events.register_event(...)`,
- `shared.network.events.parse(...)`,
- `shared.core.event_handler.EventHandler`.

Rekomendacja:

- uzywac `shared.network.events.parse(...)` jako podstawowego parsera po obu stronach,
- zachowac serwerowy i agentowy `NetworkEventHandler` tylko jako klasy domenowe lub adaptory do lokalnego busa,
- nie dublowac lokalnie logiki wyboru klasy eventu po `type`.

To pozwala wykorzystac realna wspolna warstwe, ktora juz teraz laczy agenta i serwer.

### 2. Wprowadzic cienkie sesje websocketowe

W serwerze sa realnie dwa rozne przeplywy:

- agent websocket session,
- frontend websocket session.

Kazdy z nich powinien miec wlasny runner lub session handler odpowiedzialny tylko za:

- odbior wiadomosci,
- parsowanie eventu,
- wywolanie routera,
- obsluge disconnect i cleanup.

Przykladowe moduly:

- `vm_agent_server/src/network/agent_session.py`
- `vm_agent_server/src/network/frontend_session.py`

### 3. Routing eventow rozdzielic po kierunku i domenie

Nie budowac jednego wielkiego `NetworkEventHandler` dla wszystkiego.
Lepszy podzial to dwa poziomy:

- router per kanal lub per source,
- handlery domenowe podpinane do routera.

#### Agent -> Server

Eventy przychodzace od agenta powinny byc dzielone na:

- `AgentLifecycleEventHandler`
  - handshake
  - heartbeat
  - rejestracja i rozlaczenie agenta
  - walidacja hosta i auth result
- `TaskAgentEventHandler`
  - task_output
  - task_status
  - domkniecie pipeline advance
- `ProcessMonitoringEventHandler`
  - process_screenshot
  - w przyszlosci inne eventy process/window telemetry

#### Frontend -> Server -> Agent

Komendy frontendowe warto rozdzielic na:

- `AgentCommandHandler`
  - start_program
  - start_monitored_process
  - create_session
  - capture_process_screenshot
- `ProcessWatchSubscriptionHandler`
  - watch_process_manager
  - unwatch_process_manager
  - cleanup watcherow

### 4. Preferowac dziedziczenie po shared EventHandler tylko tam, gdzie daje wartosc

Twoja intuicja o `TaskNetworkHandler` jest dobra na poziomie domeny, ale nie warto wciskac wszystkiego w jedno drzewo klas typu:

- `BaseNetworkHandler`
- `TaskNetworkHandler`
- `AgentNetworkHandler`
- `ProcessNetworkHandler`

jesli ta baza ma sluzyc tylko temu, zeby wszystkie klasy mialy metode `handle`.

Rekomendacja:

- potraktowac `shared.core.event_handler.EventHandler` jako istniejacy bazowy kontrakt,
- rozszerzac go tam, gdzie lokalny handler rzeczywiscie ma sens jako adapter do domeny lub busa,
- mapowanie typow eventow do konkretnych handlerow robic jawnie po stronie serwera,
- zbudowac router, ktory deleguje po `event.type`,
- wspolne zaleznosci przekazywac przez jawny kontekst, a nie przez szeroka klase bazowa.

Dziedziczenie ma sens tylko wtedy, gdy rzeczywiscie wspoldzielisz:

- walidacje authenticated agent,
- wysylke odpowiedzi do socketu,
- standardowy error handling,
- albo helpery dla lifecycle danego kanalu.

### 5. Kladc handlery przy domenach, nie w jednym worku

Poniewaz repo juz ma podzial domenowy, najlepszy efekt da ulozenie handlerow blisko logiki, ktorej dotycza.

Rekomendowany uklad:

- `vm_agent_server/src/network/router.py`
- `vm_agent_server/src/network/context.py`
- `vm_agent_server/src/network/agent_session.py`
- `vm_agent_server/src/network/frontend_session.py`
- `vm_agent_server/src/agents/network_handler.py`
- `vm_agent_server/src/tasks/network_handler.py`
- `vm_agent_server/src/services/process_monitoring/network_handler.py`

Parser pozostaje wspolny w `shared.network.events.parse(...)`.

Jesli nie chcesz teraz dodawac nowego katalogu `agents/`, sensowny wariant przejsciowy to:

- `vm_agent_server/src/agent_network_handler.py`
- `vm_agent_server/src/tasks/network_handler.py`
- `vm_agent_server/src/process_monitoring_network_handler.py`

Ale docelowo domenowy katalog jest czytelniejszy.

## Proponowany kontrakt

Najprostsza uzyteczna forma bez nadmiarowej abstrakcji to zachowac istniejacy kontrakt z `shared`, a nad nim dolozyc kontekst serwera:

```python
from dataclasses import dataclass
from fastapi import WebSocket
from shared.core.event_handler import EventHandler


@dataclass(slots=True)
class NetworkHandlerContext:
    ws: WebSocket
    agent_runtime: object
    registry_db: object
    task_service: object
    task_db: object
    telemetry_db: object
    frontend_snapshot_event: object
    user_service: object | None = None
    session: object | None = None
    client_id: str | None = None
    authenticated: bool = False


class EventHandler:
  ...
```

Nad tym dwa routery:

- `AgentEventRouter`
- `FrontendEventRouter`

Kazdy router ma slownik:

```python
{
    "handshake": lifecycle_handler,
    "heartbeat": lifecycle_handler,
    "task_output": task_handler,
    "task_status": task_handler,
}
```

To jest prostsze od kaskady `match case` w `server.py`, a jednoczesnie nie robi niepotrzebnego frameworka.
Kluczowe jest to, ze parser i typowanie eventow pochodza ze wspolnej warstwy, a nie z lokalnej implementacji serwera.

## Granice odpowiedzialnosci

### server.py

Powinien zostac odpowiedzialny za:

- tworzenie singletonow aplikacyjnych,
- rejestracje routerow HTTP,
- podpiecie websocket endpointow,
- bootstrap sesji websocket,
- lifecycle aplikacji.

Nie powinien zostac odpowiedzialny za:

- szczegoly handshake agenta,
- aktualizacje task status,
- obsluge screenshot eventow,
- logike watcherow process managera.

### handlers domenowe

Powinny robic skutki uboczne w swojej domenie:

- update DB,
- broadcast do frontendow,
- delegacja do services,
- wysylka komendy do agenta.

### router websocketowy

Powinien robic tylko:

- sprawdzenie czy typ eventu jest znany,
- delegacje do odpowiedniego handlera,
- ewentualnie wspolny error boundary i audit log.

## Docelowy podzial eventow

### AgentLifecycleEventHandler

Odpowiada za:

- handshake,
- authorize_agent,
- hostname verification,
- register_agent,
- heartbeat merge,
- status online offline,
- frontend snapshot trigger przy zmianie stanu.

To jest jeden spójny obszar: tozsamosc i stan polaczenia agenta.

### TaskNetworkHandler

Odpowiada za:

- task_output,
- task_status,
- update `TaskDB`,
- broadcast task event,
- `TaskService.advance_pipeline(...)`.

To naturalnie pasuje do `tasks/`, bo juz tam jest logika zadan i pipeline.

### ProcessMonitoringNetworkHandler

Odpowiada za:

- process_screenshot,
- watch_process_manager,
- unwatch_process_manager,
- window tracking on/off,
- utrzymanie relacji watcher -> agent.

To jest jedna poddomena: obserwacja i strumieniowanie stanu procesow oraz okien.

### AgentCommandHandler

Odpowiada za frontendowe komendy delegowane do agenta:

- start_program,
- start_monitored_process,
- create_session,
- capture_process_screenshot.

To jest inny typ odpowiedzialnosci niz lifecycle, bo nie opisuje stanu polaczenia, tylko command forwarding.

## Rekomendowana kolejnosc wdrozenia

### Etap 1

Przepiac serwer z lokalnego parsera w `vm_agent_server/src/network_event_handler.py` na wspolne `shared.network.events.parse(...)`.

Efekt:

- serwer i agent opieraja sie na tym samym rejestrze eventow,
- znika dublowanie logiki parsera,
- `NetworkEventHandler` moze przestac udawac ogolny parser i stac sie realnym adapterem domenowym albo zostac usuniety po migracji.

### Etap 2

Wydzielic `TaskNetworkHandler` do `tasks/network_handler.py`.

To najlepszy pierwszy krok, bo:

- obsluguje mala i dobrze wydzielona grupe eventow,
- ma juz gotowe zaleznosci domenowe,
- od razu zmniejsza centralny `match` w `server.py`.

### Etap 3

Wydzielic `AgentLifecycleEventHandler`.

To najwrazliwsza czesc, bo dotyka auth, register i reconnect, wiec warto robic ja po taskach.

### Etap 4

Wydzielic `ProcessMonitoringNetworkHandler` oraz frontendowe komendy i watchery.

### Etap 5

Wprowadzic osobne session runnery i cienki router eventow.

## Decyzje architektoniczne

### Co rekomenduje teraz

1. Zostawic jeden parser formatow eventow we wspolnej warstwie `shared`.
2. Rozdzielic routing na `AgentEventRouter` i `FrontendEventRouter`.
3. Dla domen tworzyc handlery przy domenach, na pewno `tasks/network_handler.py`.
4. Wykorzystac istniejacy `shared.core.event_handler.EventHandler`, ale nie budowac nad nim szerokiej hierarchii tylko dla samej abstrakcji.

### Czego nie rekomenduje teraz

1. Jednego wspolnego `NetworkEventHandler` dla wszystkich eventow serwera.
2. Przenoszenia calej logiki do jednego nowego katalogu `network_handlers/`, bo to oslabia domenowy podzial repo.
3. Szerokiej klasy bazowej, ktora bedzie tylko workiem helperow i zaleznosci.

## Minimalny wariant docelowy

Jesli chcesz zrobic to najmniejszym kosztem, ale zgodnie z dobra architektura, to docelowy minimalny zestaw jest taki:

- parser eventow ze wspolnej warstwy `shared`,
- `TaskNetworkHandler` w `tasks/`,
- `AgentLifecycleEventHandler` przy logice agenta,
- cienkie helpery do command forwarding i watcherow,
- `server.py` ograniczony do endpointow i skladania zaleznosci.

To da duzy zysk architektoniczny bez przepisywania wszystkiego naraz.