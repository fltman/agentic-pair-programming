---
name: pair
description: Starta eller stoppa parprogrammering där Codex eller GitHub Copilot är navigatör och granskar Claudes kod varje gång Claude stannar. Kör /pair <mål>, /pair auto <mål>, /pair off eller /pair status.
disable-model-invocation: true
argument-hint: "<mål> | auto <mål> | auto off | off | status"
---

# /pair — Claude kör, Codex eller Copilot navigerar

Argument: `$ARGUMENTS`

## Gör så här (i projektroten)

**`off`** — kör `rm -f .pair/session.md .pair/autopilot`. Säg att parprogrammeringen är avslagen och att loggen finns kvar i `.pair/log.md`. Klart.

**`status`** — visa `.pair/session.md` (om den finns, annars "inte aktiv"), om `.pair/autopilot` finns, `.pair/state.json` och de sista ~40 raderna av `.pair/log.md`. Klart.

**`auto off`** — kör `rm -f .pair/autopilot`. Säg att paret fortsätter men att du nu stannar efter varje godkänt steg. Klart.

**`auto` utan mål** — finns `.pair/session.md`: kör `touch .pair/autopilot`, säg att autopiloten är på för det pågående målet och fortsätt arbeta. Finns den inte: be om ett mål.

**`auto <mål>`** — som nedan, men kör även `touch .pair/autopilot` i steg 2.

**Allt annat är målet för sessionen:**
1. Kontrollera att katalogen är ett git-repo (`git rev-parse --show-toplevel`) och att navigatörens CLI finns: `command -v "${PAIR_COPILOT_BIN:-copilot}"` om `PAIR_NAVIGATOR` är `copilot`, annars `command -v "${PAIR_CODEX_BIN:-codex}"`. Saknas något: säg det och sluta.
2. `mkdir -p .pair && printf '*\n' > .pair/.gitignore && rm -f .pair/state.json .pair/autopilot`
3. Skriv målet till `.pair/session.md`, ordagrant som användaren skrev det. Lägg gärna till en rad om vilka filer/moduler som berörs om det är uppenbart.
4. Bekräfta kort att paret är igång (och om autopiloten är på), och börja sedan arbeta mot målet.

## Dina regler som förare så länge `.pair/session.md` finns

- **Codex eller Copilot är din navigatör** (`PAIR_NAVIGATOR`, standard `codex`). Varje gång du stannar granskar den dina ocommittade ändringar mot målet. Har den invändningar får du tillbaka dem innan användaren ser ditt svar.
- **Fokuserade steg.** Håll varje tur till ett sammanhängande steg, så att granskningen blir skarp. Hellre tre små varv än ett jättevarv.
- **Säg vad du gjorde och varför** i ditt avslutande meddelande. Navigatören läser det tillsammans med diffen.
- **Ta ställning till varje kommentar.** Åtgärda den, eller invänd med ett konkret skäl. Du ska varken lyda blint eller vifta bort något. Om du står fast vid din lösning: ändra inte koden bara för att få tyst på navigatören. Säg varför, så får användaren avgöra.
- **Committa inte** förrän navigatören sagt LGTM (och bara om användaren vill ha commits).

## Autopilot (när `.pair/autopilot` finns)

Efter varje LGTM skickar navigatören dig vidare till nästa steg i stället för att lämna tillbaka ordet. Så här avslutar du:
- **Målet helt nått och verifierat** (kör tester eller programmet om det går): avsluta meddelandet med en egen rad `PAIR: KLART`.
- **Du behöver ett beslut av användaren** (oklart krav, riskabel ändring, vägval med verkliga konsekvenser): ställ frågan och avsluta med `PAIR: FRÅGA`. Gissa inte dig förbi sådant.
- Varje steg ska ändra koden. Stannar du utan ny kod och utan markör pausas autopiloten.
- Det finns ett tak på antal steg (standard 8), så dela upp målet i rimligt stora steg.
