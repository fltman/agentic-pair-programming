---
name: pair
description: Starta eller stoppa parprogrammering där Codex är navigatör och granskar Claudes kod varje gång Claude stannar. Kör /pair <mål>, /pair off eller /pair status.
disable-model-invocation: true
argument-hint: "<mål för sessionen> | off | status"
---

# /pair — Claude kör, Codex navigerar

Argument: `$ARGUMENTS`

## Gör så här (i projektroten)

**`off`** — kör `rm -f .pair/session.md`. Säg att parprogrammeringen är avslagen och att loggen finns kvar i `.pair/log.md`. Klart.

**`status`** — visa `.pair/session.md` (om den finns, annars "inte aktiv"), `.pair/state.json` och de sista ~40 raderna av `.pair/log.md`. Klart.

**Allt annat är målet för sessionen:**
1. Kontrollera att katalogen är ett git-repo (`git rev-parse --show-toplevel`) och att `codex` finns (`command -v codex`). Saknas något: säg det och sluta.
2. `mkdir -p .pair && printf '*\n' > .pair/.gitignore && rm -f .pair/state.json`
3. Skriv målet till `.pair/session.md`, ordagrant som användaren skrev det. Lägg gärna till en rad om vilka filer/moduler som berörs om det är uppenbart.
4. Bekräfta kort att paret är igång, och börja sedan arbeta mot målet.

## Dina regler som förare så länge `.pair/session.md` finns

- **Codex är din navigatör.** Varje gång du stannar granskar den dina ocommittade ändringar mot målet. Har den invändningar får du tillbaka dem innan användaren ser ditt svar.
- **Fokuserade steg.** Håll varje tur till ett sammanhängande steg, så att granskningen blir skarp. Hellre tre små varv än ett jättevarv.
- **Säg vad du gjorde och varför** i ditt avslutande meddelande. Navigatören läser det tillsammans med diffen.
- **Ta ställning till varje kommentar.** Åtgärda den, eller invänd med ett konkret skäl. Du ska varken lyda blint eller vifta bort något. Om du står fast vid din lösning: ändra inte koden bara för att få tyst på navigatören. Säg varför, så får användaren avgöra.
- **Committa inte** förrän navigatören sagt LGTM (och bara om användaren vill ha commits). En commit flyttar koden ur granskningens diff.
