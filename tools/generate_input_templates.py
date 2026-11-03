"""
Writes assets/input_templates.json, the texts of the "Input Prompt" template for every action that takes input.
The JSON is the source of truth afterwards; this script only keeps the two languages side by side while writing them.
Run from the repository root:  python tools/generate_input_templates.py
"""
import json

CZ_DATE = "Datum: DD.MM.RRRR (např. 31.12.2026)."
CZ_TIME = "Čas: HH:MM (např. 08:00); vypnutí 00:00 se bere jako 23:59, zapnutí musí být dřív než vypnutí."
CZ_TIME_WHOLE_DAY = (CZ_TIME + " Když čas od i čas do zůstanou prázdné, nastaví se celý den: od 00:00 do 23:59 "
                     "(vyplníte-li jen jeden, druhý se doplní stejně).")
CZ_DAYS = ("Dny: kódy oddělené čárkou: mo = pondělí, tu = úterý, we = středa, th = čtvrtek, fr = pátek, "
           "sa = sobota, su = neděle; nebo čísla 1-7 podle API (1 = neděle ... 7 = sobota). Prázdné = všechny dny.")
CZ_BLOCK = ["   a) název playlistu", "   b) platí od: datum DD.MM.RRRR, např. 01.01.2026, nebo prázdné",
            "   c) platí do: datum DD.MM.RRRR, např. 31.12.2026, nebo prázdné",
            "   d) dny v týdnu: kódy mo,tu,we,th,fr,sa,su (nebo čísla 1-7) oddělené čárkou, nebo prázdné",
            "   e) od kolika hodin: čas HH:MM, např. 08:00, nebo prázdné (prázdné = od 00:00)",
            "   f) do kolika hodin: čas HH:MM, např. 18:00, nebo prázdné (prázdné = do 23:59)"]
CZ_CREATE = ("Název ještě nesmí existovat. Nesmí obsahovat středník, tabulátor ani znaky ě š č ř ž ý á í é ß; "
             "doporučeno psát bez diakritiky.")

EN_DATE = "Date: DD.MM.YYYY (e.g. 31.12.2026)."
EN_TIME = "Time: HH:MM (e.g. 08:00); an off time of 00:00 is taken as 23:59, the on time must be earlier than the off time."
EN_TIME_WHOLE_DAY = (EN_TIME + " When both the from and the to time are left empty, the whole day is set: from 00:00 to "
                     "23:59 (if only one is filled, the other is filled in the same way).")
EN_DAYS = ("Days: codes separated by commas: mo = Monday, tu = Tuesday, we = Wednesday, th = Thursday, "
           "fr = Friday, sa = Saturday, su = Sunday; or the API numbers 1-7 (1 = Sunday ... 7 = Saturday). "
           "Empty = every day.")
EN_BLOCK = ["   a) playlist name", "   b) valid from: a date DD.MM.YYYY, e.g. 01.01.2026, or empty",
            "   c) valid to: a date DD.MM.YYYY, e.g. 31.12.2026, or empty",
            "   d) days of the week: codes mo,tu,we,th,fr,sa,su (or numbers 1-7) separated by commas, or empty",
            "   e) from what time: a time HH:MM, e.g. 08:00, or empty (empty = from 00:00)",
            "   f) until what time: a time HH:MM, e.g. 18:00, or empty (empty = until 23:59)"]
EN_CREATE = ("The name must not exist yet. It must not contain a semicolon, a tab or the characters "
             "ě š č ř ž ý á í é ß; writing it without diacritics is recommended.")


def action(summary, columns, example, notes=()):
    return {"summary": summary, "columns": list(columns), "notes": list(notes), "example": list(example)}


cz = {
    "common": {
        "title": "Vzor vstupu",
        "tab": "Sloupce oddělujte tabulátorem (při kopírování z Excelu se vloží samy). Jeden záznam = jeden řádek, bez záhlaví.",
        "names": "Názvy musí přesně odpovídat názvům v DSMediaplay (velikost písmen, diakritika, bez mezer na okrajích).",
        "skip": "Tyto řádky (včetně nezměněného vzorového řádku) se při zpracování přeskočí - můžete je nechat, nebo smazat.",
    },
    "actions": {
        "set_assets_to_playlists": action(
            "Nastavení assetů playlistu: obsah playlistu se nahradí uvedenými assety v uvedeném pořadí.",
            ["1. název playlistu", "2. a další: názvy assetů (libovolný počet, prázdné buňky se přeskočí)"],
            ["<název playlistu>", "<asset 1>", "<asset 2>", "<asset 3>"], ["Jeden řádek na playlist."]),
        "set_playlist_settings": action(
            "Nastavení playlistu: interval dominance.",
            ["1. název playlistu", "2. interval dominance (celé číslo, např. 300; prázdné = dominance vypnutá)"],
            ["<název playlistu>", "300"]),
        "remove_assets_from_playlists": action(
            "Odebrání assetů z playlistu podle klíčového slova.",
            ["1. název playlistu",
             "2. klíčové slovo (odeberou se všechny assety, v jejichž názvu je; rozlišuje velikost písmen)"],
            ["<název playlistu>", "<klíčové slovo>"]),
        "remove_unused_playlists": action(
            "Smazání nepoužívaných playlistů.", ["1. název playlistu (jeden na řádek)"], ["<název playlistu>"],
            ["Playlisty se štítkem \"test\" se přeskočí."]),
        "create_playlist": action(
            "Vytvoření nových playlistů.", ["1. nový název playlistu: ještě nesmí existovat, bez středníku, tabulátoru a znaků ě š č ř ž ý á í é ß; jeden na řádek"], ["<nový název playlistu>"],
            [CZ_CREATE]),
        "set_group_settings": action(
            "Nastavení parametrů skupiny.",
            ["1. název skupiny", "2. rozlišení (text jako v CSV exportu, např. 1080p)",
             "3. orientace (text jako v CSV exportu, např. landscape)",
             "4. automatický restart: čas HH:MM, prázdné = vypnuto",
             "5. automatický deploy: čas HH:MM, prázdné = vypnuto",
             "6. kombinovat výchozí playlist: true / false", "7. přehrávat všechny vyhovující playlisty: true / false",
             "8. LCD zapnout: čas HH:MM", "9. LCD vypnout: čas HH:MM (8 a 9 vyplňte obě, nebo ani jednu)",
             "10. video přehrávač: default / mpv / cvlc"],
            ["<název skupiny>", "1080p", "landscape", "03:00", "04:00", "true", "true", "06:00", "22:00", "default"],
            ["Za ano se bere jen true, 1 nebo yes; cokoli jiného (i \"ano\") je ne.", "Jeden řádek na skupinu."]),
        "set_detailed_playlists_to_groups": action(
            "Nastavení playlistů skupiny: playlisty skupiny se nahradí uvedenými.",
            ["1. název skupiny", "2. výchozí playlist (bez omezení; může být prázdný)",
             "3. a dál: libovolný počet bloků po 6 sloupcích (vždy všech 6; prázdné buňky nechte prázdné, "
             "tabulátory ponechte):"] + CZ_BLOCK,
            ["<název skupiny>", "<výchozí playlist>", "<název playlistu>", "01.01.2026", "31.12.2026",
             "mo,tu,we,th,fr", "08:00", "18:00"], ["Jeden řádek na skupinu.", CZ_DATE, CZ_TIME_WHOLE_DAY, CZ_DAYS]),
        "set_add_detailed_playlist_to_group": action(
            "Přidání playlistů ke skupině: přidají se ke stávajícím, ty zůstanou.",
            ["1. název skupiny",
             "2. a dál: libovolný počet bloků po 6 sloupcích (vždy všech 6; prázdné buňky nechte prázdné, "
             "tabulátory ponechte):"] + CZ_BLOCK,
            ["<název skupiny>", "<název playlistu>", "01.01.2026", "31.12.2026", "mo,tu,we,th,fr", "08:00", "18:00"],
            ["Jeden řádek na skupinu (bez sloupce výchozího playlistu).", CZ_DATE, CZ_TIME_WHOLE_DAY, CZ_DAYS]),
        "remove_expired_playlists": action(
            "Odebrání neplatných (prošlých) playlistů ze skupin.", ["1. název skupiny (jeden na řádek)"],
            ["<název skupiny>"]),
        "remove_playlists_from_group": action(
            "Odebrání playlistů ze skupiny podle klíčového slova.",
            ["1. název skupiny",
             "2. klíčové slovo (odeberou se playlisty, v jejichž názvu je; rozlišuje velikost písmen)"],
            ["<název skupiny>", "<klíčové slovo>"]),
        "remove_playlist_list": action(
            "Odebrání vybraných playlistů ze všech skupin.", ["1. název playlistu (jeden na řádek)"],
            ["<název playlistu>"], ["Neexistující názvy se přeskočí s varováním."]),
        "set_group_rename": action(
            "Přejmenování skupin.", ["1. stávající název skupiny", "2. nový název: bez mezery, čárky, středníku a uvozovek; ještě nesmí existovat ani se opakovat"],
            ["<stávající název>", "<nový název>"],
            ["Nový název nesmí obsahovat mezeru, čárku, středník ani uvozovky, nesmí už existovat ani se opakovat."]),
        "remove_unused_groups": action(
            "Smazání nepoužívaných skupin.", ["1. název skupiny (jeden na řádek)"], ["<název skupiny>"],
            ["Skupiny se štítkem \"test\" se přeskočí."]),
        "create_group": action(
            "Vytvoření nových skupin.", ["1. nový název skupiny: ještě nesmí existovat, bez středníku, tabulátoru a znaků ě š č ř ž ý á í é ß; jeden na řádek"], ["<nový název skupiny>"],
            [CZ_CREATE]),
        "set_groups_to_players": action(
            "Přiřazení skupiny přehrávači.", ["1. název přehrávače", "2. název skupiny"],
            ["<název přehrávače>", "<název skupiny>"], ["Každý přehrávač nejvýše jednou."]),
        "set_player_config_location": action(
            "Přiřazení lokace přehrávači.", ["1. název přehrávače", "2. název lokace"],
            ["<název přehrávače>", "<název lokace>"], ["Každý přehrávač nejvýše jednou."]),
        "set_notes_to_players": action(
            "Nastavení poznámky přehrávače.",
            ["1. název přehrávače", "2. poznámka (může být prázdná = poznámka se smaže; bez tabulátoru a zalomení řádku)"],
            ["<název přehrávače>", "<poznámka>"]),
        "set_player_labels": action(
            "Nastavení kategorií přehrávače.",
            ["1. název přehrávače", "2. a další: názvy kategorií (libovolný počet, musí existovat)"],
            ["<název přehrávače>", "<kategorie 1>", "<kategorie 2>"],
            ["Jeden řádek na přehrávač.", "Řádek jen s názvem přehrávače odebere všechny jeho kategorie."]),
        "remove_additional_playlists": action(
            "Odebrání additional playlistů přehrávačům.",
            ["1. název přehrávače (jeden na řádek; další sloupce se ignorují)"], ["<název přehrávače>"],
            ["Zpracují se jen přehrávače, které additional playlist mají."]),
        "set_player_rename": action(
            "Přejmenování přehrávačů.", ["1. stávající název přehrávače", "2. nový název: s identifikátorem a podtržítkem (PB, PC, PD nebo PE + 4 číslice, např. PB1234_, nebo RPI + 3 číslice), identifikátor se nesmí změnit; bez mezery, čárky, středníku a uvozovek; ještě nesmí existovat"],
            ["<stávající název>", "<nový název>_PB1234_"],
            ["Nový název musí obsahovat identifikátor, za kterým následuje podtržítko: PB, PC, PD nebo PE + 4 číslice "
             "(např. PB1234_), nebo RPI + 3 číslice (např. RPI123_). Identifikátor stávajícího názvu se nesmí změnit. "
             "Nový název nesmí obsahovat uvozovky, čárku, středník ani mezery a nesmí už existovat."]),
        "remove_unused_labels": action(
            "Smazání nepoužívaných kategorií.", ["1. název kategorie (jeden na řádek)"], ["<název kategorie>"],
            ["Kategorie, jejichž název začíná \"test\", se přeskočí."]),
        "create_label": action(
            "Vytvoření nových kategorií.", ["1. nový název kategorie: ještě nesmí existovat, bez středníku, tabulátoru a znaků ě š č ř ž ý á í é ß; jeden na řádek"], ["<nový název kategorie>"],
            [CZ_CREATE]),
        "set_location_plan": action(
            "Nastavení časů zapnutí a vypnutí lokace pro každý den týdne.",
            ["1. název lokace"] + [f"{2 + 2 * day + part}. {name} - {text}: čas HH:MM, např. {example}, nebo prázdné"
                                   for day, name in enumerate(("neděle", "pondělí", "úterý", "středa", "čtvrtek", "pátek",
                                                               "sobota"))
                                   for part, (text, example) in enumerate((("zapnutí", "08:00"), ("vypnutí", "18:00")))],
            ["<název lokace>", "", ""] + ["08:00", "18:00"] * 5 + ["", ""],
            ["Dny jdou od neděle, stejně jako v CSV exportu a v DSMediaplay.",
             "Vždy všech 15 sloupců; prázdná buňka = v ten den se nic nenastaví.", CZ_TIME]),
        "set_location_rename": action(
            "Přejmenování lokací.", ["1. stávající název lokace", "2. nový název: bez mezery (ani jiných bílých znaků); ještě nesmí existovat"],
            ["<stávající název>", "<nový název>"],
            ["Nový název nesmí obsahovat mezeru (ani jiné bílé znaky) a nesmí už existovat."]),
        "remove_unused_locations": action(
            "Smazání nepoužívaných lokací.", ["1. název lokace (jeden na řádek)"], ["<název lokace>"],
            ["Lokace se štítkem \"test\" se přeskočí."]),
        "create_location": action(
            "Vytvoření nových lokací.", ["1. nový název lokace: ještě nesmí existovat, bez středníku, tabulátoru a znaků ě š č ř ž ý á í é ß; jeden na řádek"], ["<nový název lokace>"],
            [CZ_CREATE]),
        "set_asset_validity": action(
            "Nastavení platnosti assetu.",
            ["1. název assetu", "2. platí od: datum nebo prázdné", "3. platí do: datum nebo prázdné",
             "4. od kolika hodin: celá hodina 0-23 (např. 8 nebo 08:00) nebo prázdné",
             "5. do kolika hodin: celá hodina 1-24 (24 nebo 00:00 = do půlnoci) nebo prázdné"],
            ["<název assetu>", "01.01.2026", "31.12.2026", "08:00", "18:00"],
            [CZ_DATE, "Hodiny se použijí jen tehdy, když je vyplněné aspoň jedno datum; bez dat se platnost vypne.",
             "Datum i hodiny se kontrolují při načtení; server bere jen celé hodiny (minuty ne)."]),
        "remove_unused_assets": action(
            "Smazání nepoužívaných assetů.", ["1. název assetu (jeden na řádek)"], ["<název assetu>"],
            ["Assety se štítkem \"test\" se přeskočí."]),
        "set_player_snapshot": action(
            "Snímek obrazovky: uloží obrázek toho, co přehrávač právě zobrazuje. Uloží se do složky "
            "DSMediaplay_snapshots ve stažených souborech.",
            ["1. název přehrávače (jeden na řádek)"], ["<název přehrávače>"],
            ["Přehrávač musí být online, pořízení snímku může trvat několik sekund."]),
        "set_player_assets_check": action(
            "Kontrola assetů přehrávačů: ověří, zda mají online přehrávače soubory a nastavení, které mají mít podle své skupiny.",
            ["1. název přehrávače (jeden na řádek)"], ["<název přehrávače>"],
            ["Vstup je volitelný: prázdný vstup zkontroluje všechny online přehrávače."]),
        "set_player_playback_check": action(
            "Kontrola přehrávání: ověří, zda online přehrávače přehrávají video.",
            ["1. název přehrávače (jeden na řádek)"], ["<název přehrávače>"],
            ["Vstup je volitelný: prázdný vstup zkontroluje všechny online přehrávače."]),
        "set_deploy_selected_groups": action(
            "Deploy vybraných skupin: obsah se nasadí na všechny online přehrávače těchto skupin.",
            ["1. název skupiny (jeden na řádek)"], ["<název skupiny>"]),
    },
}

en = {
    "common": {
        "title": "Input template",
        "tab": "Separate the columns with a tab (copying cells from a spreadsheet inserts them by itself). One record = one line, no header row.",
        "names": "Names must match the names in DSMediaplay exactly (case, diacritics, no spaces at the ends).",
        "skip": "These lines (including the unchanged example line) are skipped when the input is processed - keep or delete them.",
    },
    "actions": {
        "set_assets_to_playlists": action(
            "Set the assets of a playlist: the playlist content is replaced by the listed assets in the listed order.",
            ["1. playlist name", "2. and more: asset names (any number, empty cells are skipped)"],
            ["<playlist name>", "<asset 1>", "<asset 2>", "<asset 3>"], ["One line per playlist."]),
        "set_playlist_settings": action(
            "Set a playlist: the domination interval.",
            ["1. playlist name", "2. domination interval (a whole number, e.g. 300; empty = domination off)"],
            ["<playlist name>", "300"]),
        "remove_assets_from_playlists": action(
            "Remove assets from a playlist by a keyword.",
            ["1. playlist name", "2. keyword (every asset whose name contains it is removed; case-sensitive)"],
            ["<playlist name>", "<keyword>"]),
        "remove_unused_playlists": action(
            "Delete unused playlists.", ["1. playlist name (one per line)"], ["<playlist name>"],
            ["Playlists labelled \"test\" are skipped."]),
        "create_playlist": action(
            "Create new playlists.", ["1. new playlist name: must not exist yet, no semicolon, tab or the characters ě š č ř ž ý á í é ß; one per line"], ["<new playlist name>"], [EN_CREATE]),
        "set_group_settings": action(
            "Set the parameters of a group.",
            ["1. group name", "2. resolution (text as in the CSV export, e.g. 1080p)",
             "3. orientation (text as in the CSV export, e.g. landscape)",
             "4. auto restart: time HH:MM, empty = off", "5. auto deploy: time HH:MM, empty = off",
             "6. combine the default playlist: true / false", "7. play all eligible playlists: true / false",
             "8. LCD on: time HH:MM", "9. LCD off: time HH:MM (fill in both 8 and 9, or neither)",
             "10. video player: default / mpv / cvlc"],
            ["<group name>", "1080p", "landscape", "03:00", "04:00", "true", "true", "06:00", "22:00", "default"],
            ["Only true, 1 or yes mean yes; anything else (even \"ano\") means no.", "One line per group."]),
        "set_detailed_playlists_to_groups": action(
            "Set the playlists of a group: the group's playlists are replaced by the listed ones.",
            ["1. group name", "2. default playlist (no restrictions; may be empty)",
             "3. and more: any number of blocks of 6 columns (always all 6; leave empty cells empty, keep the tabs):"]
            + EN_BLOCK,
            ["<group name>", "<default playlist>", "<playlist name>", "01.01.2026", "31.12.2026", "mo,tu,we,th,fr",
             "08:00", "18:00"], ["One line per group.", EN_DATE, EN_TIME_WHOLE_DAY, EN_DAYS]),
        "set_add_detailed_playlist_to_group": action(
            "Add playlists to a group: they are added to the existing ones, which stay.",
            ["1. group name",
             "2. and more: any number of blocks of 6 columns (always all 6; leave empty cells empty, keep the tabs):"]
            + EN_BLOCK,
            ["<group name>", "<playlist name>", "01.01.2026", "31.12.2026", "mo,tu,we,th,fr", "08:00", "18:00"],
            ["One line per group (there is no default playlist column).", EN_DATE, EN_TIME_WHOLE_DAY, EN_DAYS]),
        "remove_expired_playlists": action(
            "Remove expired playlists from groups.", ["1. group name (one per line)"], ["<group name>"]),
        "remove_playlists_from_group": action(
            "Remove playlists from a group by a keyword.",
            ["1. group name", "2. keyword (playlists whose name contains it are removed; case-sensitive)"],
            ["<group name>", "<keyword>"]),
        "remove_playlist_list": action(
            "Remove the selected playlists from all groups.", ["1. playlist name (one per line)"],
            ["<playlist name>"], ["Names that do not exist are skipped with a warning."]),
        "set_group_rename": action(
            "Rename groups.", ["1. current group name", "2. new name: no space, comma, semicolon or quotation mark; must not exist yet and must not be repeated"], ["<current name>", "<new name>"],
            ["The new name must not contain a space, a comma, a semicolon or quotation marks, must not exist yet "
             "and must not be repeated."]),
        "remove_unused_groups": action(
            "Delete unused groups.", ["1. group name (one per line)"], ["<group name>"],
            ["Groups labelled \"test\" are skipped."]),
        "create_group": action(
            "Create new groups.", ["1. new group name: must not exist yet, no semicolon, tab or the characters ě š č ř ž ý á í é ß; one per line"], ["<new group name>"], [EN_CREATE]),
        "set_groups_to_players": action(
            "Assign a group to a player.", ["1. player name", "2. group name"], ["<player name>", "<group name>"],
            ["Each player at most once."]),
        "set_player_config_location": action(
            "Assign a location to a player.", ["1. player name", "2. location name"],
            ["<player name>", "<location name>"], ["Each player at most once."]),
        "set_notes_to_players": action(
            "Set the note of a player.",
            ["1. player name", "2. note (may be empty = the note is deleted; no tab or line break)"],
            ["<player name>", "<note>"]),
        "set_player_labels": action(
            "Set the categories of a player.",
            ["1. player name", "2. and more: category names (any number, they must exist)"],
            ["<player name>", "<category 1>", "<category 2>"],
            ["One line per player.", "A line with only the player name removes all its categories."]),
        "remove_additional_playlists": action(
            "Remove the additional playlists of players.",
            ["1. player name (one per line; further columns are ignored)"], ["<player name>"],
            ["Only players that have an additional playlist are processed."]),
        "set_player_rename": action(
            "Rename players.", ["1. current player name", "2. new name: with an identifier and an underscore (PB, PC, PD or PE + 4 digits, e.g. PB1234_, or RPI + 3 digits), the identifier must not change; no space, comma, semicolon or quotation mark; must not exist yet"], ["<current name>", "<new name>_PB1234_"],
            ["The new name must contain an identifier followed by an underscore: PB, PC, PD or PE + 4 digits "
             "(e.g. PB1234_), or RPI + 3 digits (e.g. RPI123_). The identifier of the current name must not change. "
             "The new name must not contain quotes, commas, semicolons or whitespace and must not exist yet."]),
        "remove_unused_labels": action(
            "Delete unused categories.", ["1. category name (one per line)"], ["<category name>"],
            ["Categories whose name starts with \"test\" are skipped."]),
        "create_label": action(
            "Create new categories.", ["1. new category name: must not exist yet, no semicolon, tab or the characters ě š č ř ž ý á í é ß; one per line"], ["<new category name>"], [EN_CREATE]),
        "set_location_plan": action(
            "Set the on and off times of a location for each day of the week.",
            ["1. location name"] + [f"{2 + 2 * day + part}. {name} - {text}: a time HH:MM, e.g. {example}, or empty"
                                    for day, name in enumerate(("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
                                                                "Friday", "Saturday"))
                                    for part, (text, example) in enumerate((("on", "08:00"), ("off", "18:00")))],
            ["<location name>", "", ""] + ["08:00", "18:00"] * 5 + ["", ""],
            ["The days start with Sunday, as in the CSV export and in DSMediaplay.",
             "Always all 15 columns; an empty cell = nothing is set for that day.", EN_TIME]),
        "set_location_rename": action(
            "Rename locations.", ["1. current location name", "2. new name: no space (or other white space); must not exist yet"], ["<current name>", "<new name>"],
            ["The new name must not contain a space (or other white space) and must not exist yet."]),
        "remove_unused_locations": action(
            "Delete unused locations.", ["1. location name (one per line)"], ["<location name>"],
            ["Locations labelled \"test\" are skipped."]),
        "create_location": action(
            "Create new locations.", ["1. new location name: must not exist yet, no semicolon, tab or the characters ě š č ř ž ý á í é ß; one per line"], ["<new location name>"], [EN_CREATE]),
        "set_asset_validity": action(
            "Set the validity of an asset.",
            ["1. asset name", "2. valid from: a date or empty", "3. valid to: a date or empty",
             "4. from what hour: a whole hour 0-23 (e.g. 8 or 08:00) or empty",
             "5. until what hour: a whole hour 1-24 (24 or 00:00 = until midnight) or empty"],
            ["<asset name>", "01.01.2026", "31.12.2026", "08:00", "18:00"],
            [EN_DATE, "The hours are used only when at least one date is filled in; with no dates the validity is off.",
             "The dates and the hours are checked when the input is loaded; the server takes whole hours only (no minutes)."]),
        "remove_unused_assets": action(
            "Delete unused assets.", ["1. asset name (one per line)"], ["<asset name>"],
            ["Assets labelled \"test\" are skipped."]),
        "set_player_snapshot": action(
            "Screenshot: saves an image of what the player is showing right now. It is saved to the "
            "DSMediaplay_snapshots folder in Downloads.",
            ["1. player name (one per line)"], ["<player name>"],
            ["The player must be online; taking the screenshot can take a few seconds."]),
        "set_player_assets_check": action(
            "Check player assets: verifies that the online players have the files and settings they should have according to their group.",
            ["1. player name (one per line)"], ["<player name>"],
            ["The input is optional: an empty input checks all the online players."]),
        "set_player_playback_check": action(
            "Check playback: verifies that the online players play a video.",
            ["1. player name (one per line)"], ["<player name>"],
            ["The input is optional: an empty input checks all the online players."]),
        "set_deploy_selected_groups": action(
            "Deploy the selected groups: the content is deployed to all online players of these groups.",
            ["1. group name (one per line)"], ["<group name>"]),
    },
}

assert set(cz["actions"]) == set(en["actions"])
with open("assets/input_templates.json", "w", encoding="utf-8") as file:
    json.dump({"cz": cz, "en": en}, file, indent=2, ensure_ascii=False)
    file.write("\n")
print("zapsáno:", len(cz["actions"]), "činností ve 2 jazycích")
