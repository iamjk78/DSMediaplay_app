"""
The texts of the user guide that are not in the application: the pages that describe how it works and what the actions
without an input template do. `tools/generate_documentation.py` puts them together with what the application knows
itself (the names of the buttons, the actions and the input templates), so the guide cannot name an action that is not
there or leave one out.

Words in curly braces, like {start}, are the texts of the application's own buttons and fields in that language.
"""

# ---- what the actions that have no input template do: key of the action -> {language: text}

ACTIONS = {
    "get_playlist_details": {
        "cz": "Uloží do CSV všechny playlisty a jejich assety (soubory, které playlist obsahuje).",
        "en": "Saves every playlist and its assets (the files in it) to a CSV file."},
    "get_playlist_unused": {
        "cz": "Uloží do CSV playlisty, které nepoužívá žádná skupina, žádný přehrávač jako doplňkový ani žádná zóna jiného playlistu.",
        "en": "Saves to a CSV file the playlists that no group uses, no player as an additional one and no zone of another playlist."},
    "remove_all_unused_playlists": {
        "cz": "Smaže všechny nepoužívané playlisty (ty, které vypíše „CSV - nepoužité playlisty“). Před smazáním se zobrazí seznam a aplikace se zeptá; playlisty se štítkem „test“ se přeskočí.",
        "en": "Deletes all the unused playlists (the ones the unused-playlists CSV lists). The list is shown and confirmed first; playlists labelled “test” are skipped."},
    "get_playlist_settings": {
        "cz": "Uloží do CSV nastavení playlistů (interval dominance). Soubor má tvar, který přijímá „Nastavení - playlisty“.",
        "en": "Saves the settings of the playlists (the domination interval) to a CSV file, in the form the playlist-settings action takes."},
    "get_detailed_groups_with_playlists": {
        "cz": "Uloží do CSV skupiny a jejich playlisty včetně platnosti (data, dny v týdnu, časy). Soubor má tvar, který přijímá „Nastavení - playlisty skupiny (nahradí stávající)“, takže se dá upravit a vložit zpět.",
        "en": "Saves the groups and their playlists, with the validity (dates, days of the week, times), to a CSV file. It has the form the “playlists of the groups” action takes, so it can be edited and pasted back."},
    "get_group_settings": {
        "cz": "Uloží do CSV nastavení skupin: rozlišení, orientaci, automatický restart a deploy, kombinování výchozího playlistu, spánek displeje a přehrávač videa. Tvar odpovídá akci „Nastavení - parametry skupin“.",
        "en": "Saves the settings of the groups to a CSV file: resolution, orientation, automatic restart and deploy, combining the default playlist, the display schedule and the video player. It has the form the group-parameters action takes."},
    "remove_all_expired_playlists": {
        "cz": "Ze všech skupin odebere playlisty, jejichž platnost (zapnuté omezení data) už skončila. Log napíše, které playlisty se ze které skupiny odebraly. Playlist samotný se nemaže.",
        "en": "Takes out of all the groups the playlists whose validity (a switched-on date restriction) has ended. The log says which playlists were taken out of which group. The playlist itself is not deleted."},
    "get_group_unused": {
        "cz": "Uloží do CSV skupiny, do kterých nepatří žádný přehrávač.",
        "en": "Saves to a CSV file the groups that no player belongs to."},
    "remove_all_unused_groups": {
        "cz": "Smaže všechny skupiny, do kterých nepatří žádný přehrávač. Před smazáním se zobrazí seznam a aplikace se zeptá.",
        "en": "Deletes all the groups that no player belongs to. The list is shown and confirmed first."},
    "get_identical_groups": {
        "cz": "Uloží do CSV skupiny, které mají stejné playlisty (se stejnou platností) a stejnou orientaci, tedy skupiny, které by šly sloučit.",
        "en": "Saves to a CSV file the groups that have the same playlists (with the same validity) and the same orientation, that is, groups that could be merged."},
    "get_players_with_groups": {
        "cz": "Uloží do CSV všechny přehrávače a jejich skupiny. Tvar odpovídá akci „Nastavení - skupiny“.",
        "en": "Saves all the players and their groups to a CSV file, in the form the “groups of the players” action takes."},
    "get_player_locations": {
        "cz": "Uloží do CSV všechny přehrávače a jejich lokace. Tvar odpovídá akci „Nastavení - lokace“.",
        "en": "Saves all the players and their locations to a CSV file, in the form the player-location action takes."},
    "get_player_notes": {
        "cz": "Uloží do CSV všechny přehrávače a jejich poznámky. Tvar odpovídá akci „Nastavení - poznámky“.",
        "en": "Saves all the players and their notes to a CSV file, in the form the notes action takes."},
    "get_player_categories": {
        "cz": "Uloží do CSV všechny přehrávače a jejich kategorie (štítky). Tvar odpovídá akci „Nastavení - kategorie“.",
        "en": "Saves all the players and their categories (labels) to a CSV file, in the form the categories action takes."},
    "get_category_unused": {
        "cz": "Uloží do CSV kategorie (štítky), které nepoužívá žádný přehrávač, skupina, asset, playlist ani lokace.",
        "en": "Saves to a CSV file the categories (labels) that no player, group, asset, playlist or location uses."},
    "remove_all_unused_labels": {
        "cz": "Smaže všechny nepoužívané kategorie. Před smazáním se zobrazí seznam a aplikace se zeptá.",
        "en": "Deletes all the unused categories. The list is shown and confirmed first."},
    "get_player_details": {
        "cz": "Uloží do CSV stav přehrávačů: online/offline, poslední spojení a synchronizaci, verzi softwaru, IP adresu, dobu běhu a poslední teplotu.",
        "en": "Saves the state of the players to a CSV file: online/offline, the last connection and sync, the software version, the IP address, the uptime and the last temperature."},
    "show_player_snapshots": {
        "cz": "Otevře tabulku přehrávačů, stejnou jako tlačítko {live_view}: u každého online přehrávače je tlačítko {pb_snapshot}, které ukáže aktuální snímek obrazovky. Viz stránka o tabulce přehrávačů.",
        "en": "Opens the table of the players, the same as the {live_view} button: every online player has a {pb_snapshot} button that shows the current screenshot. See the page about the table of players."},
    "set_player_assets_check": {
        "cz": "Zkontroluje, zda mají online přehrávače uložené soubory, které mají podle své skupiny přehrávat. Aplikace přečte ze serveru soubory skupiny každého přehrávače a zeptá se přehrávače, zda je má ve složce s médii (jeden příkaz, který jen vypíše názvy souborů, nic se nemění). Přehrávače se kontrolují jeden po druhém s pauzou 0,2 s a před každým se znovu ověří, že je online. Přehrávač, který neodpoví do 30 sekund, se přeskočí. V logu je u každého přehrávače vidět, jaké soubory má mít, a chybějící jsou červeně; na konci je souhrn. Vstup je volitelný: prázdný vstup zkontroluje všechny online přehrávače, jinak se zadají názvy přehrávačů.",
        "en": "Checks that the online players have stored the files they are to play according to their group. The application reads the files of the group of each player from the server and asks the player whether it has them in the folder of the media (one command that only lists the names of the files, nothing is changed). The players are checked one by one with a pause of 0.2 s, and before each one it is checked again that it is online. A player that does not answer within 30 seconds is skipped. The log shows for every player which files it should have, the missing ones in red, and a summary at the end. The input is optional: an empty input checks all the online players, otherwise enter the names of the players."},
    "set_player_playback_check": {
        "cz": "Zkontroluje, zda online přehrávače přehrávají. Aplikace se každého přehrávače zeptá (jeden příkaz, který jen vypíše běžící přehrávače videa, nic se nemění) a v logu napíše, co přehrává, nebo červeně, že neběží žádný přehrávač videa, ačkoli playlist video obsahuje. Přehrávače se kontrolují jeden po druhém s pauzou 0,2 s, před každým se znovu ověří, že je online, a přehrávač, který neodpoví do 30 sekund, se přeskočí. Podezřelé přehrávače se po 10 sekundách zkontrolují ještě jednou, protože mezi dvěma videi je na okamžik přehrávač videa vypnutý. Playlist s jediným videem se přehrává ve smyčce jedním procesem, který běží i celé dny, a vypíše se jako „přehrává ve smyčce“. Playlist bez videa (jen obrázky nebo web) se podle procesu posoudit nedá a vypíše se jako takový. Vstup je volitelný: prázdný vstup zkontroluje všechny online přehrávače, jinak se zadají názvy přehrávačů. Doporučení: spouštět několik minut po hromadném nahrání obsahu.",
        "en": "Checks that the online players play. The application asks each player (one command that only lists the video players that run on it, nothing is changed) and writes in the log what it plays, or, in red, that no video player is running although the playlist has a video. The players are checked one by one with a pause of 0.2 s, before each one it is checked again that it is online, and a player that does not answer within 30 seconds is skipped. The suspicious players are checked once more after 10 seconds, because between two videos the video player is off for a moment. A playlist of a single video is played in a loop by one process that runs for days, and is listed as \"playing in a loop\". A playlist without a video (only images or the web) cannot be judged from the process and is listed as such. The input is optional: an empty input checks all the online players, otherwise enter the names of the players. Recommended: run it a few minutes after a mass upload of content."},
    "get_player_versions": {
        "cz": "Uloží do CSV verzi softwaru každého přehrávače.",
        "en": "Saves the software version of every player to a CSV file."},
    "get_player_overview": {
        "cz": "Uloží do CSV přehled přehrávačů: skupinu, verzi, adresu, poslední hlášení, lokaci, teplotu, kategorie, poznámku a aktuální playlist.",
        "en": "Saves an overview of the players to a CSV file: group, version, address, last report, location, temperature, categories, note and the playlist playing now."},
    "get_additional_playlists": {
        "cz": "Uloží do CSV přehrávače, které mají přiřazené doplňkové (additional) playlisty, a ty playlisty.",
        "en": "Saves to a CSV file the players that have additional playlists assigned, and those playlists."},
    "get_locations_plan": {
        "cz": "Uloží do CSV časy zapnutí a vypnutí displejů v lokacích po dnech v týdnu. Tvar odpovídá akci „Nastavení - časy lokace“.",
        "en": "Saves the times the displays are switched on and off in the locations, by day of the week, to a CSV file, in the form the location-times action takes."},
    "remove_all_unused_locations": {
        "cz": "Smaže všechny lokace, ve kterých není žádný přehrávač. Před smazáním se zobrazí seznam a aplikace se zeptá.",
        "en": "Deletes all the locations that no player is in. The list is shown and confirmed first."},
    "get_location_unused": {
        "cz": "Uloží do CSV lokace, ve kterých není žádný přehrávač.",
        "en": "Saves to a CSV file the locations that no player is in."},
    "get_asset_unused": {
        "cz": "Uloží do CSV assety, které neobsahuje žádný playlist (ani jako logo nebo v zóně).",
        "en": "Saves to a CSV file the assets that no playlist contains (not even as a logo or in a zone)."},
    "remove_all_unused_assets": {
        "cz": "Smaže všechny nepoužívané assety. Před smazáním se zobrazí seznam a aplikace se zeptá; assety se štítkem „test“ se přeskočí.",
        "en": "Deletes all the unused assets. The list is shown and confirmed first; assets labelled “test” are skipped."},
    "get_asset_details": {
        "cz": "Uloží do CSV údaje o všech assetech: typ, délku, velikost, rozlišení, období platnosti, playlisty, ve kterých je asset použit, a kategorie.",
        "en": "Saves the details of all the assets to a CSV file: type, duration, size, resolution, validity period, the playlists that use the asset, and categories."},
    "get_asset_validity": {
        "cz": "Uloží do CSV platnost assetů (data a hodiny). Tvar odpovídá akci „Nastavení - platnost assetů“.",
        "en": "Saves the validity of the assets (dates and hours) to a CSV file, in the form the asset-validity action takes."},
    "set_deploy_all_players": {
        "cz": "Spustí Deploy na všechny online přehrávače vybraného účtu, po dávkách. Stejné jako tlačítko {deploy_all}. Před spuštěním se v okně s logem zobrazí počet přehrávačů a aplikace se zeptá; přehrávače bez skupiny a offline přehrávače se přeskočí.",
        "en": "Starts a deploy to all the online players of the selected account, in batches. The same as the {deploy_all} button. Before it starts, the log window shows the number of players and asks; players without a group and offline players are skipped."},
}

# ---- the introductions of the pages of the categories

CATEGORIES = {
    "Playlists": {
        "cz": ("Playlisty", "Akce nad playlisty: jejich assety, nastavení a úklid nepoužívaných."),
        "en": ("Playlists", "Actions on playlists: their assets, settings and the clean-up of unused ones.")},
    "Groups": {
        "cz": ("Skupiny", "Akce nad skupinami: jejich playlisty a platnost, parametry, přejmenování a úklid."),
        "en": ("Groups", "Actions on groups: their playlists and validity, parameters, renaming and the clean-up.")},
    "Players": {
        "cz": ("Přehrávače", "Akce nad přehrávači: skupiny, lokace, poznámky, kategorie, přejmenování, snímky obrazovky a přehledy."),
        "en": ("Players", "Actions on players: groups, locations, notes, categories, renaming, screenshots and overviews.")},
    "Locations": {
        "cz": ("Lokace", "Akce nad lokacemi: časy zapnutí a vypnutí displejů, přejmenování, vytvoření a úklid."),
        "en": ("Locations", "Actions on locations: the times the displays are switched on and off, renaming, creating and the clean-up.")},
    "Assets": {
        "cz": ("Assety", "Akce nad assety (soubory): platnost, přehledy a úklid nepoužívaných."),
        "en": ("Assets", "Actions on assets (files): validity, overviews and the clean-up of unused ones.")},
    "Deploy": {
        "cz": ("Deploy", "Okamžité nasazení obsahu na přehrávače."),
        "en": ("Deploy", "Sending the content to the players at once.")},
}

# ---- the pages of the guide

PAGES = {
"cz": {
"index": ("Úvod", """
<section>
<h2>K čemu aplikace slouží</h2>
<p>DSMediaplay_app je ovládací panel pro zákaznické účty DSMediaplay. Místo klikání ve webovém rozhraní v ní
hromadně měníte nastavení přehrávačů, skupin, playlistů, lokací a assetů: data vložíte z tabulky nebo je stáhnete
do CSV, upravíte a vložíte zpět. Dvě tlačítka otevřou živý přehled přehrávačů.</p>
</section>
<section>
<h2>Jak začít</h2>
<ol>
<li>Přidejte zákaznický účet a login (tlačítko <b>+</b>), zadejte heslo a klikněte na „{save_login_details}“. Heslo se ověří na serveru a uloží do úložiště hesel vašeho počítače, ne do souboru.</li>
<li>Vyberte kategorii a činnost.</li>
<li>Má-li činnost vstup, klikněte na „{input_prompt}“, vložte data podle vzoru a uložte je.</li>
<li>Klikněte na „{start}“. V okně s logem uvidíte průběh. Co nejde vrátit zpět (mazání, Deploy), se před spuštěním zeptá.</li>
</ol>
<p>Podrobnosti jsou na stránce <a href="/cz/window.html">Hlavní okno</a>. Přehled všech činností je v kategoriích nahoře.</p>
</section>
<section>
<h2>Co si zapamatovat</h2>
<ul>
<li>Názvy ve vstupu musí přesně odpovídat názvům na serveru (velikost písmen, diakritika, bez mezer na okrajích).</li>
<li>Akce, které něco mění, nejdřív zkuste na zkušebním účtu nebo na jednom záznamu.</li>
<li>Co se provedlo, se nevrací. Zastavení (STOP) pozastaví jen to, co ještě nezačalo.</li>
</ul>
</section>
"""),
"window": ("Hlavní okno", """
<section>
<h2>Účet, login a heslo</h2>
<p><img class="screenshot" src="/assets/images/main_window_cz.png" alt="Hlavní okno" onerror="this.remove()"></p>
<ul>
<li><b>{customer_account}</b> a <b>{name}</b>: vyberte účet a login. Tlačítka <b>+</b> a <b>−</b> vedle nich účet nebo login přidají či odeberou (s uloženými hesly). Adresa účtu musí začínat <code>https://</code>.</li>
<li><b>{password}</b> a „{save_login_details}“: aplikace se s údaji přihlásí k serveru; když se přihlášení podaří, heslo uloží do úložiště hesel (macOS Klíčenka, Windows Správce pověření). Do konfiguračního souboru se heslo nikdy nezapisuje.</li>
<li>Uživatel zákaznického účtu (kolaborant) má adresu s koncem <code>_xxxx</code> (čtyři písmena za posledním podtržítkem). Aplikace pro něj automaticky použije adresu hlavního účtu, kde jsou přehrávače, a v logu to napíše.</li>
<li>Tlačítka <b>{start}</b>, <b>DEPLOY ALL</b>, <b>Live-view</b> a <b>Výpadky</b> jsou šedá, dokud není vybraný účet, login a heslo. {start} navíc potřebuje vybranou činnost.</li>
</ul>
</section>
<section>
<h2>Kategorie a činnost</h2>
<p>V „{select_entity_type}“ vyberte kategorii (Playlists, Groups, Players, Locations, Assets, Deploy), v „{select_action}“ činnost. Činnosti začínající „CSV“ soubor stahují, ostatní mění data na serveru. Všechny činnosti jsou popsané na stránkách kategorií.</p>
<p>V seznamu činností jsou položky obarvené podle toho, co dělají: <b>zeleně</b> stažení CSV, <b>modře</b> nastavení, přidání, přejmenování a vytvoření, <b>červeně</b> odebrání a smazání. Každá barva tvoří samostatný blok a v něm jsou činnosti podle abecedy. Když kurzor chvíli spočine na činnosti v seznamu, vedle se zobrazí její popis.</p>
<p>Aplikace si pamatuje poslední použitý účet, login, kategorii a činnost a při příštím spuštění je vybere znovu. Činnost, která odebírá nebo maže, se neobnoví, jen její kategorie.</p>
</section>
<section>
<h2>Vstup</h2>
<p>Tlačítko „{input_prompt}“ je vidět jen u činností, které vstup berou. V okně je vzor: šedé řádky začínající <code>#</code> popisují sloupce, poslední řádek je příklad. Vzor můžete smazat, nebo nechat, nezměněné řádky vzoru se při zpracování přeskočí. Sloupce se oddělují tabulátorem (při kopírování z Excelu se vloží samy), jeden záznam je jeden řádek. Řádky se zpracovávají v pořadí, v jakém jsou napsané, a chyby uvádějí číslo řádku tak, jak ho vidíte.</p>
<p>Vstup se zkontroluje celý, než se cokoli změní: když je v něm chyba (neznámý název, špatné datum nebo čas), nic se neprovede a log vypíše všechny chyby.</p>
<p>Log nejdřív napíše, kolik řádků načetl a kolik prázdných řádků mezi nimi přeskočí. Stejný řádek, který je ve vstupu víckrát, se zpracuje jen jednou; log napíše, kolik opakujících se řádků přeskočil. Na konci logu se všechny chyby vypíšou ještě jednou červeně pod nadpisem „Zjištěné chyby:“. Kliknutím na podtržený řádek takové chyby se otevře vstup s textem posledního spuštění a kurzorem na chybném řádku.</p>
</section>
<section>
<h2>Spuštění a okno s logem</h2>
<p>„{start}“ otevře okno s logem. Ukazuje průběh a stav (<i>{working}</i>, <i>{done}</i>, <i>{error}</i>, <i>{cancelled}</i>, <i>{stopped}</i>). Tlačítka:</p>
<ul>
<li><b>STOP</b>: operaci zastaví po dokončení právě zpracovávané dávky. Co se už provedlo, se nevrátí. Po zastavení log napíše, po kolika krocích operace skončila.</li>
<li><b>{close}</b>: zavře okno; když operace ještě běží, nejdřív se zeptá a zastaví ji.</li>
<li><b>{save}</b>: uloží log do textového souboru.</li>
</ul>
<p>Před nevratnou činností (smazání, Deploy) se v okně s logem zobrazí, co se stane (seznam, počet přehrávačů), a aplikace se zeptá; výchozí odpověď je „Ne“.</p>
<p>Mezi jednotlivými kroky dávky (řádky vstupu) je pauza 0,1 sekundy, aby se server nezahltil požadavky; STOP ji ukončí okamžitě. Když se spojení se serverem nepodaří navázat, požadavek se až dvakrát zopakuje (po 2 a po 5 sekundách). Když server neodpovídá ani potom, log napíše srozumitelnou chybu a na konci, kolik kroků proběhlo a které zbývají. Zbylé řádky pak stačí vložit do vstupu znovu.</p>
<p>Před činností, která přepisuje nebo maže data (například nastavení playlistů skupin, odebrání playlistů, smazání nepoužívaných položek), aplikace uloží stav před změnou do složky Stažené soubory (Downloads) jako CSV soubory s názvem <code>účet-backup-data-čas.csv</code>. Log napíše, kam se uložily. Když se záloha nepodaří, činnost se nespustí. Vytváření, přidávání a přejmenování se nezálohuje, v logu je vidět stará i nová hodnota.</p>
</section>
<section>
<h2>Soubory CSV</h2>
<p>Činnosti „CSV - …“ uloží soubor do složky Stažené (Downloads) pod názvem <code>účet-činnost-datum.csv</code> a po dokončení napíšou cestu. Soubor je oddělený středníky v UTF-8 s označením pro tabulkové procesory, takže se diakritika otevře správně. Co v souboru začíná znakem <code>=</code>, <code>@</code> nebo je to slovo se znaménkem, dostane na začátku apostrof, aby ho tabulka nespustila jako vzorec.</p>
</section>
<section>
<h2>Rychlá tlačítka</h2>
<ul>
<li><b>Výpadky</b>: tabulka přehrávačů předfiltrovaná na aktivní přehrávače, které jsou offline, s nejnovějším hlášením nahoře.</li>
<li><b>Live-view</b>: tabulka všech přehrávačů se snímky obrazovky. Viz <a href="/cz/table.html">Tabulka přehrávačů</a>.</li>
<li><b>DEPLOY ALL</b>: nasazení na všechny online přehrávače účtu. Před spuštěním se zobrazí jejich počet a aplikace se zeptá.</li>
</ul>
</section>
<section>
<h2>Nastavení a nápověda</h2>
<p>Tlačítko „{settings}“: jazyk, písmo, velikost písma a Deploy (velikost dávky a interval mezi dávkami v sekundách). Jazyk nebo písmo se po uložení použijí v celém okně; změna dávky nic nezavírá. „{default}“ vrátí výchozí hodnoty. Název okna ukazuje verzi aplikace. Tlačítko „{help}“ otevře tuto příručku.</p>
</section>
<section>
<h2>Aktualizace aplikace</h2>
<p>Tlačítko „{update}“ vedle „{help}“ zjistí, jestli je mezi zveřejněnými verzemi aplikace na GitHubu novější. Když je, nabídne její instalaci: stáhne se instalační soubor pro váš systém, ověří se jeho kontrolní součet a aplikace se přepíše novou verzí. Účty a hesla zůstanou a aplikace se po instalaci sama znovu spustí.</p>
<p>Totéž se pět sekund po spuštění aplikace zkontroluje samo. Když je k dispozici novější verze, ukáže se okno, ve kterém ji můžete <b>nainstalovat hned</b>, nebo <b>odložit</b>: nabídne se znovu při příštím spuštění. Když žádná aktualizace není, nebo se kontrola nepovede (třeba bez internetu), nestane se nic.</p>
<p>Instalace z aplikace nejde, když aplikace běží ze zdrojového kódu, když nemáte právo zápisu do složky, kde je nainstalovaná (macOS), nebo když verze nemá zveřejněný kontrolní součet. Aplikace pak nabídne otevřít stránku verze v prohlížeči, odkud ji lze stáhnout a nainstalovat ručně. Sestavení nejsou podepsaná, proto systém při ruční instalaci zobrazí varování.</p>
</section>
<section>
<h2>Kdyby něco nešlo</h2>
<ul>
<li><b>Přihlášení se nepodařilo ověřit</b>: zkontrolujte heslo a připojení k internetu. Chyba serveru (kód 5xx) se hlásí zvlášť, není to špatné heslo.</li>
<li><b>Chyba při zpracování vstupu</b>: log vypíše číslo řádku a důvod; po opravě vstup uložte znovu.</li>
<li><b>Poškozený soubor s účty</b>: při startu se aplikace zeptá, jestli ho uložit vedle pod jiným názvem a začít s prázdným seznamem. Hesla zůstávají v úložišti hesel.</li>
<li><b>Nápověda se neotevře</b>: aplikace použije volný port, když je 8080 obsazený jinou aplikací.</li>
</ul>
</section>
"""),
"table": ("Tabulka přehrávačů", """
<section>
<p><img class="screenshot" src="/assets/images/players_table_cz.png" alt="Tabulka přehrávačů" onerror="this.remove()"></p>
<p>Otevře ji <b>Live-view</b>, <b>Výpadky</b> nebo činnost Players → „Snímek obrazovky - zobrazit“. Data se stáhnou ze serveru a filtry pracují nad nimi; v dolní části je „{pb_count}“ a čas poslední aktualizace.</p>
</section>
<section>
<h2>Sloupce</h2>
<p>Název, Stav (Online/Offline), Skupina, Lokace, Kategorie, Synchronizováno, Reportováno, Poznámka, Teplota a Verze. Tlačítka vedle „{pb_columns}“ sloupce zobrazují a skrývají (zelené je zobrazený, červené skrytý); Teplota a Verze jsou ve výchozím stavu skryté. Šířku sloupce změníte tažením černé čáry mezi sloupci, „{pb_default_columns}“ vrátí výchozí šířky. Velikost písma v okně mění tlačítka <b>A</b>. Velikost okna, sloupců a písma si aplikace pamatuje pro každý účet.</p>
</section>
<section>
<h2>Filtry a řazení</h2>
<ul>
<li>Pod záhlavím je filtr pro každý sloupec: text (název, poznámka; bez ohledu na velikost písmen a diakritiku), výběr (stav, skupina, lokace, kategorie), stáří (synchronizováno, reportováno) a teplota. Výběr „{pb_all}“ filtr vypne.</li>
<li>„{pb_reset}“ zruší všechny filtry.</li>
<li>Kliknutí na záhlaví sloupce řadí podle něj, druhé kliknutí obrátí směr. Přehrávače, které nemají hodnotu (nikdy se nehlásily, nemají teplotu), jsou vždy na konci.</li>
</ul>
</section>
<section>
<h2>Aktualizace</h2>
<p>„{pb_refresh}“ načte přehrávače znovu (nejdřív za 10 sekund po předchozím načtení); otevřené okno se samo aktualizuje po 10 minutách. Výpadky při otevření data aktualizují vždy.</p>
</section>
<section>
<h2>Snímek obrazovky</h2>
<p>Tlačítko „{pb_snapshot}“ u online přehrávače ukáže aktuální snímek jeho obrazovky v samostatném okně (nejvýše 5 oken najednou); okno si pamatuje velikost. U offline přehrávače je tlačítko červené a nedá se stisknout.</p>
</section>
<section>
<h2>Kopírování textu</h2>
<p>Text v polích tabulky jde označit myší (tažením část textu, dvojklikem slovo, trojklikem celé pole) a zkopírovat běžnou zkratkou (Cmd+C, na Windows Ctrl+C). Pravé tlačítko myši (na macOS i Ctrl+klik) otevře nabídku: „{pb_copy}“ zkopíruje označený text, nebo celé pole, když nic označeno není, a „{pb_copy_row}“ zkopíruje zobrazené sloupce řádku oddělené tabulátory, takže se po vložení do Excelu rozdělí do buněk.</p>
</section>
<section>
<h2>Výpadky</h2>
<p>Tlačítko <b>Výpadky</b> otevře tabulku se smazanými filtry, s viditelným sloupcem „Reportováno“, s filtrem na offline přehrávače, jejichž název obsahuje „aktivni“ (podle názvosloví přehrávačů), a seřazenou tak, že nahoře jsou přehrávače s nejnovějším hlášením.</p>
</section>
"""),
},
"en": {
"index": ("Introduction", """
<section>
<h2>What the application is for</h2>
<p>DSMediaplay_app is a control panel for DSMediaplay customer accounts. Instead of clicking through the web
interface, you change the settings of players, groups, playlists, locations and assets in bulk: paste the data from a
spreadsheet, or download it to CSV, edit it and paste it back. Two buttons open a live overview of the players.</p>
</section>
<section>
<h2>Getting started</h2>
<ol>
<li>Add a customer account and a login (the <b>+</b> button), enter the password and click “{save_login_details}”. The password is checked on the server and stored in the password store of your computer, not in a file.</li>
<li>Select a category and an action.</li>
<li>If the action takes input, click “{input_prompt}”, paste the data following the template and save it.</li>
<li>Click “{start}”. The log window shows the progress. What cannot be undone (deleting, deploy) is asked about first.</li>
</ol>
<p>The details are on the <a href="/en/window.html">Main window</a> page. All the actions are described in the categories above.</p>
</section>
<section>
<h2>Worth remembering</h2>
<ul>
<li>The names in the input must match the names on the server exactly (letter case, accents, no spaces at the ends).</li>
<li>Try an action that changes something on a test account, or on one record, first.</li>
<li>What has been done is not undone. STOP only holds back what has not started yet.</li>
</ul>
</section>
"""),
"window": ("Main window", """
<section>
<h2>Account, login and password</h2>
<p><img class="screenshot" src="/assets/images/main_window_en.png" alt="The main window" onerror="this.remove()"></p>
<ul>
<li><b>{customer_account}</b> and <b>{name}</b>: select the account and the login. The <b>+</b> and <b>−</b> buttons next to them add or remove an account or a login (with the stored passwords). The address of an account must start with <code>https://</code>.</li>
<li><b>{password}</b> and “{save_login_details}”: the application logs in to the server with the details; when that works, it stores the password in the password store (the macOS Keychain, the Windows Credential Manager). The password is never written to the configuration file.</li>
<li>A user of a customer account (a collaborator) has an address ending in <code>_xxxx</code> (four letters after the last underscore). The application uses the address of the main account, where the players are, and says so in the log.</li>
<li>The buttons <b>{start}</b>, <b>DEPLOY ALL</b>, <b>Live-view</b> and <b>Outages</b> are grey until an account, a login and a password are given. {start} also needs a selected action.</li>
</ul>
</section>
<section>
<h2>Category and action</h2>
<p>In “{select_entity_type}” select a category (Playlists, Groups, Players, Locations, Assets, Deploy), in “{select_action}” an action. The actions that start with “CSV” download a file, the others change data on the server. All the actions are described on the pages of the categories.</p>
<p>The entries of the list of actions are coloured by what they do: <b>green</b> for downloading a CSV file, <b>blue</b> for setting, adding, renaming and creating, <b>red</b> for removing and deleting. Each colour is a block of its own, and the actions in it are in alphabetical order. When the pointer rests on an action in the list, a description of it appears next to it.</p>
<p>The application remembers the last used account, login, category and action and selects them again the next time it starts. An action that removes or deletes is not restored, only its category.</p>
</section>
<section>
<h2>Input</h2>
<p>The “{input_prompt}” button is shown only for actions that take input. The window holds a template: the grey lines starting with <code>#</code> describe the columns, the last line is an example. You can delete the template or leave it, the lines of it that were not changed are skipped. The columns are separated by tabs (pasting from a spreadsheet does it), one record is one line. The lines are processed in the order they are written, and errors give the number of the line as you see it.</p>
<p>The input is checked as a whole before anything is changed: when something in it is wrong (an unknown name, a wrong date or time), nothing is done and the log lists all the errors.</p>
<p>The log first says how many lines it read and how many empty lines between them it skips. A line that is in the input more than once is processed only once; the log says how many repeated lines it skipped. At the end of the log all the errors are listed once more in red under the heading “Errors found:”. A click on an underlined line of such an error opens the input with the text of the last run and the cursor on the line with the error.</p>
</section>
<section>
<h2>Running and the log window</h2>
<p>“{start}” opens the log window. It shows the progress and the state (<i>{working}</i>, <i>{done}</i>, <i>{error}</i>, <i>{cancelled}</i>, <i>{stopped}</i>). The buttons:</p>
<ul>
<li><b>STOP</b>: stops the operation when the batch being processed is finished. What has been done is not undone. After a stop the log says after how many steps the operation ended.</li>
<li><b>{close}</b>: closes the window; when the operation is still running, it asks first and stops it.</li>
<li><b>{save}</b>: saves the log to a text file.</li>
</ul>
<p>Before something that cannot be undone (deleting, deploy) the log window shows what is going to happen (the list, the number of players) and asks; the default answer is “No”.</p>
<p>There is a pause of 0.1 second between the steps of a batch (the lines of the input), so as not to overload the server with requests; STOP ends it at once. When a connection to the server cannot be made, the request is repeated up to twice (after 2 and after 5 seconds). If the server does not answer even then, the log gives a clear error and, at the end, how many steps were done and which are left. The remaining lines can then be pasted into the input again.</p>
<p>Before an action that overwrites or deletes data (for example setting the playlists of groups, removing playlists, deleting unused items) the application saves the state before the change to the Downloads folder as CSV files named <code>account-backup-data-time.csv</code>. The log says where they were saved. When the backup cannot be saved, the action does not start. Creating, adding and renaming are not backed up, the log shows the old and the new value.</p>
</section>
<section>
<h2>CSV files</h2>
<p>The “CSV - …” actions save a file to the Downloads folder as <code>account-action-date.csv</code> and say the path when done. The file is separated by semicolons, in UTF-8 with the mark spreadsheet applications need, so the accents open correctly. A text in the file that starts with <code>=</code> or <code>@</code>, or is a word with a sign, gets an apostrophe in front so a spreadsheet does not run it as a formula.</p>
</section>
<section>
<h2>The quick buttons</h2>
<ul>
<li><b>Outages</b>: the table of the players prefiltered to the active players that are offline, with the newest report at the top.</li>
<li><b>Live-view</b>: the table of all the players with screenshots. See <a href="/en/table.html">The table of players</a>.</li>
<li><b>DEPLOY ALL</b>: a deploy to all the online players of the account. Their number is shown and confirmed first.</li>
</ul>
</section>
<section>
<h2>Settings and help</h2>
<p>The “{settings}” button: language, font, font size and Deploy (the size of a batch and the interval between batches in seconds). A new language or font applies to the whole window after saving; changing the batch closes nothing. “{default}” returns the defaults. The title of the window shows the version of the application. The “{help}” button opens this guide.</p>
</section>
<section>
<h2>Updating the application</h2>
<p>The “{update}” button next to “{help}” checks whether a newer version of the application is among the versions published on GitHub. If there is one, it offers to install it: the installation file for your system is downloaded, its checksum is verified and the application is overwritten with the new version. Your accounts and passwords stay, and the application starts again by itself when it is done.</p>
<p>The same check is made by itself five seconds after the application starts. When a newer version is available, a window lets you <b>install it now</b> or <b>postpone it</b>: it is offered again the next time the application starts. When there is no update, or the check fails (without internet, for example), nothing happens.</p>
<p>The installation cannot be done from the application when it runs from the source code, when you have no permission to write to the folder it is installed in (macOS), or when the version has no published checksum. The application then offers to open the page of the version in the browser, where it can be downloaded and installed by hand. The builds are not signed, so the system shows a warning when installing by hand.</p>
</section>
<section>
<h2>If something does not work</h2>
<ul>
<li><b>The login could not be verified</b>: check the password and the internet connection. A server error (code 5xx) is reported separately, it is not a wrong password.</li>
<li><b>An error in the input</b>: the log gives the number of the line and the reason; save the input again after the correction.</li>
<li><b>A damaged accounts file</b>: at the start the application asks whether to keep it next to itself under another name and begin with an empty list. The passwords stay in the password store.</li>
<li><b>The help does not open</b>: the application uses a free port when 8080 is taken by another application.</li>
</ul>
</section>
"""),
"table": ("The table of players", """
<section>
<p><img class="screenshot" src="/assets/images/players_table_en.png" alt="The table of players" onerror="this.remove()"></p>
<p>It is opened by <b>Live-view</b>, <b>Outages</b> or the action Players → “Screenshot - show”. The data is downloaded from the server and the filters work on it; the lower part shows “{pb_count}” and the time of the last update.</p>
</section>
<section>
<h2>Columns</h2>
<p>Name, Status (Online/Offline), Group, Location, Label, Synchronized, Reported, Note, Temperature and Version. The buttons next to “{pb_columns}” show and hide the columns (green is shown, red is hidden); Temperature and Version are hidden by default. Drag the black line between columns to change the width of a column; “{pb_default_columns}” returns the default widths. The <b>A</b> buttons change the size of the text in the window. The application remembers the size of the window, the columns and the text for every account.</p>
</section>
<section>
<h2>Filters and sorting</h2>
<ul>
<li>Under the header there is a filter for every column: text (name, note; letter case and accents do not matter), a choice (status, group, location, label), an age (synchronized, reported) and a temperature. The choice “{pb_all}” switches a filter off.</li>
<li>“{pb_reset}” clears all the filters.</li>
<li>A click on the header of a column sorts by it, a second click reverses the direction. Players that have no value (never reported, no temperature) are always at the end.</li>
</ul>
</section>
<section>
<h2>Updating</h2>
<p>“{pb_refresh}” loads the players again (at the earliest 10 seconds after the previous load); a window that is left open updates itself after 10 minutes. Outages always updates the data when it opens.</p>
</section>
<section>
<h2>Screenshot</h2>
<p>The “{pb_snapshot}” button of an online player shows the current screenshot of its screen in a window of its own (at most 5 windows at a time); the window remembers its size. For an offline player the button is red and cannot be pressed.</p>
</section>
<section>
<h2>Copying text</h2>
<p>The text in the fields of the table can be selected with the mouse (a drag selects a part, a double click a word, a triple click the whole field) and copied with the usual shortcut (Cmd+C, Ctrl+C on Windows). The other mouse button (Ctrl+click too on macOS) opens a menu: “{pb_copy}” copies the selected text, or the whole field when nothing is selected, and “{pb_copy_row}” copies the shown columns of the row separated by tabs, so that pasted into a spreadsheet they fall into cells.</p>
</section>
<section>
<h2>Outages</h2>
<p>The <b>Outages</b> button opens the table with the filters cleared, the column “Reported” shown, a filter for offline players whose name contains “aktivni” (after the naming of the players), and sorted so that the players with the newest report are at the top.</p>
</section>
"""),
},
}

# ---- the words of the pages

WORDS = {
    "cz": {"home": "Domů", "window": "Hlavní okno", "table": "Tabulka přehrávačů", "title": "Uživatelská příručka DSMediaplay",
           "kind_csv": "Stáhne CSV do složky Stažené.", "kind_input": "Vyžaduje vstup („{input_prompt}“).",
           "kind_noinput": "Nevyžaduje vstup, spustí se tlačítkem „{start}“.", "kind_window": "Otevře okno.",
           "input": "Vstup", "example": "Příklad řádku", "how": "Jak na to",
           "how_text": "Vyberte kategorii <b>{category}</b> a činnost „{label}“{input_part}. Pak klikněte na „{start}“.",
           "how_input": ", klikněte na „{input_prompt}“, vložte data a uložte je", "how_plain": "",
           "english": "English", "czech": "Čeština", "lang": "cs", "actions": "Činnosti",
           "intro_actions": "Činnosti této kategorie (název je přesně takový, jaký je v aplikaci):",
           "version": "Verze aplikace"},
    "en": {"home": "Home", "window": "Main window", "table": "The table of players", "title": "DSMediaplay User Guide",
           "kind_csv": "Downloads a CSV file to the Downloads folder.", "kind_input": "Takes input (“{input_prompt}”).",
           "kind_noinput": "Takes no input, it is run with “{start}”.", "kind_window": "Opens a window.",
           "input": "Input", "example": "An example line", "how": "How",
           "how_text": "Select the category <b>{category}</b> and the action “{label}”{input_part}. Then click “{start}”.",
           "how_input": ", click “{input_prompt}”, paste the data and save it", "how_plain": "",
           "english": "English", "czech": "Čeština", "lang": "en", "actions": "Actions",
           "intro_actions": "The actions of this category (the name is exactly as in the application):",
           "version": "Application version"},
}
