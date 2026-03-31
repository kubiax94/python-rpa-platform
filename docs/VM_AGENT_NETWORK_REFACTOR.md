# VM Agent Network Refactor

## Cel

Uporzadkowac obsluge eventow sieciowych w `vm_agent` tak, zeby agent mial ten sam ogolny wzorzec co serwer:

- wspolny parser eventow z `shared/`,
- cienka warstwa transportu i reconnect,
- osobny runner sesji websocketowej,
- routing eventow po typie,
- male handlery domenowe zamiast jednego `NetworkEventHandler`.

Celem nie jest przepisanie calego agenta, tylko wyznaczenie granic, zeby refaktor nie rozlal sie na task runner, process manager i logike Windows service.

## Obecny stan

Aktualnie `vm_agent` ma jedna scentralizowana sciezke dla eventow przychodzacych z serwera:

- `vm_agent/src/network/agent_connection.py` utrzymuje websocket i reconnect loop,
- `vm_agent/src/network/agent_client.py` skleja transport, parser, handshake callback i event bus,
- `vm_agent/src/network/network_event_handler.py` robi jednoczesnie parsowanie i dispatch po `event.type`,
- logika domenowa jest uruchamiana posrednio przez `EventEmitter`.

Najwazniejsze symptomy obecnego ukladu:

- parser opiera sie na `NetworkEvent.model_validate_json(...)`, a nie na wspolnym `shared.network.events.parse(...)`,
- `NetworkEventHandler` ma duzy `match` dla roznych domen: auth, taski, sesje, process monitoring,
- `AgentClient` laczy za duzo odpowiedzialnosci: lifecycle polaczenia, handshake, parser, bus wiring,
- kontrakt obslugi eventow po stronie agenta nie jest jeszcze tak czytelny jak po stronie serwera.

## Ograniczenia refaktoru

Ten refaktor powinien zachowac trzy rzeczy:

1. `AgentConnection` pozostaje niskopoziomowa warstwa websocket i reconnect.
2. Domenowa logika wykonawcza pozostaje poza warstwa `network/`.
3. Wspolny format eventow i modele danych sa nadal definiowane w `shared/`.

To oznacza, ze nie chcemy:

- przenosic logiki task execution do `network/`,
- budowac nowego lokalnego frameworka eventowego tylko dla agenta,
- mieszac reconnect policy z domenowym dispatchingiem.

## Docelowy wzorzec

### 1. Wspolny parser z `shared`

Po stronie agenta parser powinien byc taki sam jak po stronie serwera:

- `shared.network.events.parse(...)`

Rekomendacja:

- usunac lokalna odpowiedzialnosc parsera z `vm_agent/src/network/network_event_handler.py`,
- traktowac parser jako element wspolnej warstwy kontraktu, nie lokalnej implementacji agenta,
- zachowac lokalne handlery tylko dla routingu i adaptacji do domeny.

To daje jedna definicje mapowania `type -> event class` po obu stronach.

### 2. Osobny runner sesji agenta

Tak jak w serwerze, warstwa sesji powinna byc oddzielona od FastAPI albo innego hosta transportu. W `vm_agent` session runner powinien odpowiadac tylko za:

- odbior surowej ramki z `AgentConnection`,
- parsowanie eventu przez `shared.network.events.parse(...)`,
- wywolanie routera,
- obsluge disconnect i cleanup lokalnego stanu sesji.

Przykladowy modul:

- `vm_agent/src/network/agent_session.py`

`AgentConnection` nie powinien znac handlerow domenowych. Powinien znac tylko klienta lub callback do przetwarzania ramki.

### 3. Cienki router eventow

Po stronie agenta warto wprowadzic prosty router podobny do serwerowego `EventRouter`, czyli:

- rejestracja listy `event_types` dla handlera,
- `dispatch(event, context)`,
- brak wiedzy o transporcie domenowym poza delegacja.

Przykladowy modul:

- `vm_agent/src/network/event_router.py`

Ten router nie powinien robic nic wiecej niz mapowanie `event.type` do handlera.

### 4. Male handlery domenowe

Monolityczny `NetworkEventHandler` warto rozbic na male komponenty wedlug odpowiedzialnosci.

#### AgentLifecycleHandler

Zakres:

- `handshake`,
- `auth_result`,
- lokalny stan inicjalizacji sesji,
- ewentualne sygnaly o gotowosci albo bledzie auth.

To jest jedna odpowiedzialnosc: stan sesji i tozsamosc polaczenia z serwerem.

#### AgentCommandHandler

Zakres:

- `start_program`,
- `start_monitored_process`,
- `create_session`.

To jest grupa eventow opisujacych komendy wykonawcze przychodzace z serwera.

#### TaskCommandHandler

Zakres:

- `execute_task`,
- `cancel_task`.

Te eventy juz dzis dotykaja task execution, wiec dobrze wydzielaja sie jako osobna domena.

#### ProcessMonitoringCommandHandler

Zakres:

- `capture_process_screenshot`,
- `set_window_tracking`.

To jest osobna poddomena zwiazana z process/window monitoringiem.

## Rekomendowana struktura plikow

Minimalny, czytelny uklad podobny do serwera:

- `vm_agent/src/network/agent_connection.py`
- `vm_agent/src/network/agent_client.py`
- `vm_agent/src/network/agent_session.py`
- `vm_agent/src/network/event_router.py`
- `vm_agent/src/network/context.py`
- `vm_agent/src/agents/lifecycle_handler.py`
- `vm_agent/src/agents/command_handler.py`
- `vm_agent/src/tasks/network_handler.py`
- `vm_agent/src/process_monitoring/network_handler.py`

Jesli chcesz mniejszego pierwszego kroku, przejsciowo mozna zostac przy plikach w `vm_agent/src/network/`, ale docelowo lepiej polozyc handlery przy domenach, tak jak po stronie serwera.

## Proponowany kontrakt

Po stronie agenta nie trzeba kopiowac calej architektury serwera 1:1. Wystarczy prosty wspolny wzorzec:

```python
from dataclasses import dataclass


@dataclass(slots=True)
class AgentSessionContext:
    connection: object
    client_id: str
    initialized: bool
    bus: object
    config: object


class AgentEventHandlerProtocol:
    event_types: tuple[str, ...]

    async def handle(self, event, context) -> None:
        ...
```

W praktyce kontekst mozna potem rozszerzyc o:

- callbacks do `send_event`,
- dostep do process managera,
- dostep do task runtime,
- stan auth albo bootstrap.

Wazne jest to, zeby zaleznosci byly jawne, a nie zaszyte w jednym handlerze i globalnym busie.

## Granice odpowiedzialnosci

### AgentConnection

Powinien pozostac odpowiedzialny za:

- otwarcie websocketu,
- zamkniecie websocketu,
- wysylke ramek,
- read loop,
- reconnect policy,
- mapowanie bledow transportowych na status polaczenia.

Nie powinien odpowiadac za:

- parsowanie eventow biznesowych,
- routing po `event.type`,
- handshake flow,
- delegacje do task runnera albo process managera.

### AgentSession

Powinien odpowiadac za:

- parsowanie ramek,
- routing eventow,
- utrzymanie stanu sesji,
- kontrolowany cleanup po disconnect.

Nie powinien odpowiadac za:

- low-level reconnect,
- szczegoly wykonania komend domenowych.

### Handlery domenowe

Powinny odpowiadac za:

- mapowanie eventu na wywolanie domeny,
- walidacje danych wejscia specyficzna dla domeny,
- ewentualna emisje lokalnych eventow domenowych, jesli dalej chcesz utrzymac `EventEmitter`.

Nie powinny odpowiadac za:

- zarzadzanie websocketem,
- reconnect loop,
- parsowanie surowych ramek JSON.

## Relacja do EventEmitter

`EventEmitter` nie musi zniknac w pierwszym etapie.

Najbezpieczniejszy wariant przejsciowy:

- session runner parsuje i routuje event,
- handler domenowy zamienia event sieciowy na wywolanie lokalnej domeny,
- jesli obecna domena nadal jest oparta na busie, handler emituje odpowiedni lokalny event.

To pozwala rozdzielic transport od dispatchingu bez jednoczesnego przepisywania calej wewnetrznej orkiestracji agenta.

Czyli:

- najpierw odchudzamy `network/`,
- dopiero potem, jesli bedzie sens, redukujemy zaleznosc od `EventEmitter`.

## Docelowy przeplyw

Docelowo przeplyw powinien wygladac tak:

1. `AgentConnection` odbiera surowy websocket frame.
2. `AgentSession` parsuje frame przez `shared.network.events.parse(...)`.
3. `EventRouter` wybiera handler po `event.type`.
4. Handler domenowy wykonuje akcje albo emituje lokalny event domenowy.
5. Odpowiedz do serwera, jesli potrzebna, wychodzi przez jawny callback lub adapter w kontekscie sesji.

To jest ten sam ogolny schemat, ktory juz dziala po stronie serwera.

## Rekomendowana kolejnosc wdrozenia

### Etap 1

Wydzielic parser z `NetworkEventHandler` i przepiac `AgentClient.process(...)` na `shared.network.events.parse(...)`.

Efekt:

- agent i serwer korzystaja z tego samego parsera,
- znika najprostsza duplikacja kontraktu eventow.

### Etap 2

Wprowadzic `EventRouter` i nowy cienki `AgentSession` bez zmiany domenowych skutkow ubocznych.

Efekt:

- `AgentClient` przestaje byc miejscem, gdzie miesza sie transport i dispatch,
- nadal mozna pod spodem emitowac na bus tak jak dzis.

### Etap 3

Rozbic `NetworkEventHandler` na:

- lifecycle,
- commands,
- task,
- process monitoring.

Na tym etapie mozna jeszcze utrzymac przejsciowo `EventEmitter` jako adapter do starej domeny.

### Etap 4

Wydzielic jawne konteksty zaleznosci dla handlerow i sesji.

Efekt:

- mniej ukrytych zaleznosci,
- prostsze testy jednostkowe,
- mniejsza presja na jedna klase bazowa.

### Etap 5

Dopiero po ustabilizowaniu warstwy `network/` rozwazac, czy warto ograniczac role `EventEmitter` w calym agencie.

## Czego nie rekomenduje teraz

1. Przepisywania od razu calego `agent_client.py` i domen wykonawczych w jednym kroku.
2. Budowania rozbudowanej hierarchii klas bazowych typu `BaseNetworkHandler` tylko po to, zeby wszystkie klasy mialy `handle(...)`.
3. Przenoszenia logiki reconnect z `AgentConnection` do handlerow.
4. Usuwania `EventEmitter` zanim transport i routing beda rozdzielone.

## Minimalny wariant docelowy

Jesli celem jest pierwszy sensowny etap bez refaktoru bez granic, to minimalny wariant jest taki:

- parser z `shared.network.events.parse(...)`,
- `AgentSession` jako cienki runner,
- prosty `EventRouter`,
- rozbicie `NetworkEventHandler` przynajmniej na lifecycle i command/task/process handlers,
- tymczasowe zachowanie `EventEmitter` jako wewnetrznego adaptera domenowego.

To daje ten sam kierunek architektoniczny co w `vm_agent_server`, ale bez wymuszania jednoczesnej przebudowy calego agenta.