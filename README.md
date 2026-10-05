# search

Circle to Search for the Linux desktop. Press a shortcut, circle or tap something on the screen, and search for it on Google or Google Lens. For short selections, the app also shows cards with extra information.

It is made for KDE Plasma 6 on Wayland. Other desktops can work, with slower screenshots, but they are not tested.

## How it works

1. The app takes a screenshot and shows it as a full-screen overlay.
2. You circle an area or tap a word.
3. OCR reads the text in that area.
4. A search bar shows the text. You can edit it, search it, copy it, or send the area to Google Lens.
5. If the selection is short, cards appear next to the search bar.

## Cards

| You select | Cards |
|---|---|
| A word | Definition, pronunciation, translation |
| A place | Map, weather for 7 days, facts, places nearby |
| A country | Facts, currency rate, public holidays, population and GDP |
| A person, company or project | Summary, facts, GitHub repository, PyPI or npm package |
| An address | Map |
| An amount of money | The amount in your currency |
| A measurement | The value in your unit system |
| A date | Weekday, month calendar, "add to calendar" link |
| A time with a time zone | Your local time |
| A colour (`#4285F4`, `rgb()`, `hsl()`) | Formats, contrast, shades, matching colours |
| A link, email or phone number | Open, write or call |
| A Nova Poshta or Ukrposhta tracking number | Tracking link |
| A sentence in another language | Translation |
| A short calculation | The result |

Names in other scripts (for example "Львів" or "東京") are found on the Wikipedia of their own language and shown with the English article.

## Requirements

- KDE Plasma 6 on Wayland
- Python 3.10 or newer
- PyQt6
- Tesseract OCR with the English language pack, and packs for other languages you want to read
- Hunspell English dictionary (used to tell words from names)
- `wl-clipboard` (for copying on Wayland)
- `gcc` and GLib development files (to build the screenshot helper)

On Fedora:

```
sudo dnf install python3-pyqt6 tesseract tesseract-langpack-eng hunspell-en-US wl-clipboard gcc glib2-devel
```

Other OCR languages use the package name `tesseract-langpack-<code>`, for example `tesseract-langpack-ukr` or `tesseract-langpack-deu`.

## Install

1. Clone the repository:

   ```
   git clone https://github.com/styanr/search.git
   cd search
   ```

2. Build the screenshot helper:

   ```
   gcc -O2 -o kwin-grab kwin-grab.c $(pkg-config --cflags --libs gio-unix-2.0)
   ```

3. Allow the helper to take screenshots. KWin only gives screenshots to programs that are listed in a desktop file. Create `~/.local/share/applications/circle-search-grab.desktop` with this content, and change the path to where you cloned the repository:

   ```
   [Desktop Entry]
   Type=Application
   Name=Circle to Search screenshot helper
   Exec=/home/you/search/kwin-grab
   NoDisplay=true
   X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2
   ```

   Then run `kbuildsycoca6`.

   Without this step the app still works, but it uses Spectacle for screenshots, which is about 0.5 seconds slower.

4. Add a keyboard shortcut. Open System Settings → Keyboard → Shortcuts → Add New → Command or Script. Use this command, with your path:

   ```
   python3 /home/you/search/circle_search.py
   ```

   Then choose a key, for example Meta+S.

## Use

| Action | Result |
|---|---|
| Circle or scribble | Select an area |
| Tap | Select the word under the cursor |
| Enter | Run the suggested search (text or image) |
| Ctrl+Enter | Search the selected area with Google Lens |
| Ctrl+C | Copy the text |
| Right-click | Clear the selection |
| Esc | Close |

Run with `--instant` to search as soon as you finish circling.

## Settings

Settings are environment variables. To set them for every login, put them in `~/.config/environment.d/circle-search.conf`, one per line:

```
CIRCLE_SEARCH_CONTACT=you@example.com
CIRCLE_SEARCH_OCR_LANGUAGES=jpn+ell
```

| Variable | Default | Meaning |
|---|---|---|
| `CIRCLE_SEARCH_CONTACT` | none | Your email or website. Sent to Wikimedia, OpenStreetMap and MusicBrainz only, because their rules ask for a contact. |
| `CIRCLE_SEARCH_LANGUAGE` | from your regional settings | Language for translations, as a two-letter code (`uk`, `de`). |
| `CIRCLE_SEARCH_CURRENCY` | from your regional settings | Currency to convert to (`UAH`, `EUR`). |
| `CIRCLE_SEARCH_UNITS` | from your regional settings | `metric` or `imperial`. |
| `CIRCLE_SEARCH_OCR_LANGUAGES` | none | Extra OCR languages, joined with `+` (`jpn+ell`). English and your own language are always used. Each extra language makes OCR slower. |
| `CIRCLE_SEARCH_CARDS` | `1` | Set to `0` to turn off cards. |
| `CIRCLE_SEARCH_DEBUG` | `0` | Set to `1` to save each screenshot and OCR result to `~/.cache/circle-search/debug/`. |
| `CIRCLE_SEARCH_ROUTER` | `local` | Which router decides the kind of selection. Only `local` is built in. |

The app reads your language, currency and units from the KDE regional settings (`LC_ADDRESS`, `LC_MONETARY`, `LC_MEASUREMENT`). The card text is in English.

## Services and privacy

OCR runs on your computer. Cards and searches use these online services. The selected text, or the values found in it, is sent to them.

| Service | Used for | Terms |
|---|---|---|
| Google Search | Text search | |
| Google Lens | Image search, only when you choose it. The image is sent from your browser. | |
| Google Translate (unofficial endpoint) | Translations, language detection | May stop working without notice |
| Wikipedia, Wiktionary, Wikivoyage | Summaries, definitions, travel text | CC BY-SA |
| Wikidata and QLever | Facts | CC0 |
| OpenStreetMap (Nominatim and map tiles) | Addresses, maps | ODbL. Light use only. |
| Open-Meteo | Weather, air quality | CC BY 4.0, non-commercial use |
| National Bank of Ukraine | Rates when your currency is UAH | |
| Frankfurter (European Central Bank rates) | Rates for about 30 currencies | |
| currency-api | Rates for other currencies | |
| World Bank | Population and GDP | CC BY 4.0 |
| Nager.Date | Public holidays | |
| GitHub, deps.dev | Repository data | GitHub allows 60 requests per hour without a token |
| PyPI, npm | Package data | |

## Files

| File | Contents |
|---|---|
| `circle_search.py` | The overlay, OCR, selection, search bar, card layout |
| `context_card.py` | Decides what kind of selection it is, and looks up words, names and translations |
| `card_data.py` | Card data model, money, units, dates, times, colours, phones, addresses, maps |
| `providers.py` | Extra cards that build on the main card: weather, facts, currency, repository, nearby, trends, holidays, packages |
| `card_views.py`, `card_shapes.py`, `card_tokens.py` | How each card looks |
| `locale_profile.py` | Reads your language, currency and units |
| `kwin-grab.c` | Takes a screenshot through KWin's D-Bus interface |
| `examples/test-page.html` | A page with examples of every kind of selection, for testing |

## Limitations

- Fast screenshots work only on KDE Plasma (KWin). Other desktops use Spectacle, grim or gnome-screenshot.
- Only the primary screen is used.
- OCR can misread small text or text in fonts with unusual shapes. Check the text in the search bar if a card does not appear.
- A name that is also a common word (for example "React") may show the dictionary meaning instead of the article.
- The Google Translate and Google Lens endpoints are not official APIs and can change.

## License

MIT. See `LICENSE`.

The fonts in `fonts/` (Google Sans Flex and Google Sans) use the SIL Open Font License 1.1. See the license files in that folder.
