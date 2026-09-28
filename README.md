# agentic-pair-programming

[![Patreon](https://img.shields.io/badge/Patreon-AndersBjarby-F96854?logo=patreon&logoColor=white)](https://www.patreon.com/AndersBjarby)

Parprogrammering mellan två agenter: **Claude Code kör, Codex navigerar.**

Varje gång Claude stannar granskar Codex de ocommittade ändringarna mot målet för sessionen. Har navigatören invändningar (blocker/major) får Claude tillbaka dem innan du ser svaret. Claude måste då ta ställning till varje punkt: åtgärda den eller invända med skäl. Du får tillbaka ordet när navigatören säger LGTM, när föraren står fast vid sin lösning, eller efter tre rundor.

## Kom igång

Kräver [Codex CLI](https://github.com/openai/codex) (inloggad), `git` och `python3`.

```bash
./install.sh ~/Projekt/mitt-projekt   # kopierar in hook + /pair-skill, rör inte övriga inställningar
```

Starta om Claude Code i projektet och kör sedan:

```
/pair Lägg till export till CSV i rapportvyn
/pair status
/pair off
```

Committa gärna `.claude/`-filerna i projektet. `.pair/` ignorerar sig själv.

## Så funkar det

| Del | Roll |
|---|---|
| `.claude/hooks/codex-navigator.py` | Stop-hook. Tar diffen (staged + unstaged + ospårat), kör `codex exec --sandbox read-only --output-schema …` och blockerar eller släpper. |
| `.claude/hooks/navigator-prompt.md` | Navigatörens regler: granska mot målet, inga stilnitpickar, verifiera innan du påstår. |
| `.claude/hooks/navigator-schema.json` | Strukturerat svar: `verdict`, `summary`, `comments[{severity, location, comment}]`. |
| `.claude/skills/pair/SKILL.md` | `/pair`: startar/stoppar sessionen och ger Claude förarens regler. |
| `.pair/` (i projektet) | `session.md` (målet, finns = aktivt), `state.json`, `log.md` (hela dialogen). |

Skyddsräcken:
- Utfallet (LGTM eller ändringar) bestäms i koden utifrån allvarlighetsgraden, inte av modellens egen etikett.
- Samma diff granskas aldrig två gånger.
- Max `PAIR_MAX_ROUNDS` (3) rundor per tur.
- Om Codex fallerar släpps Claude alltid.

Miljövariabler: `PAIR_MAX_ROUNDS` och `PAIR_CODEX_MODEL`.
