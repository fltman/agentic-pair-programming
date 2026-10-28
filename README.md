# agentic-pair-programming

[![Patreon](https://img.shields.io/badge/Patreon-AndersBjarby-F96854?logo=patreon&logoColor=white)](https://www.patreon.com/AndersBjarby)

Parprogrammering mellan två agenter: **Claude Code kör, Codex eller GitHub Copilot navigerar.**

Varje gång Claude stannar granskar navigatören de ocommittade ändringarna mot målet för sessionen. Har navigatören invändningar (blocker/major) får Claude tillbaka dem innan du ser svaret. Claude måste då ta ställning till varje punkt: åtgärda den eller invända med skäl. Du får tillbaka ordet när navigatören säger LGTM, när föraren står fast vid sin lösning, eller efter tre rundor.

## Kom igång

Kräver `git`, `python3` och en inloggad navigatör: [Codex CLI](https://github.com/openai/codex) (standard) eller [GitHub Copilot CLI](https://gh.io/copilot-cli).

```bash
./install.sh ~/Projekt/mitt-projekt   # kopierar in hook + /pair-skill, rör inte övriga inställningar
```

Starta om Claude Code i projektet och kör sedan:

```
/pair Lägg till export till CSV i rapportvyn
/pair auto Bygg import av CSV med validering och tester
/pair status
/pair off
```

### Autopilot

Med `/pair auto <mål>` lämnar paret inte tillbaka ordet efter varje LGTM, utan fortsätter själv med nästa steg. Du får tillbaka ordet när:
- föraren avslutar med `PAIR: KLART` och navigatören har godkänt sista steget,
- föraren behöver ett beslut av dig (`PAIR: FRÅGA`),
- föraren och navigatören inte blir överens, eller navigatören inte blir nöjd på tre rundor,
- föraren stannar utan ny kod, eller
- `PAIR_MAX_STEPS` (8) godkända steg har passerat.

`/pair auto off` stänger av autopiloten men låter paret fortsätta.

Committa gärna `.claude/`-filerna i projektet. `.pair/` ignorerar sig själv.

### GitHub Copilot som navigatör

Sätt `PAIR_NAVIGATOR=copilot`, till exempel i projektets `.claude/settings.json`:

```json
{ "env": { "PAIR_NAVIGATOR": "copilot" } }
```

Copilot CLI installeras med `npm install -g @github/copilot` och loggar in med `copilot login`. Kontot behöver en Copilot-licens, och varje granskning drar AI-krediter (premium requests).

Skillnader mot Codex:
- Copilot saknar `--output-schema`. Schemat skickas med i prompten, och svaret valideras i hooken. Ett svar som inte går att tolka räknas som en misslyckad granskning, och Claude släpps.
- Copilot saknar en read-only-sandlåda. Navigatören körs i stället med `--deny-tool write`, `--deny-tool shell` och `--deny-tool url` och utan inbyggda MCP-servrar. Den kan läsa repot men inte ändra något. Spärren bygger på behörighetsregler, inte på en sandlåda i operativsystemet.
- Prompten skrivs till en temporär fil som Copilot läser. Diffen kan vara större än vad som får plats i ett kommandoradsargument.

## Så funkar det

| Del | Roll |
|---|---|
| `.claude/hooks/codex-navigator.py` | Stop-hook. Tar en ögonblicksbild av arbetsträdet (inklusive ospårade filer, via ett temporärt index), diffar mot senaste LGTM, kör `codex exec --sandbox read-only --output-schema …` (eller `copilot -p` med skrivspärrar) och blockerar eller släpper. Filnamnet är kvar för att befintliga installationer ska fungera. |
| `.claude/hooks/navigator-prompt.md` | Navigatörens regler: granska mot målet, inga stilnitpickar, verifiera innan du påstår. |
| `.claude/hooks/navigator-schema.json` | Strukturerat svar: `verdict`, `summary`, `comments[{severity, location, comment}]`. |
| `.claude/skills/pair/SKILL.md` | `/pair`: startar/stoppar sessionen och ger Claude förarens regler. |
| `.pair/` (i projektet) | `session.md` (målet, finns = aktivt), `autopilot` (finns = på), `state.json`, `log.md` (hela dialogen). |

Skyddsräcken:
- Utfallet (LGTM eller ändringar) bestäms i koden utifrån allvarlighetsgraden, inte av modellens egen etikett.
- Varje granskning gäller bara det som ändrats sedan senaste LGTM. Godkänd kod granskas inte om, och samma tillstånd granskas aldrig två gånger.
- Max `PAIR_MAX_ROUNDS` (3) rundor per tur.
- Om navigatören fallerar, eller svarar med något som inte följer schemat, släpps Claude alltid.

Miljövariabler: `PAIR_NAVIGATOR` (`codex` eller `copilot`), `PAIR_MAX_ROUNDS`, `PAIR_MAX_STEPS`, `PAIR_CODEX_MODEL`, `PAIR_CODEX_BIN`, `PAIR_COPILOT_MODEL` och `PAIR_COPILOT_BIN`.

## Tester

```bash
python3 -m unittest discover tests   # falsk codex och copilot, inga krediter
```
