# Contratto dati e contabilità opzioni reali — V1

Data: 2026-10-21. Stato: `DESIGN_ONLY / NO_REAL_DATA_ACQUIRED`.
Governa il programma `REAL_OPTIONS_RESEARCH_PROGRAM_V1.md`.

## Identità degli strumenti

Mercato candidato iniziale: Deribit production, opzioni europee inverse BTC.
Hedge candidato: future inverso con scadenza corrispondente, solo se negoziato
e con metadati completi. Nessuna equivalenza presunta tra BTC, USD ed EUR.
Le opzioni USDC, ETH, combo e perpetual sono fuori V1.

Per ogni strumento preservare payload originale e metadati normalizzati:
venue, instrument ID, tipo inverse/linear, call/put, strike, expiry timestamp,
settlement currency, contract size, unità di quantità e prezzo, minimum amount,
tick size e relativa versione/intervallo di validità. Non derivare la scadenza
solo dal nome. Unità assenti o contraddittorie bloccano lo strumento.

I premi inverse sono quotati in BTC; le quantità opzioni e future hanno unità
diverse secondo le specifiche. La trasformazione della sensibilità delta in
quantità di future deve essere derivata e verificata in RO-03, non copiata dal
contratto sintetico della tesi. Il collateral BTC introduce rischio rispetto
a un obiettivo in EUR/USD che va riportato separatamente.

## Envelope degli eventi

Campi obbligatori: schema_version, source, connection_id, ingest_sequence,
channel, instrument_id, exchange_timestamp, receive_timestamp_utc,
receive_monotonic_ns, event_id, payload_hash, event_type e unità.
Timestamp non disponibili restano missing espliciti, mai ricostruiti come fatti.
Conservare precisione e semantica della fonte. Decisioni e join usano solo
eventi già ricevuti; clock rollback non modifica il tempo monotono.

Separare stream di quote, trade, indice, hedge, mark e provider greeks.
IV/greche devono riportare provider, metodo quando disponibile, timestamp,
unità e missingness. Mark, IV e greche sono stime; non sono fill o verità latenti.

## Ricostruzione del book

Book pubblico per livelli L2; canali 100ms/agg2, nessun canale raw autenticato.
Snapshot iniziale; delta applicabile solo se prev_change_id coincide con
l'ultimo change_id. Gap, conflitto o fuori ordine invalidano lo stato fino a
un nuovo snapshot. Non ricucire gap con forward-fill. Duplicati identici sono
idempotenti; stesso ID con payload diverso è un errore bloccante.

Registrare disconnect, reconnect, gap, overflow, throttling e scarti.
Distinguere connessione sana, ultima modifica della quote e freschezza delle
feature. Una quote invariata non prova da sola un feed interrotto.
Soglie di età, heartbeat, skew, latenza e retention sono `UNSET_BLOCKS_RO02`:
vanno congelate e motivate prima del pilot, non ottimizzate sul suo P&L.

## Esecuzione simulata

Buy all'ask e sell al bid, con cammino sui livelli e vincoli tick/size.
Profondità insufficiente produce fill parziale o rifiuto, non liquidità inventata.
Quote osservata al tempo decisionale non garantisce esecuzione istantanea:
RO-02/RO-03 devono specificare ritardo e gestione degli aggiornamenti intervenuti.
Il mid è un riferimento di valutazione. Dal solo L2 non si deduce priorità
maker né fill in coda. Niente fill garantiti a mark o ultimo trade.

Spread incluso nel prezzo di fill; fee e slippage aggiuntivo sono separati
per evitare doppio conteggio. Fee, delivery fee e margini devono essere
versionati dalle specifiche valide. Il future a scadenza non ha il funding
periodico del perpetual; restano basis, commissioni e collateral.
Un futuro ampliamento ai perpetual rende obbligatori eventi funding realizzati.

## Ledger

Numeraire primario BTC. Conversioni USD/EUR riportano prezzo, fonte, timestamp
e qualità; nessuna equivalenza tra profitto BTC e profitto EUR.
Registro append-only di ordini simulati, fill, cancellazioni, fee, cashflow,
posizioni, collateral, margine e settlement, con event_id deterministico.

Per evento: delta cash = cashflow contrattuale - fee + flussi esterni.
Equity = cash + valore netto delle posizioni, nella medesima unità.
Margine riservato limita il disponibile: non è una seconda perdita o fee.
Premio, payoff e variazioni di valore non devono essere addebitati due volte.
Per inverse futures il payoff non è il payoff lineare USD del sottostante.

Le specifiche Deribit aggiornate nel settembre 2026 descrivono dal 1 agosto
2026 il settlement ITM inverse in due eventi: conversione in future allo strike,
poi regolamento BTC del future. Il journal deve rappresentare entrambi,
anche quando il payoff netto coincide con la precedente formula cash.
Eventi OTM e ITM call/put devono essere verificati manualmente sulle specifiche.
Non si presume che ogni periodo storico usi la medesima convenzione.

Replay dello stesso journal deve produrre stesso stato e hash, senza doppio
addebito al reconnect. Decimal/quantizzazione esatta per valori contrattuali;
float solo per stime dichiarate e con tolleranze predefinite.

## Dati e licenze

Accesso pubblico senza account non autorizza redistribuzione o uso commerciale.
Manifest: fonte, URL documentazione, data consultazione, condizioni applicabili,
granularità, universo, periodi, versione adapter/schema e hash delle parti.
Rispettare allowlist, limiti API e backoff bounded; mai retry aggressivi.
Nessun endpoint privato, credenziale, ordine reale o costo.

Massive US è un dataset distinto: barre di trade qualificati, timezone ET e
disponibilità EOD. Assenza di barra significa assenza di trade qualificato,
non quote disponibile. Non colmare quei buchi come eseguibilità.

## Gate tecnici RO-01

| ID | Requisito | Evidenza richiesta |
|---|---|---|
| D01 | metadati e unità completi | fixture valide e rifiuto casi ambigui |
| D02 | replay L2 deterministico | snapshot, insert/update/delete, sorting |
| D03 | sequenza fail-closed | gap, duplice ID conflittuale, reconnect |
| D04 | disponibilità causale | join, skew, clock rollback e missingness |
| D05 | quote/trade/mark separati | schema e controlli negativi |
| D06 | fill conservativi | parziale, rifiuto, livelli, tick e size |
| D07 | ledger riconciliato | casi hand-calculated, fee una volta sola |
| D08 | settlement versionato | OTM/ITM call/put, eventi separati |
| D09 | idempotenza | doppio replay con identici hash e saldi |
| D10 | limiti e failure controllate | mock timeout, throttling, disk-full, malformed |
| D11 | sorgenti/licenze/versioni | manifest completo; ambiguità dichiarate |
| D12 | rete e scope | test offline, nessuna chiave/endpoint privato |

Fixture artificiali: massimo 20.000 eventi, 60 secondi CPU e 100 MB output.
Questi limiti non sono un disegno statistico né un test di efficacia finanziaria.
La chiusura RO-01 certifica infrastruttura tecnica, non raccolta reale,
profittabilità, superiorità su BS o prontezza al deployment.

Fonti: documentazione Deribit e Massive linkata nel programma V1. Le specifiche
economiche vanno riconfermate prima dell'implementazione dei relativi casi.
