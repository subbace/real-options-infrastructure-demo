# Programma di ricerca su opzioni reali — V1

Data di efficacia: 2026-10-21, Europe/Rome.

Stato: `RO-00_DOCUMENTARY_TRANSITION`; nessun risultato nuovo.

## Obiettivo e autorità

L'utente ha concluso e discusso la tesi e ha autorizzato l'avvio di un nuovo
programma. L'obiettivo è costruire un laboratorio riproducibile per confrontare
strategie di copertura su opzioni realmente negoziate, con informazioni
osservabili, esecuzione e contabilità verificabili, e test successivi su dati
nuovi. Il budget iniziale per sviluppo, dati e calcolo è zero euro.

Il patrimonio della tesi è una base di conoscenza e di software da verificare;
il nuovo obiettivo non azzera la storia scientifica né rende nuovi i campioni
già esaminati. Nessuna superiorità o affidabilità economica è presupposta.

Questo documento governa il programma post-tesi. Completion Contract V3 resta
il contratto storico della tesi. Le sue scadenze universitarie di agosto e
settembre 2026, il budget della vecchia ricerca post-C-05 e il vincolo di
vittoria entro agosto per la raccolta dati non governano nuovi blocchi RO.
Anche il vecchio puntatore obbligatorio alla residual search è storico.
Nessun limite viene rimosso retroattivamente e nessun esito viene cambiato.

Restano vincolanti causalità, SPENT, protocolli precommitted, distinzione tra
FULL e FAST/debug, conservazione dei file e autorizzazione separata per costi,
account, credenziali, broker e denaro reale. Questo programma non autorizza
training pesanti, simulazioni scientifiche, valutazioni FULL, ordini o spese.

## Domande e criteri di successo

1. Si possono ricostruire book e portafoglio senza ambiguità di tempo, unità
   contrattuali o contabilità?
2. Quali metodi riducono il rischio di copertura dopo spread, commissioni e
   vincoli, rispetto a baseline forti sullo stesso insieme di contratti?
3. Il risultato sopravvive a dati futuri, stress, inizializzazione e cambio di
   mercato, con dipendenza e selezione multipla trattate esplicitamente?
4. Quale contributo hanno osservabili, struttura economica della policy e
   capacità del modello? Sono ipotesi separate da testare.

La copertura di una passività e la gestione di un conto per produrre rendimento
sono obiettivi distinti. Una riduzione dell'ES non certifica profitto netto.
La gestione autonoma di capitale richiederà un contratto economico separato,
comprensivo della fonte di rendimento, collateral, perdite e rischi di coda.
Non esiste un obiettivo di rendimento promesso o di crescita a un milione.

## Stato ereditato

Fonti: registry, chiusure C-01–C-05, RQ9 e Tier-10 del ramo finale della tesi
`codex/thesis-defense-clarity-v2`, commit
`7e4567c783112f895d93d1ef7a66cd7d405d38ff`.

| Evidenza | Stato da preservare | Uso futuro |
|---|---|---|
| C-01–C-05 | blocchi chiusi; OOD negativo e valore aggiunto latente non confermato | conoscenza e infrastruttura da verificare |
| Tier-10 FULL | dieci semi per famiglia, 100 path OOD; nessuna famiglia batte BS sull'aggregato | evidenza negativa, non holdout disponibile |
| SPY RQ9 | sottostante reale, call sintetiche; 139 finestre SPENT; BS vincitore full-sample | sola analisi descrittiva/provenienza; escluso da sviluppo, tuning e selezione |
| Sensibilità RQ9 successive | retrospettive descrittive su SPENT | nessuna promozione a conferma |
| Residual/FCBSAR | rami separati, non risultati vincenti certificati | audit separato prima di qualsiasi riuso |
| Opzioni vere, book, paper trading | non svolti nella tesi | nuovi blocchi RO |

L'overlap non è l'unica spiegazione dei fallimenti: Tier-10 tratta la dipendenza
e mantiene un esito sfavorevole anche nelle sensibilità senza overlap.
I termini pubblici sono "prototype-based latent-regime" e "soft prototype";
gli identificatori storici quantum restano invariati per compatibilità.

## Sequenza dei blocchi

| Blocco | Deliverable e gate | Stato al checkpoint RO-00 |
|---|---|---|
| RO-00 | fonti finali integrate, obiettivo e contratto dati versionati, master clean, refresh KB unico verificato | chiusura subordinata al receipt post-commit |
| RO-01 | schema, replay L2, ledger e adapter pubblico verificati su fixture; nessun modello | prossimo blocco, solo dopo chiusura RO-00 |
| RO-02 | pilot di raccolta pubblica con universo, durata, quote e storage congelati; data-quality receipt | non iniziato |
| RO-03 | baseline analitiche e accounting del contratto inverse derivati e verificati; protocollo sperimentale congelato | non iniziato |
| RO-04 | confronto limitato di candidati e capacità su development/validation | nessun training autorizzato da RO-00 |
| RO-05 | una conferma su dati nuovi riservati, poi shadow su dati successivi | non iniziato; gate scientifici da precommettere |
| RO-06 | estensione progressiva ad altri sottostanti e mercati | condizionale a RO-05; protocolli separati |

Non si inizia un nuovo blocco prima di chiudere il checkpoint precedente.
Incertezza, esito negativo e carenza di dati sono risultati documentabili;
non autorizzano tentativi illimitati o riuso del test come validation.

## Mercato iniziale e dati

Prima candidata: Deribit, opzioni europee inverse BTC, con un future inverso
a scadenza corrispondente quando effettivamente disponibile. Sono esclusi
inizialmente ETH, opzioni lineari USDC, combo e perpetual. La disponibilità
del future non si presume per ogni scadenza: determina l'universo ammissibile.
Il contratto tecnico è `REAL_OPTIONS_DATA_AND_LEDGER_CONTRACT_V1.md`.

Il futuro pilot richiederà un universo piccolo, metadati completi e limiti
espliciti. Accesso pubblico non significa diritto di redistribuzione né
licenza commerciale. Nessuna chiave, account o endpoint privato è necessario
per lo sviluppo della prima infrastruttura.

Massive Basic è una fonte separata per barre storiche di opzioni US, disponibili
a fine giornata; non sostituisce bid/ask, book o prova di eseguibilità.
Dataset processati degli autori e risorse universitarie sono candidati da
verificare per contenuto, licenza e accesso; non entitlement già disponibili.

## Osservabili e ponte simulazione/realtà

La policy operativa usa informazioni disponibili prima della decisione:
moneyness, tempo residuo, posizione precedente, volatilità realizzata/implicita,
spread, profondità e flusso osservato, capitale e collateral disponibili.
Ogni campo ha unità, timestamp di disponibilità, fonte e missingness.

Share di chartisti, domanda strutturale e stress ABM restano stati del
simulatore. Un proxy empirico non è reso equivalente dallo stesso nome o range.
Le eventuali feature simulate devono attraversare un layer osservativo
compatibile con quello reale, con rumore e ritardi dichiarati.
Provider greeks, volatilità calibrata e regimi inferiti restano stime.

## Confronti candidati e budget scientifico futuro

Ordine iniziale da valutare: delta con IV osservata, delta a frequenza ridotta,
bande/Whalley–Wilmott, correzione semplice del delta; poi No-Transaction Band
Network, residual limitato e piccola GRU/LSTM. Superficie IV multi-strumento,
Neural-SDE e robustificazione avversaria sono estensioni successive.

Questa lista è una roadmap, non un'autorizzazione a eseguire tutti i modelli.
Prima di RO-04 si congelano numero di candidati e semi, budget CPU/GPU,
regola unica di selezione, metriche, margini, correzione di molteplicità,
stop rule e numero di aperture del test. Nessun valore scientifico viene
scelto qui senza un'analisi di potenza e fattibilità su dati di sviluppo.
La rete attuale 9–32–32–1 ha 1.409 parametri: capacità insufficiente è
un'ipotesi, non una spiegazione già provata.

## Disegno temporale e inferenza

- Split cronologici per calendario e gruppi di mercato, non random per riga o
  per contratto. Opzioni contemporanee condividono il rischio sottostante.
- Purging degli intervalli informativi/label che attraversano i confini;
  embargo motivato da orizzonte e informazione effettiva, senza numero arbitrario.
- Preprocessing, IV fit e selezione solo su dati consentiti; join causale
  rispetto al tempo di ricezione, senza esecuzione al prezzo appena osservato
  presupposta istantanea.
- Finestre sovrapposte dentro uno split sono ammesse solo con classificazione
  e dipendenza esplicite; il loro numero non è numero di osservazioni indipendenti.
- Bootstrap/cluster a livello di unità economica e tempo, sensibilità senza
  overlap, campioni effettivi e incertezza sulle code.
- ID/OOD definiti prima di osservare il risultato: periodi, liquidità, volatilità
  e mercati; trasferimento cross-asset distinto da holdout temporale.
- Holdout terminale sigillato; dopo apertura diventa SPENT. Una conferma negativa
  non autorizza rituning sullo stesso campione.
- Confronti a parità di passività, capitale, osservabili ammessi, strumenti,
  esecuzione, costi e budget di ricerca; riferire anche rischio, drawdown,
  turnover, costi, violazioni e dipendenza da singoli periodi.

## Book, contabilità e adattamento

Sono richiesti sia il book di mercato sia il journal di ordini, fill, costi,
cash, collateral, posizioni e settlement. L2 non certifica posizione nella coda.
Il mid/mark non è prezzo di fill. Nessuna esecuzione maker è inferita dal solo L2.

L'autoreplica è una possibile selezione offline di strategie: capitale aggregato
conservato, varianti registrate, confronto champion/challenger su nuovi dati.
Non consente moltiplicazione del capitale, modifica autonoma dei limiti,
promozione sul solo P&L o consultazione ripetuta del medesimo holdout.
Il controllore dei limiti deve essere indipendente dalla policy.

## Calcolo e ambiente

Preflight locale 2026-10-21: i5-1035G1, 8 processori logici, circa 7,76 GiB
RAM utilizzabile, Intel UHD. L'ambiente scientifico canonico è invariato:
Python 3.9.1, NumPy 2.0.2, pandas 2.3.3, SciPy 1.13.1,
torch runtime 2.8.0+cpu, metadata 2.8.0, CUDA None/non disponibile.

Il primo sviluppo usa stdlib e carichi piccoli. GPU gratuite Colab/Kaggle sono
risorse eventuali e non garantite, con ambiente separato e checkpoint.
Non sono una soluzione di hosting continuativo. Nessuna installazione o
modifica dell'interprete canonico è autorizzata per il checkpoint.

## Unico prossimo blocco: RO-01

`REAL_OPTIONS_MARKET_DATA_AND_LEDGER_FOUNDATION_RO01` è lavoro tecnico offline:

- nuova implementazione separata dai producer scientifici della tesi;
- schema con unità e tempi, replay book, journal idempotente e ledger;
- adapter con allowlist di soli endpoint pubblici e rete disabilitata nei test;
- fixture dichiaratamente artificiali, non traiettorie scientifiche;
- massimo 20.000 eventi, 60 secondi CPU totali e 100 MB di output per suite;
- test significativi di gap, duplicati conflittuali, reconnect, causalità,
  conversioni BTC/USD, fill parziali, fee e settlement;
- stop su ambiguità contrattuale, hash/ledger non riconciliati o superamento budget.

Sono esclusi dati live, raccolta continuativa, download storici, stime di
performance, training, selezione di modelli e connessioni broker.
Un pilot reale richiede prima il protocollo numerico RO-02 e il suo checkpoint.
Tempo di esecuzione tecnico: limite sopra indicato. Tempo umano/agent per
implementazione: NON VERIFICATO; nessuna stima di training estrapolata dal PC.

## Fonti esterne consultate il 2026-10-21

- Deribit: https://docs.deribit.com/articles/options-data-collection-best-practices
- Contratti inverse: https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options
- Policy API: https://docs.deribit.com/articles/api-usage-policy
- Massive: https://massive.com/docs/rest/options/aggregates/custom-bars
- No-Transaction Band: https://arxiv.org/abs/2103.01775
- IV surface: https://arxiv.org/abs/2504.06208
- Robust DH: https://arxiv.org/abs/2508.14757
- Neural-SDE: https://github.com/vicaws/neuralSDE-marketmodel
- SPX 0DTE: https://www.sciencedirect.com/science/article/pii/S1572308926000379

Le specifiche dei provider sono versionabili e devono essere riconfermate
prima di acquisizione o uso contrattuale; nessun paper è una garanzia di profitto.
